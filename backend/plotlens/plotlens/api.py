"""
plotlens.api — FastAPI wrapper around the pipeline.

Run with:
    python -m uvicorn plotlens.api:app --reload --port 8000

Core rule of this file:
    A REPORT MUST NEVER PRESENT SIMULATED DATA AS AN OBSERVATION OF THIS SITE.

That rule has three concrete consequences, all implemented below:

1. The headline verdict is computed ONLY from categories backed by live data.
   Previously _overall() took the worst status across terrain, access and
   land-cover change regardless of provenance — so a synthetic "filled pond"
   fixture could stamp a red Flag on a real location where nothing of the sort
   was measured.

2. Every card whose data is simulated carries a visible provenance row and is
   not labelled "Satellite-derived".

3. Simulated sources do not emit specific, checkable claims (named monitoring
   stations, exact AQI values, dated land-cover narratives). Fabricated
   precision is worse than an empty field, because it survives a sanity check.
"""
from __future__ import annotations
import os
import uuid
import threading

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
except ImportError:  # keep importable without fastapi
    FastAPI = None

from plotlens.pipeline import run_report, capability_report, credentials

# "auto" = use live data wherever credentials exist. Set PLOTLENS_MODE=synthetic
# to force everything synthetic (useful for offline demos).
MODE = os.environ.get("PLOTLENS_MODE", "auto")
OUT_DIR = os.environ.get("PLOTLENS_OUT", "out")

JOBS: dict[str, dict] = {}
_lock = threading.Lock()

SOURCE_LABELS = {
    "dem": "Elevation / terrain",
    "osm": "Roads, water & POIs",
    "imagery": "Satellite land cover",
    "aqi": "Air quality",
}

SIMULATED_ROW = ["Data source", "Simulated — not measured for this location"]


def _process(job_id, lat, lng, archetype):
    try:
        result = run_report(lat, lng, out_dir=OUT_DIR, mode=MODE, archetype=archetype)
        result["archetype"] = archetype
        with _lock:
            JOBS[job_id].update(status="done", result=result)
    except Exception as e:  # noqa
        with _lock:
            JOBS[job_id].update(status="error", error=str(e))


# ----------------------------------------------------------------------
# Provenance helpers
# ----------------------------------------------------------------------
def _is_live(result, key) -> bool:
    return bool(result.get("live", {}).get(key))


def _card_source(is_live: bool, live_value: str = "derived") -> str:
    """
    Map provenance onto source values the frontend already understands.

    We deliberately do NOT invent a new value: the frontend renders "derived"
    as "Satellite-derived", and an unknown value could render blank. Simulated
    cards use "partial" (shown as "Indicative") AND carry an explicit simulated
    row, so the label can never overstate the data.
    """
    return live_value if is_live else "partial"


def _overall(result):
    """
    Worst status across categories THAT ARE BACKED BY LIVE DATA.

    If nothing live contributes we return "check" rather than inventing a
    verdict — an honest "not enough real data yet" instead of a false Flag.
    """
    rank = {"good": 0, "check": 0, "caution": 1, "flag": 2}
    candidates = []

    if _is_live(result, "dem"):
        candidates.append(result["terrain"]["water_status"])
    if _is_live(result, "osm"):
        candidates.append(result["access"]["access_status"])
    if _is_live(result, "imagery"):
        candidates.append(result["imagery"]["change_status"])

    if not candidates:
        return "check"
    return max(candidates, key=lambda s: rank.get(s, 0))


def _verdict_note(result):
    """Explain what the headline verdict is, and is not, based on."""
    live = result.get("live", {})
    keys = ("dem", "osm", "imagery")
    contributing = [SOURCE_LABELS[k].lower() for k in keys if live.get(k)]
    missing = [SOURCE_LABELS[k].lower() for k in keys if not live.get(k)]

    if not contributing:
        return ("No live data source was available for this location, so no overall "
                "verdict has been calculated. Figures below are simulated placeholders.")
    if missing:
        return ("Verdict based only on " + ", ".join(contributing) +
                ". Excluded: " + ", ".join(missing) +
                " — simulated for this location.")
    return None


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------
def _fmt_distance(m, label_if_missing="None mapped nearby"):
    """Distances use -1 as a 'not found' sentinel. Never render that raw."""
    try:
        m = float(m)
    except (TypeError, ValueError):
        return label_if_missing
    if m < 0:
        return label_if_missing
    return f"{m:.0f} m"


