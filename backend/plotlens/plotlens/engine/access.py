"""
plotlens.engine.access — distances & access metrics from OSM features.

Pure geometry. Computes nearest road / water / emergency / transit distances and
a transparent access read. Pairs with terrain.py: the water distance here feeds
the same Water & Drainage category as the flow analysis.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math


@dataclass
class AccessResult:
    nearest_road_m: float
    nearest_road_name: str
    nearest_water_m: float
    nearest_water_name: str
    nearest_transit_m: float
    nearest_emergency_m: float
    emergency_kind: str
    adjacent_landuse: str
    coverage: str
    access_status: str
    reading: str

    def scalars(self):
        return {k: v for k, v in asdict(self).items()}


def _pt_dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _min_dist_to_feature(f):
    """Min distance from plot centre (0,0) to any vertex of a feature."""
    return min(_pt_dist((0, 0), c) for c in f.coords)


def _nearest(features, predicate):
    best_d, best_f = float("inf"), None
    for f in features:
        if predicate(f):
            d = _min_dist_to_feature(f)
            if d < best_d:
                best_d, best_f = d, f
    return best_d, best_f


def analyse(osm) -> AccessResult:
    feats = osm.features

    d_road, f_road = _nearest(feats, lambda f: f.kind == "road")
    d_water, f_water = _nearest(feats, lambda f: f.kind == "water")
    d_transit, _ = _nearest(feats, lambda f: f.kind == "poi" and f.subtype in ("bus_stop", "station"))
    d_emerg, f_emerg = _nearest(feats, lambda f: f.kind == "poi" and f.subtype in ("fire_station", "hospital", "clinic"))

    # adjacent land use = the landuse polygon whose centroid is closest
    landuses = [f for f in feats if f.kind == "landuse"]
    adj = "unknown"
    if landuses:
        def centroid_dist(f):
            cx = sum(c[0] for c in f.coords) / len(f.coords)
            cy = sum(c[1] for c in f.coords) / len(f.coords)
            return math.hypot(cx, cy)
        adj = min(landuses, key=centroid_dist).subtype

    status, reading = _classify(d_road, d_emerg, osm.coverage)

    return AccessResult(
        nearest_road_m=round(d_road, 0) if d_road < 1e8 else -1,
        nearest_road_name=(f_road.name if f_road else "") or "unnamed road",
        nearest_water_m=round(d_water, 0) if d_water < 1e8 else -1,
        nearest_water_name=(f_water.name if f_water else "") or "—",
        nearest_transit_m=round(d_transit, 0) if d_transit < 1e8 else -1,
        nearest_emergency_m=round(d_emerg, 0) if d_emerg < 1e8 else -1,
        emergency_kind=(f_emerg.subtype if f_emerg else "—"),
        adjacent_landuse=adj,
        coverage=osm.coverage,
        access_status=status,
        reading=reading,
    )


def _classify(d_road, d_emerg, coverage):
    note = ""
    if coverage == "sparse":
        note = " Note: OSM coverage is sparse here — absence of a feature may mean it is unmapped, not absent."
    if d_road > 5e7:
        return "caution", "No mapped road access within the analysis window." + note
    if d_road <= 50 and d_emerg < 6000:
        return "good", f"Road access ~{d_road:.0f} m; emergency services within ~{d_emerg/1000:.1f} km." + note
    if d_road <= 150:
        return "good", f"Road access ~{d_road:.0f} m away." + note
    return "caution", f"Nearest mapped road ~{d_road:.0f} m — check the access path on the ground." + note
