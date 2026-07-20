"""
plotlens.engine.plot_geometry — vector analysis of a drawn plot boundary.

WHY THIS MODULE IS VECTOR-ONLY:
    A typical 30x40 ft plot is ~111 m² — about ONE Sentinel-2 pixel and an
    eighth of a COP30 elevation pixel. Clipping rasters to a polygon that small
    is averaging a single pixel and adds nothing. OSM geometry, by contrast, is
    exact. So a drawn boundary is used for what it can honestly improve:
    area, perimeter, road frontage, orientation, boundary-to-feature distances,
    and setback feasibility. Raster statistics are only meaningful for parcels
    over ~0.5 acre (~2000 m², 20+ imagery pixels); that gate lives in the
    pipeline, not here.

COORDINATE FRAME:
    Same local frame as plotlens.data.osm: metres east (x) and north (y) of a
    reference point. Callers convert lat/lng once via `to_local` using the
    polygon centroid as reference — the identical equirectangular approximation
    the OSM provider uses, so plot edges and OSM features share one frame and
    distances between them are directly comparable.

    All functions are pure and numpy-free where practical, so this file is
    trivially testable anywhere.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import math

M_PER_DEG_LAT = 111_320.0

# Conversions plot buyers actually use.
SQFT_PER_M2 = 10.7639
SQM_PER_ACRE = 4046.86
SQM_PER_GUNTA = 101.17     # 1 gunta = 121 sq yd, standard in Karnataka
SQM_PER_CENT = 40.4686     # used in Kerala/TN listings

# Below this, per-pixel raster stats are one-pixel averages; keep vicinity framing.
RASTER_MEANINGFUL_M2 = 2000.0


# ----------------------------------------------------------------------
# Frame conversion
# ----------------------------------------------------------------------
def to_local(latlngs, ref_lat=None, ref_lng=None):
    """
    Convert [(lat, lng), ...] to metres [(x_east, y_north), ...] about a
    reference (default: vertex mean). Returns (points, ref_lat, ref_lng).
    """
    if not latlngs:
        return [], ref_lat, ref_lng
    if ref_lat is None:
        ref_lat = sum(p[0] for p in latlngs) / len(latlngs)
        ref_lng = sum(p[1] for p in latlngs) / len(latlngs)
    m_lng = M_PER_DEG_LAT * math.cos(math.radians(ref_lat))
    pts = [((lng - ref_lng) * m_lng, (lat - ref_lat) * M_PER_DEG_LAT)
           for lat, lng in latlngs]
    return pts, ref_lat, ref_lng


# ----------------------------------------------------------------------
# Core polygon primitives (pure)
# ----------------------------------------------------------------------
def _closed(pts):
    """Vertex list without a duplicated closing vertex."""
    if len(pts) > 1 and pts[0] == pts[-1]:
        return pts[:-1]
    return list(pts)


def signed_area(pts):
    """Shoelace. Positive = counter-clockwise."""
    pts = _closed(pts)
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def area(pts):
    return abs(signed_area(pts))


def perimeter(pts):
    pts = _closed(pts)
    n = len(pts)
    if n < 2:
        return 0.0
    return sum(math.dist(pts[i], pts[(i + 1) % n]) for i in range(n))


def is_convex(pts):
    """True if the polygon is convex (collinear runs tolerated)."""
    pts = _closed(pts)
    n = len(pts)
    if n < 4:
        return True
    sign = 0
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cx, cy = pts[(i + 2) % n]
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(cross) < 1e-9:
            continue
        s = 1 if cross > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def self_intersects(pts):
    """True if any two non-adjacent edges cross. O(n^2); plots have few vertices."""
    pts = _closed(pts)
    n = len(pts)

    def seg(i):
        return pts[i], pts[(i + 1) % n]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def intersects(p1, p2, p3, p4):
        d1 = cross(p3, p4, p1)
        d2 = cross(p3, p4, p2)
        d3 = cross(p1, p2, p3)
        d4 = cross(p1, p2, p4)
        return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

    for i in range(n):
        for j in range(i + 1, n):
            # skip adjacent edges (they share a vertex by construction)
            if abs(i - j) in (0, 1) or (i == 0 and j == n - 1):
                continue
            a1, a2 = seg(i)
            b1, b2 = seg(j)
            if intersects(a1, a2, b1, b2):
                return True
    return False


def point_seg_dist(p, a, b):
    """Distance from point p to segment ab."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def polyline_min_dist(poly_pts, line_pts):
    """Minimum distance between a polygon boundary and a polyline."""
    poly = _closed(poly_pts)
    n = len(poly)
    best = float("inf")
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(len(line_pts) - 1):
            c, d = line_pts[j], line_pts[j + 1]
            best = min(best,
                       point_seg_dist(a, c, d), point_seg_dist(b, c, d),
                       point_seg_dist(c, a, b), point_seg_dist(d, a, b))
    if len(line_pts) == 1:   # point feature
        c = line_pts[0]
        for i in range(n):
            best = min(best, point_seg_dist(c, poly[i], poly[(i + 1) % n]))
    return best