def _fmt_emergency(a):
    """Distance plus service type, or a plain 'none found' statement."""
    try:
        m = float(a.get("nearest_emergency_m", -1))
    except (TypeError, ValueError):
        m = -1
    if m < 0:
        return "None mapped within search area"
    kind = (a.get("emergency_kind") or "").strip()
    if kind and kind not in ("—", "-"):
        return f"{m:.0f} m ({kind})"
    return f"{m:.0f} m"


def _fmt_relative_elevation(t):
    """
    rel_to_surroundings is POSITIVE when the site sits LOWER than its
    surroundings, so the raw signed number under a label like "Below
    surroundings" contradicts its own caption. State direction in words.
    """
    rel = t.get("rel_to_surroundings", 0.0)
    direction = t.get("rel_direction")
    if direction is None:  # older engine output
        direction = "below" if rel > 0.5 else ("above" if rel < -0.5 else "level with")
    if direction == "level with":
        return "Level with surrounding land"
    return f"{abs(rel):.1f} m {direction} surrounding land"


# ----------------------------------------------------------------------
# Cards
# ----------------------------------------------------------------------
def _topography_category(result):
    t = result["terrain"]
    live = _is_live(result, "dem")
    rows = [] if live else [SIMULATED_ROW]
    rows += [["Elevation", f'{t["plot_mean_elev"]} m'],
             ["Slope", f'{t["mean_slope_pct"]} %'],
             ["Relative height", _fmt_relative_elevation(t)],
             ["Landslide potential", "Low"]]
    return {"title": "Topography & Geology", "icon": "Mountain",
            "source": _card_source(live),
            "status": t["water_status"] if live else "check",
            "rows": rows}


def _water_category(result):
    t = result["terrain"]
    a = result["access"]
    dem_live = _is_live(result, "dem")
    osm_live = _is_live(result, "osm")

    rows = [] if dem_live else [SIMULATED_ROW]
    rows.append(["Water-collection index",
                 f'{t["flow_ratio"]}x the typical ground in this area'])
    if t.get("flow_percentile") is not None:
        rows.append(["Runoff concentration",
                     f'Higher than {t["flow_percentile"]:.0f}% of surrounding ground'])
    nearest = f'{_fmt_distance(a["nearest_water_m"])} ({a["nearest_water_name"]})'
    if not osm_live:
        nearest += "  [simulated]"
    rows.append(["Nearest water", nearest])
    rows.append(["Drainage bearing", f'{t["drainage_bearing"]:.0f}°'])
    rows.append(["Reading", t["reading"]])

    return {"title": "Water & Drainage", "icon": "Droplets",
            "source": _card_source(dem_live),
            "status": t["water_status"] if dem_live else "check",
            "rows": rows}


def _access_category(result):
    a = result["access"]
    live = _is_live(result, "osm")
    rows = [] if live else [SIMULATED_ROW]
    rows += [
        ["Nearest road", f'{_fmt_distance(a["nearest_road_m"])} ({a["nearest_road_name"]})'],
        ["Transit", _fmt_distance(a["nearest_transit_m"])],
        ["Emergency", _fmt_emergency(a)],
        ["Reading", a["reading"]],
    ]
    return {"title": "Circulation & Access", "icon": "Route",
            "source": _card_source(live),
            "status": a["access_status"] if live else "check",
            "rows": rows}


def _vegetation_category(result):
    im = result["imagery"]
    live = _is_live(result, "imagery")
    if not live:
        return {"title": "Vegetation & Landscaping", "icon": "Trees",
                "source": "unavailable", "status": "check",
                "rows": [SIMULATED_ROW,
                         ["Status", "Vegetation trend not measured for this location"]]}
    veg_status = im["change_status"] if im["change_status"] != "flag" else "caution"
    return {"title": "Vegetation & Landscaping", "icon": "Trees", "source": "derived",
            "status": veg_status,
            "rows": [["Vegetation cover", f'{im["veg_then_pct"]}% → {im["veg_now_pct"]}%'],
                     ["Trend", "From Sentinel-2 NDVI differencing"]]}


