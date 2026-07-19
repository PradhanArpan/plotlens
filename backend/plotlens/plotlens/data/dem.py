"""
plotlens.data.dem — elevation data providers.

The engine depends ONLY on the DEMProvider interface below, never on a concrete
source. To go live you swap SyntheticDEM for SRTMProvider in config — nothing
in the engine changes.

Real deployment note:
    SRTMProvider.fetch() is written against the OpenTopography global DEM API.
    It needs `requests`, `tifffile` and `imagecodecs` (OpenTopography returns
    LZW-compressed GeoTIFFs; tifffile delegates LZW decoding to imagecodecs).
    It does NOT need rasterio or GDAL.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import numpy as np


@dataclass
class DEMTile:
    """A square elevation grid covering a geographic window."""
    z: np.ndarray            # 2D float array, metres
    res_m: float             # ground resolution per pixel, metres (TRUE spacing)
    lat: float               # centre latitude
    lng: float               # centre longitude
    span_m: float            # side length of window, metres
    source: str              # provenance string, shown to user for credibility

    @property
    def n(self) -> int:
        return self.z.shape[0]


class DEMProvider:
    """Interface. Implementations must return a DEMTile for a centre + span."""
    name = "abstract"

    def fetch(self, lat: float, lng: float, span_m: float, res_m: float) -> DEMTile:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Synthetic provider — runs anywhere, no network.
# ----------------------------------------------------------------------
class SyntheticDEM(DEMProvider):
    name = "synthetic"

    # archetype -> (base_elev, slope_x, slope_y, bowl_depth)
    ARCHETYPES = {
        "filled_pond": (845, 0.06, 0.05, 7.0),    # dip in a slope -> water collects
        "riverside":   (678, 0.015, 0.02, 2.0),   # near-flat floodplain
        "upland":      (911, 0.09, 0.07, 0.0),    # well-drained, no bowl
    }

    def __init__(self, archetype: str = "filled_pond", seed: int = 7):
        self.archetype = archetype
        self.seed = seed

    def fetch(self, lat, lng, span_m, res_m) -> DEMTile:
        from scipy.ndimage import gaussian_filter
        n = max(40, int(span_m / res_m))
        rng = np.random.default_rng(self.seed)
        y, x = np.mgrid[0:n, 0:n]
        base, sx, sy, depth = self.ARCHETYPES.get(
            self.archetype, self.ARCHETYPES["filled_pond"])
        z = base - sx * x - sy * y
        if depth:
            cx, cy, sigma = n * 0.48, n * 0.52, n * 0.12
            z += -depth * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma ** 2)))
        z += rng.normal(0, 0.25, z.shape)
        z = gaussian_filter(z, 1.2)
        return DEMTile(z=z, res_m=res_m, lat=lat, lng=lng, span_m=span_m,
                       source=f"synthetic:{self.archetype}")


# ----------------------------------------------------------------------
# Real provider — OpenTopography global DEM.
# ----------------------------------------------------------------------
class SRTMProvider(DEMProvider):
    """
    Fetches real elevation from OpenTopography.

    dem_type options (all free, all need an API key):
        COP30    — Copernicus GLO-30 (~30 m). DEFAULT. Cleaner, fewer voids,
                   and measurably better terrain detail: tested side by side at
                   Whitefield, Bengaluru (400 m window), COP30 resolved 15.6 m
                   relief / 6.73% mean slope where SRTMGL1 reported only 8.9 m
                   / 3.00%. SRTM smooths away real banks and cuts that matter
                   to a plot buyer.
        SRTMGL1  — NASA SRTM, 1 arc-second (~30 m). Widely used baseline, kept
                   as a fallback if COP30 errors for a given location.
        AW3D30   — ALOS World 3D (~30 m).
        SRTMGL3  — SRTM 3 arc-second (~90 m). Coarser, smaller downloads.

    Honesty note on resolution:
        The native pixel spacing of these datasets is ~30 m. If the caller asks
        for a finer res_m we resample so the engine gets the grid shape it
        expects, but `native_res_m` records the TRUE information content and it
        is surfaced in `source`. res_m on the returned tile is always the actual
        spacing of the grid being returned, so slope math is correct.
    """
    name = "srtm"
    API = "https://portal.opentopography.org/API/globaldem"

    # Approximate native ground sampling distance, metres.
    NATIVE_RES = {
        "SRTMGL1": 30.0, "COP30": 30.0, "AW3D30": 30.0,
        "NASADEM": 30.0, "SRTMGL3": 90.0, "COP90": 90.0,
    }

    def __init__(self, api_key: str, dem_type: str = "COP30", timeout: int = 60):
        if not api_key:
            raise ValueError("SRTMProvider requires an OpenTopography API key.")
        self.api_key = api_key
        self.dem_type = dem_type
        self.timeout = timeout

    # -- helpers ------------------------------------------------------
    @staticmethod
    def _fill_voids(z: np.ndarray) -> np.ndarray:
        """
        Replace NaN voids using nearest-valid-neighbour.

        SRTM voids cluster near water and steep terrain. Leaving NaN in place
        poisons every downstream smoothing/contour step, so we fill rather than
        propagate. If the tile is entirely void we raise — silently returning
        flat ground would be worse than failing loudly.
        """
        mask = np.isnan(z)
        if not mask.any():
            return z
        if mask.all():
            raise RuntimeError(
                "DEM tile is entirely nodata. The location may be outside the "
                "dataset's coverage (SRTM covers 60N to 56S)."
            )
        from scipy.ndimage import distance_transform_edt
        # indices of the nearest valid cell for every cell
        _, idx = distance_transform_edt(mask, return_indices=True)
        return z[tuple(idx)]

    @staticmethod
    def _resample(z: np.ndarray, target_n: int) -> np.ndarray:
        """Bilinear resample a square grid to target_n x target_n."""
        if z.shape[0] == target_n and z.shape[1] == target_n:
            return z
        from scipy.ndimage import zoom
        factor = (target_n / z.shape[0], target_n / z.shape[1])
        return zoom(z, factor, order=1)  # order=1 = bilinear

    # -- main ---------------------------------------------------------
    def fetch(self, lat, lng, span_m, res_m) -> DEMTile:
        try:
            import requests
            import tifffile
            from io import BytesIO
        except ImportError as e:
            raise RuntimeError(
                "SRTMProvider needs `requests` and `tifffile` (plus `imagecodecs` "
                "for LZW decoding). Use SyntheticDEM for offline dev."
            ) from e

        # metres -> degrees (approx; fine for small windows)
        dlat = (span_m / 2) / 111_320
        dlng = (span_m / 2) / (111_320 * np.cos(np.radians(lat)))
        params = {
            "demtype": self.dem_type,
            "south": lat - dlat, "north": lat + dlat,
            "west": lng - dlng, "east": lng + dlng,
            "outputFormat": "GTiff", "API_Key": self.api_key,
        }

        r = requests.get(self.API, params=params, timeout=self.timeout)

        # OpenTopography reports errors as XML with a non-200 code. Surface the
        # message rather than a bare HTTPError, because the common causes
        # (bad key, quota exhausted, bbox too large) are all user-fixable.
        if r.status_code != 200:
            detail = r.text[:300].strip()
            raise RuntimeError(
                f"OpenTopography returned HTTP {r.status_code} for "
                f"{self.dem_type}: {detail}"
            )
        if r.content[:2] not in (b"II", b"MM"):
            raise RuntimeError(
                "OpenTopography returned a 200 but the body is not a GeoTIFF. "
                f"First bytes: {r.content[:80]!r}"
            )

        try:
            raw = tifffile.imread(BytesIO(r.content))
        except ValueError as e:
            # Most likely: LZW compression with imagecodecs missing.
            raise RuntimeError(
                f"Could not decode the GeoTIFF ({e}). If this mentions LZW or a "
                "codec, run: pip install imagecodecs"
            ) from e

        z = np.asarray(raw, dtype=float)
        if z.ndim == 3:          # single-band expected; take the first band
            z = z[0] if z.shape[0] < z.shape[-1] else z[..., 0]

        z[z < -1000] = np.nan     # SRTM/COP voids are large negatives
        z = self._fill_voids(z)

        # TRUE spacing of what the API actually returned, before any resampling.
        native_res_m = span_m / z.shape[0]

        target_n = max(40, int(span_m / res_m))
        z = self._resample(z, target_n)
        true_res_m = span_m / z.shape[0]   # honest post-resample spacing

        src = f"OpenTopography:{self.dem_type} (native ~{native_res_m:.0f} m/px)"
        return DEMTile(z=z, res_m=true_res_m, lat=lat, lng=lng,
                       span_m=span_m, source=src)


# ----------------------------------------------------------------------
# Disk cache wrapper — the thing that makes the economics work.
# Wraps ANY provider; keys by rounded coords+span so nearby requests reuse tiles.
# ----------------------------------------------------------------------
class CachedDEM(DEMProvider):
    def __init__(self, inner: DEMProvider, cache_dir: str = "cache"):
        self.inner = inner
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.name = f"cached({inner.name})"

    def _key(self, lat, lng, span_m, res_m) -> str:
        raw = f"{self.inner.name}|{lat:.4f}|{lng:.4f}|{span_m:.0f}|{res_m:.1f}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def fetch(self, lat, lng, span_m, res_m) -> DEMTile:
        key = self._key(lat, lng, span_m, res_m)
        npz, meta = self.dir / f"{key}.npz", self.dir / f"{key}.json"
        if npz.exists() and meta.exists():
            m = json.loads(meta.read_text())
            z = np.load(npz)["z"]
            return DEMTile(z=z, res_m=m["res_m"], lat=m["lat"], lng=m["lng"],
                           span_m=m["span_m"], source=m["source"] + " (cached)")
        tile = self.inner.fetch(lat, lng, span_m, res_m)
        np.savez_compressed(npz, z=tile.z)
        meta.write_text(json.dumps({
            "res_m": tile.res_m, "lat": tile.lat, "lng": tile.lng,
            "span_m": tile.span_m, "source": tile.source,
        }))
        return tile