# ----------------------------------------------------------------------
# Road frontage
# ----------------------------------------------------------------------
def _seg_bearing(a, b):
    return (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) + 360) % 360


def _axis_diff(b1, b2):
    """Smallest angle between two UNDIRECTED lines (0-90 degrees)."""
    d = abs(b1 - b2) % 180
    return min(d, 180 - d)


def edge_frontage(poly_pts, road_lines, touch_m=12.0, samples=9,
                  parallel_tol_deg=35.0):
    """
    For each polygon edge, the length of that edge lying within `touch_m` of
    any road centreline AND running roughly parallel to it.

    The parallel test is not cosmetic. Without it, on a 30x20 m plot beside a
    road, the two SIDE edges each have their near end within 12 m of that road
    and get counted — inflating total frontage from 30 m to 43 m. Frontage is
    the number a plot's price turns on, so overstating it is the worst error
    this module could make. An edge only counts as frontage if it lies along
    the road, not merely near it.

    Returns (per_edge, total_m):
        per_edge: list of dicts {edge, length_m, frontage_m, bearing_deg, road}
    """
    poly = _closed(poly_pts)
    n = len(poly)
    per_edge = []
    total = 0.0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        L = math.dist(a, b)
        if L == 0:
            continue
        brg = _seg_bearing(a, b)
        hits = 0
        best_road = None
        best_d = float("inf")
        for si in range(samples):
            t = (si + 0.5) / samples
            p = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            d_here, road_here = float("inf"), None
            for road in road_lines:
                coords = road.get("coords") or []
                for j in range(max(1, len(coords) - 1)):
                    c = tuple(coords[j])
                    d = tuple(coords[min(j + 1, len(coords) - 1)])
                    if c == d:
                        continue
                    # Only a road segment running ALONG this edge can front it.
                    if _axis_diff(brg, _seg_bearing(c, d)) > parallel_tol_deg:
                        continue
                    dd = point_seg_dist(p, c, d)
                    if dd < d_here:
                        d_here, road_here = dd, road
            if d_here <= touch_m:
                hits += 1
                if d_here < best_d:
                    best_d, best_road = d_here, road_here
        frontage = L * hits / samples
        per_edge.append({
            "edge": i,
            "length_m": round(L, 1),
            "frontage_m": round(frontage, 1),
            "bearing_deg": round(brg, 0),
            "road": (best_road.get("name") or best_road.get("subtype")) if best_road else None,
        })
        total += frontage
    return per_edge, round(total, 1)