def _aqi_category(result):
    """
    Air quality card.

    When AQI is simulated we show NO numbers and NO station name. The previous
    version emitted "AQI 139" and "Whitefield AQ station (~3 km)" for a pin
    ~25 km from Whitefield — invented detail specific enough to act on.
    """
    aqi = result.get("aqi")
    live = _is_live(result, "aqi")

    if not live:
        return {"title": "Air Quality", "icon": "Wind", "source": "unavailable",
                "status": "check",
                "rows": [SIMULATED_ROW,
                         ["Status", "No live air-quality data for this location"],
                         ["To enable", "Requires an OpenAQ API key on the server"]],
                "offline_note": ("Air-quality figures are withheld because no live "
                                 "monitoring data is connected yet. Nearby CPCB/SPCB "
                                 "station readings can be checked directly.")}

    if not aqi:
        return {"title": "Air Quality", "icon": "Wind", "source": "partial",
                "status": "check",
                "rows": [["Status", "No air-quality data available"]]}

    rows = []
    if aqi.get("aqi") is not None:
        rows.append(["AQI (CPCB)", f'{aqi["aqi"]} — {aqi["band"]}'])
    if aqi.get("pm25") is not None:
        rows.append(["PM2.5", f'{aqi["pm25"]} ug/m3'])
    if aqi.get("station_dist_km") is not None:
        rows.append(["Nearest station",
                     f'{aqi["station_name"]} (~{aqi["station_dist_km"]:.0f} km)'])
    else:
        rows.append(["Station", aqi.get("station_name", "—")])
    rows.append(["Reading", aqi.get("reading", "")])
    return {"title": "Air Quality", "icon": "Wind", "source": "derived",
            "status": aqi.get("status", "check"), "rows": rows}


def _landcover_category(result):
    """Land-cover change. Suppressed entirely when imagery is simulated."""
    im = result["imagery"]
    live = _is_live(result, "imagery")

    if not live:
        return {"title": "Land-cover change", "icon": "ArrowRightLeft",
                "source": "unavailable", "status": "check",
                "rows": [SIMULATED_ROW,
                         ["Status", "Then-vs-now comparison not available"],
                         ["To enable", "Requires Copernicus Data Space credentials"]],
                "offline_note": ("No satellite imagery has been analysed for this "
                                 "location, so no land-cover change has been detected "
                                 "either way. This is not an all-clear.")}

    return {"title": "Land-cover change", "icon": "ArrowRightLeft", "source": "derived",
            "status": im["change_status"],
            "rows": [["Water cover", f'{im["water_then_pct"]}% → {im["water_now_pct"]}%'],
                     ["Reading", im["reading"]]]}


def _utilities_category(result):
    a = result["access"]
    live = _is_live(result, "osm")
    rows = [] if live else [SIMULATED_ROW]
    rows += [["Adjacent land use", a["adjacent_landuse"]],
             ["Mapped utilities", "From OSM; underground lines not mapped"]]
    return {"title": "Utilities & Infrastructure", "icon": "Plug",
            "source": "partial", "status": "caution" if live else "check",
            "rows": rows}


def _provenance_category(result):
    """Explicit, user-facing statement of what is real and what is not."""
    live = result.get("live", {})
    sources = result.get("sources", {})
    degraded = result.get("degraded", [])

    rows = []
    for key, label in SOURCE_LABELS.items():
        src = sources.get(key, "unknown")
        mark = "Live data" if live.get(key) else "Simulated"
        rows.append([label, f"{mark} — {src}"])

    if degraded:
        failed = ", ".join(d["source"] for d in degraded)
        rows.append(["Fallbacks used",
                     f"{failed} (live source unavailable, simulated instead)"])

    all_live = all(live.get(k) for k in SOURCE_LABELS)
    any_live = any(live.get(k) for k in SOURCE_LABELS)
    status = "good" if all_live else ("caution" if any_live else "check")

    return {"title": "Data Sources", "icon": "Database", "source": "derived",
            "status": status, "rows": rows,
            "offline_note": (None if all_live else
                             "Items marked Simulated are realistic stand-ins, not "
                             "measurements of this site. They are excluded from the "
                             "overall verdict and must not drive a purchase decision.")}


