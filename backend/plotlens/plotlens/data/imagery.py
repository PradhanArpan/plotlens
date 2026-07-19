"""
plotlens.data.imagery — Sentinel-2 then-vs-now + spectral change indices.

Same provider pattern as dem.py / osm.py. The believable output here is a
QUANTIFIED change number (e.g. "water cover 38% -> 4%, 2017->2025") computed from
spectral indices, not a vibe.

Indices:
  NDWI = (Green - NIR) / (Green + NIR)   -> water (high = water)
  NDVI = (NIR - Red)  / (NIR + Red)      -> vegetation (high = green)

SyntheticImagery fabricates two dated multiband scenes per archetype so the index
math runs and renders today. Sentinel2Provider is the live deploy swap (needs a
licensed imagery API + network).
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import numpy as np


@dataclass
class Scene:
    """One dated multiband image patch. Bands as 2D arrays, reflectance 0..1."""
    year: int
    red: np.ndarray
    green: np.ndarray
    nir: np.ndarray
    res_m: float

    def ndwi(self):
        return _safe_idx(self.green, self.nir)

    def ndvi(self):
        return _safe_idx(self.nir, self.red)


@dataclass
class ImageryResult:
    then: Scene
    now: Scene
    water_then_pct: float
    water_now_pct: float
    veg_then_pct: float
    veg_now_pct: float
    change_status: str
    reading: str
    lat: float
    lng: float
    source: str

    def scalars(self):
        return {k: getattr(self, k) for k in
                ("water_then_pct", "water_now_pct", "veg_then_pct", "veg_now_pct",
                 "change_status", "reading", "source")}


def _safe_idx(a, b):
    denom = a + b
    denom[denom == 0] = 1e-6
    return (a - b) / denom


class ImageryProvider:
    name = "abstract"
    def fetch(self, lat, lng, span_m) -> ImageryResult:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Synthetic — fabricates believable then/now scenes per archetype.
# ----------------------------------------------------------------------
class SyntheticImagery(ImageryProvider):
    name = "synthetic"

    def __init__(self, archetype="filled_pond", seed=7, size=80):
        self.archetype = archetype
        self.size = size
        self.rng = np.random.default_rng(seed)

    def _bands(self, water_mask, veg_mask):
        """Build red/green/nir from land-cover masks (rough but index-correct)."""
        n = self.size
        noise = lambda: self.rng.normal(0, 0.02, (n, n))
        # bare soil baseline
        red = np.full((n, n), 0.22) + noise()
        green = np.full((n, n), 0.20) + noise()
        nir = np.full((n, n), 0.28) + noise()
        # water: low NIR, moderate green -> high NDWI
        red[water_mask] = 0.05; green[water_mask] = 0.10; nir[water_mask] = 0.03
        # vegetation: high NIR, low red -> high NDVI
        red[veg_mask] = 0.06; green[veg_mask] = 0.14; nir[veg_mask] = 0.45
        return np.clip(red, 0, 1), np.clip(green, 0, 1), np.clip(nir, 0, 1)

    def _disc(self, cx, cy, r):
        n = self.size
        yy, xx = np.mgrid[0:n, 0:n]
        return (xx - cx) ** 2 + (yy - cy) ** 2 < r ** 2

    def fetch(self, lat, lng, span_m) -> ImageryResult:
        n = self.size
        res = span_m / n
        empty = np.zeros((n, n), dtype=bool)

        if self.archetype == "filled_pond":
            # THEN: a pond + surrounding veg.  NOW: pond gone, less veg.
            then_water = self._disc(40, 42, 16)
            then_veg = self._disc(30, 30, 28) & ~then_water
            now_water = self._disc(40, 42, 4)
            now_veg = self._disc(30, 30, 18) & ~now_water
        elif self.archetype == "riverside":
            then_water = (np.abs(np.arange(n) - 38)[None, :] < 6) & np.ones((n, n), bool)
            then_veg = self._disc(45, 45, 30) & ~then_water
            now_water = (np.abs(np.arange(n) - 38)[None, :] < 5) & np.ones((n, n), bool)
            now_veg = self._disc(45, 45, 10) & ~now_water  # riparian cleared
        else:  # upland — stable, sparse
            then_water = empty.copy()
            then_veg = self._disc(40, 40, 14)
            now_water = empty.copy()
            now_veg = self._disc(40, 40, 13)

        tr, tg, tn = self._bands(then_water, then_veg)
        nr, ng, nn = self._bands(now_water, now_veg)
        then = Scene(2017, tr, tg, tn, res)
        now = Scene(2025, nr, ng, nn, res)
        return self._assemble(then, now, lat, lng, f"synthetic:{self.archetype}")

    def _assemble(self, then, now, lat, lng, source):
        return assemble_result(then, now, lat, lng, source)


# ----------------------------------------------------------------------
# Live — Sentinel-2 via a licensed imagery API. Deploy swap.
# ----------------------------------------------------------------------
class Sentinel2Provider(ImageryProvider):
    name = "sentinel2"

    def __init__(self, api_key: str, then_year=2017, now_year=None):
        self.api_key = api_key
        self.then_year = then_year
        self.now_year = now_year

    def fetch(self, lat, lng, span_m) -> ImageryResult:
        # Deployment: request two least-cloudy scenes (then_year, latest) for the
        # bbox from the imagery API, read R/G/NIR bands into arrays, then call
        # assemble_result(). Needs network + the provider SDK; not runnable here.
        raise RuntimeError(
            "Sentinel2Provider requires a licensed imagery API key and network. "
            "Use SyntheticImagery in dev. On deploy: fetch least-cloud scenes for "
            "then/now, read R/G/NIR bands, then call assemble_result()."
        )


# ----------------------------------------------------------------------
# Shared: turn two scenes into the quantified change result.
# ----------------------------------------------------------------------
def assemble_result(then: Scene, now: Scene, lat, lng, source) -> ImageryResult:
    WATER_T, VEG_T = 0.2, 0.3   # index thresholds
    wt = float((then.ndwi() > WATER_T).mean() * 100)
    wn = float((now.ndwi() > WATER_T).mean() * 100)
    vt = float((then.ndvi() > VEG_T).mean() * 100)
    vn = float((now.ndvi() > VEG_T).mean() * 100)

    status, reading = _classify_change(wt, wn, vt, vn)
    return ImageryResult(
        then=then, now=now,
        water_then_pct=round(wt, 1), water_now_pct=round(wn, 1),
        veg_then_pct=round(vt, 1), veg_now_pct=round(vn, 1),
        change_status=status, reading=reading,
        lat=lat, lng=lng, source=source,
    )


def _classify_change(wt, wn, vt, vn):
    water_drop = wt - wn
    veg_drop = vt - vn
    if water_drop > 8 and wt > 10:
        return "flag", (f"Water cover fell from {wt:.0f}% to {wn:.0f}% since {2017}. "
                        f"A water body appears to have been filled — verify drainage and "
                        f"whether the land was a tank/pond bed before buying.")
    if veg_drop > 20:
        return "caution", (f"Vegetation dropped from {vt:.0f}% to {vn:.0f}%. Significant "
                           f"clearing — confirm what changed and why.")
    return "good", (f"Land cover is broadly stable (water {wt:.0f}%→{wn:.0f}%, "
                    f"vegetation {vt:.0f}%→{vn:.0f}%).")


class CachedImagery(ImageryProvider):
    def __init__(self, inner: ImageryProvider, cache_dir="cache"):
        self.inner = inner
        self.dir = Path(cache_dir); self.dir.mkdir(parents=True, exist_ok=True)
        self.name = f"cached({inner.name})"

    def fetch(self, lat, lng, span_m) -> ImageryResult:
        # Cache only the scalar change summary + small RGB previews would go here;
        # for dev we recompute (scenes are cheap synthetically).
        return self.inner.fetch(lat, lng, span_m)
