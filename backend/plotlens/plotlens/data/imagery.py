"""
plotlens.data.imagery — Sentinel-2 then-vs-now + spectral change indices.

Same provider pattern as dem.py / osm.py. The believable output here is a
QUANTIFIED change number (e.g. "water cover 38% -> 4%, 2017->2025") computed from
spectral indices, not a vibe.

Indices:
  NDWI = (Green - NIR) / (Green + NIR)   -> water (high = water)
  NDVI = (NIR - Red)  / (NIR + Red)      -> vegetation (high = green)

SyntheticImagery fabricates two dated multiband scenes per archetype so the index
math runs offline. Sentinel2Provider is the live deploy swap, implemented against
the Copernicus Data Space Ecosystem (CDSE) Process API.

--- Two things that will bite you if changed carelessly ---

1. NO-DATA IS NOT NO-CHANGE.
   Sentinel Hub returns an all-ZERO image (HTTP 200) when no scene matches the
   time range and cloud filter. Zeros make NDWI and NDVI both 0, which reads as
   "0% water, 0% vegetation, land cover stable" — a total data failure rendered
   as a reassuring all-clear. Every request therefore asks for a `dataMask`
   band and refuses to draw conclusions below MIN_COVERAGE.

2. RESOLUTION IS ~10 m.
   Sentinel-2 optical bands are 10 m per pixel. A 30x40 ft plot is roughly ONE
   pixel, so this supports VICINITY-scale change detection (was this a tank bed,
   has this block been cleared or built up) and NOT plot-level imagery. Do not
   relabel this output as a picture of the plot.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import datetime as dt
import hashlib
import json
import threading
import time
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
    # Uncertainty, in percentage points, on the THEN-vs-NOW difference.
    # None means single-scene input, so no uncertainty could be estimated.
    veg_noise_pp: float | None = None
    water_noise_pp: float | None = None
    years_used: str | None = None

    def scalars(self):
        return {k: getattr(self, k) for k in
                ("water_then_pct", "water_now_pct", "veg_then_pct", "veg_now_pct",
                 "change_status", "reading", "source",
                 "veg_noise_pp", "water_noise_pp", "years_used")}


def _safe_idx(a, b):
    denom = a + b
    denom = np.where(denom == 0, 1e-6, denom)
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
        def noise():
            return self.rng.normal(0, 0.02, (n, n))
        red = np.full((n, n), 0.22) + noise()
        green = np.full((n, n), 0.20) + noise()
        nir = np.full((n, n), 0.28) + noise()
        red[water_mask] = 0.05; green[water_mask] = 0.10; nir[water_mask] = 0.03
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
            then_water = self._disc(40, 42, 16)
            then_veg = self._disc(30, 30, 28) & ~then_water
            now_water = self._disc(40, 42, 4)
            now_veg = self._disc(30, 30, 18) & ~now_water
        elif self.archetype == "riverside":
            then_water = (np.abs(np.arange(n) - 38)[None, :] < 6) & np.ones((n, n), bool)
            then_veg = self._disc(45, 45, 30) & ~then_water
            now_water = (np.abs(np.arange(n) - 38)[None, :] < 5) & np.ones((n, n), bool)
            now_veg = self._disc(45, 45, 10) & ~now_water
        else:  # upland — stable, sparse
            then_water = empty.copy()
            then_veg = self._disc(40, 40, 14)
            now_water = empty.copy()
            now_veg = self._disc(40, 40, 13)

        tr, tg, tn = self._bands(then_water, then_veg)
        nr, ng, nn = self._bands(now_water, now_veg)
        then = Scene(2017, tr, tg, tn, res)
        now = Scene(2025, nr, ng, nn, res)
        return assemble_result(then, now, lat, lng, f"synthetic:{self.archetype}")


# ----------------------------------------------------------------------
# Live — Sentinel-2 via Copernicus Data Space Ecosystem.
# ----------------------------------------------------------------------
class _TokenCache:
    """
    CDSE access tokens are short-lived — the server reported expires_in=1800
    (30 minutes), NOT the hour that some docs imply. So we read expires_in from
    the response rather than assuming, and refresh with a safety margin.
    Shared across provider instances because a token is per-credential.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[str, float]] = {}   # client_id -> (token, expiry_ts)

    def get(self, requests, token_url, client_id, client_secret, timeout=30):
        with self._lock:
            hit = self._tokens.get(client_id)
            if hit and time.time() < hit[1]:
                return hit[0]

            r = requests.post(
                token_url,
                data={"grant_type": "client_credentials",
                      "client_id": client_id,
                      "client_secret": client_secret},
                timeout=(6, timeout))
            if r.status_code != 200:
                raise RuntimeError(
                    f"CDSE token request failed (HTTP {r.status_code}): "
                    f"{r.text[:200]}")
            data = r.json()
            token = data.get("access_token")
            if not token:
                raise RuntimeError("CDSE token response contained no access_token.")
            # 60s safety margin so a token cannot expire mid-request.
            ttl = float(data.get("expires_in", 1800)) - 60
            self._tokens[client_id] = (token, time.time() + max(ttl, 30))
            return token