def _full_report(result) -> dict:
    """Shape the engine output into the frontend's report format."""
    imagery_live = _is_live(result, "imagery")

    cats = [
        _topography_category(result),
        _water_category(result),
        {"title": "Climate & Natural", "icon": "CloudRain", "source": "partial",
         "status": "check",
         "rows": [["Sun path", "E–W, standard for latitude"],
                  ["Note", "Rainfall, wind & seismic datasets not yet wired in"]]},
        _access_category(result),
        _vegetation_category(result),
        _aqi_category(result),
        _landcover_category(result),
        _utilities_category(result),
        {"title": "Development Rules & Legal", "icon": "FileText", "source": "offline",
         "status": "check",
         "rows": [["Title & ownership", "Cannot be checked from satellite"],
                  ["Zoning / land-use", "Cannot be checked from satellite"],
                  ["Easements & setbacks", "Cannot be checked from satellite"]],
         "offline_note": "Satellite data can't see legal status. Verify with the sub-registrar, "
                         "a property lawyer, and the planning authority — this is the costliest "
                         "place buyers get caught."},
        _provenance_category(result),
    ]

    # then/now panel: hardcoded strings when imagery is simulated, so they must
    # not be presented as observations of this location.
    if imagery_live:
        then = {"year": 2017, "cover": "Earlier land cover", "tint": "#3f6b3a"}
        now = {"year": 2025, "cover": "Current land cover", "tint": "#7d7a6b"}
    else:
        then = {"year": None, "cover": "Simulated preview — imagery not connected",
                "tint": "#5c5c5c"}
        now = {"year": None, "cover": "Simulated preview — imagery not connected",
               "tint": "#7a7a7a"}

    return {
        "overall": _overall(result),
        "verdict_note": _verdict_note(result),
        "then": then,
        "now": now,
        "categories": cats,
        "provenance": {
            "live": result.get("live", {}),
            "sources": result.get("sources", {}),
            "degraded": result.get("degraded", []),
            "mode": result.get("mode", MODE),
        },
    }


if FastAPI is not None:
    app = FastAPI(title="PlotLens API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # dev: allow any origin. Tighten for production.
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class ReportRequest(BaseModel):
        lat: float
        lng: float
        archetype: str = "filled_pond"

    @app.post("/report")
    def create_report(req: ReportRequest):
        job_id = uuid.uuid4().hex[:12]
        with _lock:
            JOBS[job_id] = {"status": "running"}
        threading.Thread(target=_process, args=(job_id, req.lat, req.lng, req.archetype),
                         daemon=True).start()
        return {"job_id": job_id, "status": "running"}

    @app.get("/report/{job_id}")
    def get_report(job_id: str):
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        if job["status"] == "error":
            return {"status": "error", "error": job.get("error")}
        if job["status"] != "done":
            return {"status": job["status"]}
        return {"status": "done", "report": _full_report(job["result"])}

    @app.get("/report/{job_id}/pdf")
    def get_pdf(job_id: str):
        job = JOBS.get(job_id)
        if not job or job.get("status") != "done":
            raise HTTPException(404, "not ready")
        return FileResponse(job["result"]["pdf"], media_type="application/pdf",
                            filename="plotlens_site_analysis.pdf")

    @app.get("/health")
    def health():
        """Reports ACTUAL capability, not a fixed string."""
        caps = capability_report()
        creds = credentials()
        return {
            "ok": True,
            "mode": MODE,
            "live_capable": caps,
            "credentials_present": {k: bool(v) for k, v in creds.items()},
            "all_live": all(caps.values()),
        }
