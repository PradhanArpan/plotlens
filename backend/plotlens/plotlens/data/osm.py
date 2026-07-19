"""
plotlens.data.osm — OpenStreetMap features (roads, water, land use, POIs).

Same pattern as dem.py: engine depends only on the OSMProvider interface.
SyntheticOSM runs anywhere; OverpassProvider is the live deploy swap.

Coverage caveat (surface this to users): OSM completeness varies. Urban India is
well-mapped; rural plots may have missing roads/water. "Nothing nearby" can mean
genuinely nothing OR not-yet-mapped — the result carries a `coverage` flag so the
UI can say which it cannot distinguish.

Mirror note (why this file has fallback logic):
    The main overpass-api.de endpoint began returning HTTP 406 Not Acceptable to
    many clients around April 2026, independent of query content. 406 is a
    content-negotiation refusal, so we now send explicit Accept and User-Agent
    headers (OSM policy rejects stock library user agents anyway), and we try
    several mirrors in order. The mirror that actually answered is recorded in
    the result's `source` string so a report never hides where data came from.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import math
import numpy as np


# ---- geometry: features are points/lines in metres relative to plot centre ----
@dataclass
class Feature:
    kind: str          # road | water | landuse | poi
    subtype: str       # e.g. residential, river, hospital, fire_station, lake
    # coordinates in METRES from plot centre (E,N). Points: 1 coord. Lines/areas: many.
    coords: list = field(default_factory=list)
    name: str = ""


@dataclass
class OSMResult:
    features: list                      # list[Feature]
    span_m: float
    coverage: str                       # "dense" | "sparse"
    lat: float
    lng: float
    source: str

    def of(self, kind):
        return [f for f in self.features if f.kind == kind]


class OSMProvider:
    name = "abstract"

    def fetch(self, lat, lng, span_m) -> OSMResult:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Synthetic — realistic feature sets per archetype so the engine + renderer run.
# ----------------------------------------------------------------------
class SyntheticOSM(OSMProvider):
    name = "synthetic"

    def __init__(self, archetype="filled_pond", seed=7):
        self.archetype = archetype
        self.rng = np.random.default_rng(seed)

    def fetch(self, lat, lng, span_m) -> OSMResult:
        feats = []
        h = span_m / 2

        def line(x0, y0, x1, y1, steps=8):
            return [[x0 + (x1 - x0) * t, y0 + (y1 - y0) * t]
                    for t in np.linspace(0, 1, steps)]

        if self.archetype == "filled_pond":
            feats += [
                Feature("road", "tertiary", line(-h, -40, h, 30), "Outer Ring Rd"),
                Feature("road", "residential", line(-30, -h, -10, h), ""),
                Feature("water", "pond", self._blob(150, -60, 30), "Seasonal pond"),
                Feature("landuse", "residential", self._blob(-300, 200, 220), ""),
                Feature("landuse", "farmland", self._blob(400, -350, 260), ""),
                Feature("poi", "bus_stop", [[480, -110]], "Bus stop"),
                Feature("poi", "fire_station", [[3200, 900]], "Fire station"),
                Feature("poi", "hospital", [[2100, -1500]], "Clinic"),
            ]
            cov = "dense"
        elif self.archetype == "riverside":
            feats += [
                Feature("road", "track", line(-h, 120, h, -120), "Approach track"),
                Feature("water", "river", line(-h, -55, h, -75, 20), "Cauvery channel"),
                Feature("landuse", "farmland", self._blob(0, 500, 400), ""),
                Feature("poi", "bus_stop", [[1700, 400]], "Bus stop"),
                Feature("poi", "fire_station", [[8800, 1200]], "Fire station"),
            ]
            cov = "sparse"
        else:  # upland
            feats += [
                Feature("road", "secondary", line(-h, -20, h, 10), "Tumkur Rd"),
                Feature("water", "stream", line(1300, -h, 1450, h, 12), "Minor stream"),
                Feature("landuse", "vacant", self._blob(0, 0, 500), ""),
                Feature("poi", "bus_stop", [[850, 300]], "Bus stop"),
                Feature("poi", "fire_station", [[5900, -800]], "Fire station"),
            ]
            cov = "sparse"

        return OSMResult(features=feats, span_m=span_m, coverage=cov,
                         lat=lat, lng=lng, source=f"synthetic:{self.archetype}")

    def _blob(self, cx, cy, r, steps=14):
        ang = np.linspace(0, 2 * math.pi, steps)
        rr = r * (0.8 + 0.2 * self.rng.random(steps))
        return [[cx + rr[i] * math.cos(a), cy + rr[i] * math.sin(a)]
                for i, a in enumerate(ang)]


# ----------------------------------------------------------------------
# Live — Overpass API. Deploy swap. Needs network + requests.
# ----------------------------------------------------------------------
class OverpassProvider(OSMProvider):
    """
    Queries Overpass with mirror fallback.

    Mirror order is empirical, not theoretical. Tested from Bengaluru on
    2026-07-19: overpass-api.de answered correctly once proper Accept and
    User-Agent headers were sent, while kumi.systems and private.coffee both
    failed. The 406 problem was a header problem, not a host problem — so the
    main host goes FIRST and the others are genuine fallbacks.

    Timeouts are deliberately split: a short connect/response budget for the
    first attempt keeps a dead mirror from adding ~40s to every report.
    """
    name = "overpass"

    MIRRORS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    ]

    # OSM policy requires an identifying User-Agent; stock library agents are
    # explicitly not acceptable. Accept must be set or some hosts return 406.
    HEADERS = {
        "User-Agent": "PlotLens/1.0 (geospatial plot analysis; contact via github.com/PradhanArpan/plotlens)",
        "Accept": "application/json",
    }

    def __init__(self, mirrors: list | None = None, timeout: int = 25):
        self.mirrors = mirrors or list(self.MIRRORS)
        self.timeout = timeout

    def _build_query(self, s, w, n, e) -> str:
        # No leading whitespace on lines: some mirrors are fussy about the
        # query body, and a dedented query costs nothing to send.
        return (
            "[out:json][timeout:25];\n"
            "(\n"
            f'way["highway"]({s},{w},{n},{e});\n'
            f'way["natural"="water"]({s},{w},{n},{e});\n'
            f'way["waterway"]({s},{w},{n},{e});\n'
            f'way["landuse"]({s},{w},{n},{e});\n'
            f'node["amenity"~"hospital|fire_station|clinic"]({s},{w},{n},{e});\n'
            f'node["highway"="bus_stop"]({s},{w},{n},{e});\n'
            ");\n"
            "out geom;\n"
        )

    def fetch(self, lat, lng, span_m) -> OSMResult:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "OverpassProvider needs `requests` + network. Use SyntheticOSM in dev."
            ) from e

        dlat = (span_m / 2) / 111_320
        dlng = (span_m / 2) / (111_320 * math.cos(math.radians(lat)))
        s, n, w, e = lat - dlat, lat + dlat, lng - dlng, lng + dlng
        q = self._build_query(s, w, n, e)

        errors = []
        for url in self.mirrors:
            host = url.split("/")[2]
            try:
                # (connect, read): a dead mirror should fail in seconds, not
                # stall the whole report waiting for a read that never comes.
                r = requests.post(url, data={"data": q},
                                  headers=self.HEADERS,
                                  timeout=(6, self.timeout))
                if r.status_code != 200:
                    errors.append(f"{host}: HTTP {r.status_code}")
                    continue
                try:
                    data = r.json()
                except ValueError:
                    errors.append(f"{host}: 200 but body was not JSON")
                    continue
            except Exception as ex:
                errors.append(f"{host}: {type(ex).__name__}")
                continue

            feats = self._parse(data, lat, lng)
            cov = "dense" if len(feats) > 12 else "sparse"
            return OSMResult(features=feats, span_m=span_m, coverage=cov,
                             lat=lat, lng=lng, source=f"overpass:{host}")

        raise RuntimeError("All Overpass mirrors failed — " + "; ".join(errors))

    def _parse(self, data, clat, clng):
        feats = []
        mlat = 111_320
        mlng = 111_320 * math.cos(math.radians(clat))
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            name = tags.get("name", "")

            def to_m(latlng):
                return [(latlng["lon"] - clng) * mlng, (latlng["lat"] - clat) * mlat]

            if el["type"] == "node":
                c = [to_m(el)]
                amen = tags.get("amenity") or (
                    "bus_stop" if tags.get("highway") == "bus_stop" else None)
                if amen:
                    feats.append(Feature("poi", amen, c, name))
            elif el["type"] == "way" and "geometry" in el:
                c = [to_m(p) for p in el["geometry"]]
                if "highway" in tags:
                    feats.append(Feature("road", tags["highway"], c, name))
                elif tags.get("natural") == "water" or "waterway" in tags:
                    feats.append(Feature("water", tags.get("waterway", "water"), c, name))
                elif "landuse" in tags:
                    feats.append(Feature("landuse", tags["landuse"], c, name))
        return feats


class CachedOSM(OSMProvider):
    def __init__(self, inner: OSMProvider, cache_dir="cache"):
        self.inner = inner
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.name = f"cached({inner.name})"

    def fetch(self, lat, lng, span_m) -> OSMResult:
        raw = f"osm|{self.inner.name}|{lat:.4f}|{lng:.4f}|{span_m:.0f}"
        key = hashlib.sha1(raw.encode()).hexdigest()[:16]
        p = self.dir / f"{key}.osm.json"
        if p.exists():
            d = json.loads(p.read_text())
            feats = [Feature(**f) for f in d["features"]]
            return OSMResult(feats, d["span_m"], d["coverage"],
                             d["lat"], d["lng"], d["source"] + " (cached)")
        res = self.inner.fetch(lat, lng, span_m)
        p.write_text(json.dumps({
            "features": [vars(f) for f in res.features],
            "span_m": res.span_m, "coverage": res.coverage,
            "lat": res.lat, "lng": res.lng, "source": res.source,
        }))
        return res