_TOKENS = _TokenCache()


class Sentinel2Provider(ImageryProvider):
    """
    Fetches two dated Sentinel-2 L2A composites from CDSE and turns them into a
    quantified land-cover change result.

    Cost note: the Process API bills in processing units, roughly proportional to
    output pixels x bands. Each report makes TWO requests (then + now). OUT_PX is
    deliberately modest — the index statistics do not get more truthful at higher
    resolution, since native ground sampling is 10 m regardless.
    """
    name = "sentinel2"

    TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
                 "/protocol/openid-connect/token")
    PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

    OUT_PX = 256              # output raster size per side
    MIN_COVERAGE = 0.60       # fraction of valid pixels required to trust a scene
    MAX_CLOUD = 40            # percent, passed to the scene filter

    # SEASONAL MATCHING — do not remove.
    # Comparing a full-year window against a part-year window measures SEASON,
    # not land-cover change. Observed on 2026-07-19: with unmatched windows two
    # of three Bengaluru test sites reported vegetation INCREASING by 15-20
    # points across a period of known urbanisation, because NDVI in India swings
    # hugely between dry season and post-monsoon.
    #
    # Both years are therefore sampled over the SAME calendar window. Jan-Mar is
    # chosen for peninsular India: it is the dry season, so cloud is minimal and
    # vegetation is at a consistent phenological state year to year.
    SEASON = (1, 1, 3, 31)    # (start_month, start_day, end_month, end_day)

    # Bands: B04 red, B03 green, B08 NIR (all 10 m), plus dataMask so we can tell
    # "no imagery" apart from "imagery showing nothing".
    EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B03", "B08", "dataMask"]}],
    output: {bands: 4, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  return [s.B04, s.B03, s.B08, s.dataMask];
}
"""

    # Number of years averaged into each composite. Single-year composites are
    # dominated by rainfall noise (see the note in _classify_change); averaging
    # three years cuts that noise by sqrt(3). Cost: this many Process API calls
    # per period, so 3 means 6 calls per uncached report.
    PERIOD_YEARS = 3

    def __init__(self, client_id: str, client_secret: str,
                 then_year: int = 2017, now_year: int | None = None,
                 timeout: int = 90):
        if not (client_id and client_secret):
            raise ValueError(
                "Sentinel2Provider needs BOTH a CDSE client_id and client_secret "
                "(OAuth2 client credentials), not a single API key.")
        self.client_id = client_id
        self.client_secret = client_secret
        self.then_year = then_year
        self.timeout = timeout

        # The "now" season must have already FINISHED, or the composite is built
        # from a partial window and is not comparable with the "then" composite.
        today = dt.date.today()
        candidate = now_year or today.year
        _, _, em, ed = self.SEASON
        if candidate >= today.year and today < dt.date(today.year, em, ed):
            candidate = today.year - 1
        self.now_year = candidate

    # -- internals ----------------------------------------------------
    def _bbox(self, lat, lng, span_m):
        dlat = (span_m / 2) / 111_320
        dlng = (span_m / 2) / (111_320 * np.cos(np.radians(lat)))
        return [lng - dlng, lat - dlat, lng + dlng, lat + dlat]

    def _fetch_year(self, requests, token, bbox, year):
        """
        Return (red, green, nir, coverage) for one year, or raise.

        We ask for a full-year window and let Sentinel Hub mosaic the least
        cloudy pixels. A narrow window over monsoon India frequently returns
        nothing usable.
        """
        sm, sd, em, ed = self.SEASON
        start = dt.date(year, sm, sd)
        end = dt.date(year, em, ed)

        payload = {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {"from": f"{start}T00:00:00Z",
                                      "to": f"{end}T23:59:59Z"},
                        "maxCloudCoverage": self.MAX_CLOUD,
                        "mosaickingOrder": "leastCC",
                    },
                }],
            },
            "output": {
                "width": self.OUT_PX,
                "height": self.OUT_PX,
                "responses": [{"identifier": "default",
                               "format": {"type": "image/tiff"}}],
            },
            "evalscript": self.EVALSCRIPT,
        }

        r = requests.post(self.PROCESS_URL, json=payload,
                          headers={"Authorization": f"Bearer {token}"},
                          timeout=(6, self.timeout))
        if r.status_code != 200:
            raise RuntimeError(
                f"CDSE Process API HTTP {r.status_code} for {year}: {r.text[:200]}")

        try:
            import tifffile
            from io import BytesIO
            arr = tifffile.imread(BytesIO(r.content))
        except ImportError as e:
            raise RuntimeError("Sentinel2Provider needs `tifffile`.") from e
        except Exception as e:
            raise RuntimeError(f"Could not decode CDSE TIFF for {year}: {e}") from e

        arr = np.asarray(arr, dtype=float)
        if arr.ndim != 3 or arr.shape[-1] < 4:
            raise RuntimeError(
                f"Unexpected CDSE response shape for {year}: {arr.shape} "
                "(expected HxWx4).")

        red, green, nir, mask = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
        coverage = float((mask > 0).mean())
        return red, green, nir, coverage

    def _composite(self, requests, token, bbox, years, res_m):
        """
        Average several years into one composite.

        Returns (water_pcts, veg_pcts, representative_scene, years_ok).
        Years that fail or fall below MIN_COVERAGE are skipped rather than
        allowed to drag the average toward zero.
        """
        waters, vegs, scene, ok = [], [], None, []
        for year in years:
            try:
                red, green, nir, cov = self._fetch_year(requests, token, bbox, year)
            except RuntimeError:
                continue
            if cov < self.MIN_COVERAGE:
                continue
            sc = Scene(year=year, red=red, green=green, nir=nir, res_m=res_m)
            w, v = scene_stats(sc)
            waters.append(w)
            vegs.append(v)
            ok.append(year)
            if scene is None:
                scene = sc
        return waters, vegs, scene, ok

    # -- main ---------------------------------------------------------
    def fetch(self, lat, lng, span_m) -> ImageryResult:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("Sentinel2Provider needs `requests` + network.") from e

        token = _TOKENS.get(requests, self.TOKEN_URL,
                            self.client_id, self.client_secret)
        bbox = self._bbox(lat, lng, span_m)
        res_m = span_m / self.OUT_PX

        n = self.PERIOD_YEARS
        then_years = [self.then_year + i for i in range(n)]
        now_years = sorted(self.now_year - i for i in range(n))

        tw, tv, then_scene, then_ok = self._composite(
            requests, token, bbox, then_years, res_m)
        nw, nv, now_scene, now_ok = self._composite(
            requests, token, bbox, now_years, res_m)

        if not then_ok or not now_ok:
            # Refuse rather than let missing imagery read as "no change".
            raise RuntimeError(
                f"Sentinel-2 returned no usable scenes for "
                f"{'the baseline period' if not then_ok else 'the current period'} "
                f"(tried {then_years if not then_ok else now_years}). Likely "
                "persistent cloud or no matching acquisition. Not returning a "
                "result, because absent imagery would otherwise read as "
                "'no change detected'.")

        def mean(xs):
            return sum(xs) / len(xs)

        def sd(xs):
            if len(xs) < 2:
                return None
            m = mean(xs)
            return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5

        # Pool the within-period spread, then propagate to the DIFFERENCE of two
        # means: sd/sqrt(k) per period, combined in quadrature.
        def diff_noise(a, b):
            sa, sb = sd(a), sd(b)
            if sa is None or sb is None:
                return None
            pooled = ((sa ** 2 + sb ** 2) / 2) ** 0.5
            return pooled * ((1 / len(a) + 1 / len(b)) ** 0.5)

        stats = (mean(tw), mean(nw), mean(tv), mean(nv))
        veg_noise = diff_noise(tv, nv)
        water_noise = diff_noise(tw, nw)

        yrs = f"{then_ok[0]}-{then_ok[-1]} vs {now_ok[0]}-{now_ok[-1]}"
        period = f"between {then_ok[0]}-{then_ok[-1]} and {now_ok[0]}-{now_ok[-1]}"

        return assemble_result(
            then_scene, now_scene, lat, lng,
            f"CDSE Sentinel-2 L2A, {len(then_ok)}+{len(now_ok)}-year composites "
            f"({yrs}), matched {_month_name(self.SEASON[0])}-"
            f"{_month_name(self.SEASON[2])} window (~10 m/px)",
            stats=stats, veg_noise=veg_noise, water_noise=water_noise,
            period=period, years_used=yrs)


# ----------------------------------------------------------------------
# Shared: turn two scenes into the quantified change result.
# ----------------------------------------------------------------------
def _month_name(m):
    return ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m]


WATER_T, VEG_T = 0.2, 0.3   # index thresholds


def scene_stats(scene: Scene):
    """Percentage of the frame classed as water and as vegetation."""
    return (float((scene.ndwi() > WATER_T).mean() * 100),
            float((scene.ndvi() > VEG_T).mean() * 100))


def assemble_result(then: Scene, now: Scene, lat, lng, source,
                    stats=None, veg_noise=None, water_noise=None,
                    period=None, years_used=None) -> ImageryResult:
    """
    `stats` lets a caller supply MULTI-YEAR averaged percentages instead of
    deriving them from the two representative scenes. The scenes are still
    carried for rendering.
    """
    if stats is None:
        wt, vt = scene_stats(then)
        wn, vn = scene_stats(now)
    else:
        wt, wn, vt, vn = stats

    status, reading = _classify_change(wt, wn, vt, vn, then.year, now.year,
                                       veg_noise=veg_noise,
                                       water_noise=water_noise,
                                       period=period)
    return ImageryResult(
        then=then, now=now,
        water_then_pct=round(wt, 1), water_now_pct=round(wn, 1),
        veg_then_pct=round(vt, 1), veg_now_pct=round(vn, 1),
        change_status=status, reading=reading,
        lat=lat, lng=lng, source=source,
        veg_noise_pp=round(veg_noise, 1) if veg_noise is not None else None,
        water_noise_pp=round(water_noise, 1) if water_noise is not None else None,
        years_used=years_used,
    )


def _classify_change(wt, wn, vt, vn, then_year=2017, now_year=2025,
                     veg_noise=None, water_noise=None, period=None):
    """
    Thresholds are heuristic and stated in the output, so a reader can judge them.

    NOISE FLOOR — the reason this function takes uncertainty arguments:
        Sampling Whitefield every year from 2017 to 2026 in a matched Jan-Mar
        window gave vegetation cover of 36-50% with NO trend: standard deviation
        5.3 points, so any two-year difference carries ~7.4 points of noise.
        The 43%->38% "decline" originally reported was smaller than that. It was
        year-to-year rainfall variation being read as land-cover change.

        Water is the opposite: across the same ten years it stayed within
        0.0-0.9%, a standard deviation of ~0.3 points. The 8-point water
        threshold below is roughly 27 sigma, so that detector is trustworthy.

        We therefore only report a vegetation change when it exceeds twice the
        measured noise, and say plainly when it does not.
    """
    span = period or f"between {then_year} and {now_year}"
    water_drop = wt - wn
    veg_drop = vt - vn

    water_floor = 2 * water_noise if water_noise else 0.0
    if water_drop > max(8, water_floor) and wt > 10:
        return "flag", (f"Water cover fell from {wt:.0f}% to {wn:.0f}% {span}. "
                        f"A water body appears to have been filled — verify "
                        f"drainage and whether the land was a tank/pond bed "
                        f"before buying.")

    if veg_noise is not None:
        floor = 2 * veg_noise
        if abs(veg_drop) < floor:
            return "good", (
                f"No detectable change in vegetation {span}: "
                f"{vt:.0f}% to {vn:.0f}%, a difference of {abs(veg_drop):.1f} "
                f"points against year-to-year variation of about "
                f"{veg_noise:.1f} points for this area. Vegetation cover here "
                f"swings naturally with rainfall, so a change this size cannot "
                f"be distinguished from normal variation.")
        if veg_drop >= floor and veg_drop > 10:
            return "caution", (
                f"Vegetation fell from {vt:.0f}% to {vn:.0f}% {span}, a drop of "
                f"{veg_drop:.1f} points against year-to-year variation of about "
                f"{veg_noise:.1f} points. This exceeds normal variation — "
                f"confirm what changed and why.")
        if veg_drop <= -floor:
            return "good", (
                f"Vegetation increased from {vt:.0f}% to {vn:.0f}% {span} "
                f"(variation for this area is about {veg_noise:.1f} points).")
        return "good", (f"Land cover is broadly stable {span} "
                        f"(water {wt:.0f}%→{wn:.0f}%, "
                        f"vegetation {vt:.0f}%→{vn:.0f}%).")

    # No uncertainty available (single-scene / synthetic input).
    if veg_drop > 20:
        return "caution", (f"Vegetation dropped from {vt:.0f}% to {vn:.0f}% {span}. "
                           f"Significant clearing — confirm what changed and why.")
    return "good", (f"Land cover is broadly stable {span} "
                    f"(water {wt:.0f}%→{wn:.0f}%, "
                    f"vegetation {vt:.0f}%→{vn:.0f}%).")


class CachedImagery(ImageryProvider):
    """
    In-memory TTL cache.

    The previous version was a pass-through despite its name. That matters more
    here than elsewhere: each live fetch costs TWO Process API calls against a
    processing-unit quota. Land cover changes on a scale of years, so a long TTL
    costs nothing in accuracy.
    """

    def __init__(self, inner: ImageryProvider, cache_dir="cache", ttl_s: int = 86400):
        self.inner = inner
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl_s = ttl_s
        self.name = f"cached({inner.name})"
        self._store: dict[str, tuple[float, ImageryResult]] = {}

    def fetch(self, lat, lng, span_m) -> ImageryResult:
        key = hashlib.sha1(
            f"img|{self.inner.name}|{lat:.4f}|{lng:.4f}|{span_m:.0f}".encode()
        ).hexdigest()[:16]
        hit = self._store.get(key)
        if hit and (time.time() - hit[0]) < self.ttl_s:
            return hit[1]
        res = self.inner.fetch(lat, lng, span_m)
        self._store[key] = (time.time(), res)
        return res