def facing_direction(per_edge):
    """
    Which compass direction the plot 'faces' — the outward normal of the edge
    with the most road frontage. Indian buyers care about this (vaastu, sun).
    Returns (label, degrees) or (None, None) if no frontage.
    """
    best = max(per_edge, key=lambda e: e["frontage_m"], default=None)
    if not best or best["frontage_m"] <= 0:
        return None, None
    # Outward normal is edge bearing ± 90; without knowing winding, report the
    # edge orientation axis and let the caller resolve with the road side.
    normal = (best["bearing_deg"] + 90) % 360
    labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    lab = labels[int(((normal + 22.5) % 360) // 45)]
    return lab, normal


# ----------------------------------------------------------------------
# Setbacks (convex polygons only — honestly scoped)
# ----------------------------------------------------------------------
def inset_convex(pts, d):
    """
    Move every edge of a CONVEX polygon inward by d and re-intersect.
    Returns the inset polygon, or None if the setback consumes the plot.
    Non-convex plots must not call this — check is_convex first.
    """
    pts = _closed(pts)
    n = len(pts)
    if n < 3:
        return None
    ccw = signed_area(pts) > 0
    lines = []
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L == 0:
            continue
        # inward normal: left of direction for CCW winding, right for CW
        nx, ny = (-ey / L, ex / L) if ccw else (ey / L, -ex / L)
        lines.append(((ax + nx * d, ay + ny * d), (bx + nx * d, by + ny * d)))

    out = []
    m = len(lines)
    for i in range(m):
        (a1, a2) = lines[i]
        (b1, b2) = lines[(i + 1) % m]
        # line-line intersection
        x1, y1 = a1; x2, y2 = a2; x3, y3 = b1; x4, y4 = b2
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-9:
            continue
        px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / den
        py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / den
        out.append((px, py))

    if len(out) < 3 or area(out) < 1e-6:
        return None
    # If insetting flipped the winding, the setback ate the polygon.
    if (signed_area(out) > 0) != ccw:
        return None
    return out


def setback_report(pts, front_m=3.0, other_m=1.5):
    """
    Buildable-area estimate after a UNIFORM setback. Bengaluru (BBMP/BDA)
    setbacks vary by road width and plot size and differ per edge; modelling
    that needs the sanctioning authority's table, so this applies the FRONT
    setback uniformly — a conservative floor, stated as such in the note.
    Non-convex plots are declined rather than mis-computed.
    """
    pts = _closed(pts)
    if len(pts) < 3:
        return {"feasible": None, "note": "Not a polygon."}
    if not is_convex(pts):
        return {"feasible": None,
                "note": ("Irregular (non-convex) plot shape — setback feasibility "
                         "needs a proper survey drawing, not an estimate.")}
    inner = inset_convex(pts, front_m)
    if inner is None:
        return {"feasible": False, "buildable_m2": 0.0,
                "note": (f"A uniform {front_m:.1f} m setback consumes the entire "
                         f"plot — no buildable footprint remains. Verify the "
                         f"applicable setback table before purchase.")}
    a = area(inner)
    return {"feasible": True, "buildable_m2": round(a, 1),
            "buildable_pct": round(a / max(area(pts), 1e-9) * 100, 1),
            "note": (f"Applying a uniform {front_m:.1f} m setback on all sides "
                     f"(conservative floor; actual BBMP/BDA setbacks vary per "
                     f"edge with road width and plot size).")}


# ----------------------------------------------------------------------
# Top-level analysis
# ----------------------------------------------------------------------
@dataclass
class PlotGeometry:
    area_m2: float
    area_sqft: float
    area_guntas: float
    perimeter_m: float
    vertices: int
    convex: bool
    raster_stats_meaningful: bool     # area >= RASTER_MEANINGFUL_M2
    frontage_total_m: float
    frontage_edges: list
    facing: str | None
    setback: dict
    nearest: dict = field(default_factory=dict)   # kind -> {dist_m, name}
    warnings: list = field(default_factory=list)

    def scalars(self):
        d = asdict(self)
        d.pop("frontage_edges", None)
        return d


def analyse_polygon(local_pts, osm_features=None,
                    front_setback_m=3.0) -> PlotGeometry:
    """
    local_pts: [(x_east_m, y_north_m), ...] in the SAME frame as osm_features
    osm_features: list of objects/dicts with .kind/.subtype/.name/.coords
                  (plotlens.data.osm Feature, or plain dicts with those keys)
    """
    pts = _closed([tuple(p) for p in local_pts])
    warnings = []

    if len(pts) < 3:
        raise ValueError("A plot boundary needs at least 3 vertices.")
    if self_intersects(pts):
        raise ValueError("The drawn boundary crosses itself — redraw the plot.")

    A = area(pts)
    if A < 10:
        warnings.append("Boundary encloses under 10 m² — likely a mis-draw.")
    if A > 500 * SQM_PER_ACRE:
        warnings.append("Boundary encloses over 500 acres — likely a mis-draw.")

    feats = []
    for f in (osm_features or []):
        get = f.get if isinstance(f, dict) else lambda k, _f=f: getattr(_f, k, None)
        feats.append({"kind": get("kind"), "subtype": get("subtype"),
                      "name": get("name"), "coords": get("coords") or []})

    roads = [f for f in feats if f["kind"] == "road"]
    per_edge, total_frontage = edge_frontage(pts, roads)
    facing, _ = facing_direction(per_edge)
    if total_frontage == 0 and roads:
        warnings.append("No edge lies along a mapped road — access may be via "
                        "an unmapped path; verify on the ground.")

    nearest = {}
    for kind in ("road", "water", "poi"):
        best_d, best_name = float("inf"), None
        for f in feats:
            if f["kind"] != kind or not f["coords"]:
                continue
            d = polyline_min_dist(pts, [tuple(c) for c in f["coords"]])
            if d < best_d:
                best_d = d
                best_name = f["name"] or f["subtype"]
        if best_name is not None and best_d < float("inf"):
            nearest[kind] = {"dist_m": round(best_d, 1), "name": best_name}

    return PlotGeometry(
        area_m2=round(A, 1),
        area_sqft=round(A * SQFT_PER_M2, 0),
        area_guntas=round(A / SQM_PER_GUNTA, 2),
        perimeter_m=round(perimeter(pts), 1),
        vertices=len(pts),
        convex=is_convex(pts),
        raster_stats_meaningful=A >= RASTER_MEANINGFUL_M2,
        frontage_total_m=total_frontage,
        frontage_edges=per_edge,
        facing=facing,
        setback=setback_report(pts, front_m=front_setback_m),
        nearest=nearest,
        warnings=warnings,
    )
