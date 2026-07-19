"""
plotlens.data.dem — elevation data providers.

The engine depends ONLY on the DEMProvider interface below, never on a concrete
source. To go live you swap SyntheticDEM for SRTMProvider in config — nothing
in the engine changes.

Real deployment note:
    SRTMProvider.fetch() is written against the OpenTopography global DEM API
    (Copernicus GLO-30 / SRTM). It needs `rasterio` and network access, both
    unavailable in this sandbox, so it is import-guarded and falls back cleanly.
    The synthetic provider produces a realistic bowl-in-slope tile so the whole
    pipeline runs and renders today.
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
    res_m: float             # ground resolution per pixel, metres
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
# Synthetic provider — runs anywhere, no network. Models terrain archetypes
# so the engine has something realistic to chew on.
# ----------------------------------------------------------------------
class SyntheticDEM(DEMProvider):
    name = "synthetic"

    # archetype -> (base_elev, slope_x, slope_y, bowl_depth)
    ARCHETYPES = {
        "filled_pond": (845, 0.06, 0.05, 7.0),    # dip in a slope -> water collects
        "riverside":   (678, 0.015, 0.02, 2.0),   # near-flat floodplain
        "upland":      (911, 0.09, 0.07, 0.0),     # well-drained, no bowl
    }

    def __init__(self, archetype: str = "filled_pond", seed: int = 7):
        self.archetype = archetype
        self.seed = seed

    def fetch(self, lat, lng, span_m, res_m) -> DEMTile:
        from scipy.ndimage import gaussian_filter
        n = max(40, int(span_m / res_m))
        rng = np.random.default_rng(self.seed)
        y, x = np.mgrid[0:n, 0:n]
        base, sx, sy, depth = self.ARCHETYPES.get(self.archetype, self.ARCHETYPES["filled_pond"])
        z = base - sx * x - sy * y
        if depth:
            cx, cy, sigma = n * 0.48, n * 0.52, n * 0.12
            z += -depth * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma ** 2)))
        z += rng.normal(0, 0.25, z.shape)
        z = gaussian_filter(z, 1.2)
        return DEMTile(z=z, res_m=res_m, lat=lat, lng=lng, span_m=span_m,
                       source=f"synthetic:{self.archetype}")


# ----------------------------------------------------------------------
# Real provider — OpenTopography global DEM. Deploy swap.
# ----------------------------------------------------------------------
class SRTMProvider(DEMProvider):
    name = "srtm"
    API = "https://portal.opentopography.org/API/globaldem"

    def __init__(self, api_key: str, dem_type: str = "COP30"):
        self.api_key = api_key
        self.dem_type = dem_type  # COP30 = Copernicus GLO-30, free data

    def fetch(self, lat, lng, span_m, res_m) -> DEMTile:
        # Requires rasterio + network; guarded so import never breaks the engine.
        try:
            import rasterio  # noqa
            import requests
            from io import BytesIO
        except ImportError as e:
            raise RuntimeError(
                "SRTMProvider needs `rasterio` and `requests` installed, plus network "
                "access. Use SyntheticDEM for local dev."
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
        r = requests.get(self.API, params=params, timeout=30)
        r.raise_for_status()
        with rasterio.open(BytesIO(r.content)) as ds:
            z = ds.read(1).astype(float)
        z[z < -1000] = np.nan  # nodata guard
        return DEMTile(z=z, res_m=res_m, lat=lat, lng=lng, span_m=span_m,
                       source=f"OpenTopography:{self.dem_type}")


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
