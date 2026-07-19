"""
plotlens.api — FastAPI wrapper around the pipeline.

Run with:
    python -m uvicorn plotlens.api:app --reload --port 8000

This version:
- enables CORS so the Vite frontend (localhost:5173/5174) can call it,
- returns the FULL report in the shape the frontend expects,
- defaults to mode="auto": each data source goes LIVE if its credentials are
  present in the environment, and falls back to synthetic if not. The previous
  default was "synthetic", which silently overrode the pipeline and made real
  API keys have no effect at all.
- surfaces PROVENANCE: every response says which sources were real and which
  were synthetic, and /health reports actual capability instead of a fixed
  string.
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
# to force everything synthetic (useful for demos with no network).
MODE = os.environ.get("PLOTLENS_MODE", "auto")
OUT_DIR = os.environ.get("PLOTLENS_OUT", "out")

JOBS: dict[str, dict] = {}
_lock = threading.Lock()

# Tints and cover descriptions for the then/now slider.
# NOTE: these strings are HARDCODED per archetype, not observed from imagery.
# They are honest only while imagery is synthetic anyway. When real Sentinel-2
# imagery is wired in, these must be replaced with derived descriptions or
# dropped — do not present them as observations of the actual site.
TINTS = {
    "filled_pond": {"then": "#3f6b3a", "now": "#7d7a6b",
                    "then_cover": "Open scrub & a seasonal pond",
                    "now_cover": "Partly built-up, road access added"},
    "riverside":   {"then": "#2f5d6b", "now": "#8a8160",
                    "then_cover": "Floodplain near river channel",
                    "now_cover": "Cleared, levelled, plotted"},
    "upland":      {"then": "#5a5340", "now": "#6b6147",
                    "then_cover": "Rocky upland, sparse trees",
                    "now_cover": "Same upland, access track added"},
}

SOURCE_LABELS = {
    "dem": "Elevation / terrain",
    "osm": "Roads, water & POIs",
    "imagery": "Satellite land cover",
    "aqi": "Air quality",
}


def _process(job_id, lat, lng, archetype):
    try:
        result = run_report(lat, lng, out_dir=OUT_DIR, mode=MODE, archetype=archetype)
        result["archetype"] = archetype
        with _lock:
            JOBS[job_id].update(status="done", result=result)
    except Exception as e:  # noqa
        with _lock:
            JOBS[job_id].update(status="error", error=str(e))


def _overall(result):
    rank = {"good": 0, "caution": 1, "flag": 2, "check": 0}
    statuses = [result["terrain"]["water_status"],
                result["access"]["access_status"],
                result["imagery"]["change_status"]]
    return max(statuses, key=lambda s: rank.get(s, 0))


def _fmt_distance(m, label_if_missing="None mapped nearby"):
    """Distances use -1 as a 'not found' sentinel. Never render that raw."""
    try:
        m = float(m)
    except (TypeError, ValueError):
        return label_if_missing
    if m < 0:
        return label_if_missing
    return f"{m:.0f} m"


def _fmt_relative_elevation(t):
    """
    rel_to_surroundings is POSITIVE when the site sits LOWER than its
    surroundings. Printing the raw signed number under a label like "Below
    surroundings" shows the user a value that contradicts its own caption.
    """
    rel = t.get("rel_to_surroundings", 0.0)
    direction = t.get("rel_direction")
    if direction is None:  # older engine output
        direction = "below" if rel > 0.5 else ("above" if rel < -0.5 else "level with")
    if direction == "level with":
        return "Level with surrounding land"
    return f"{abs(rel):.1f} m {direction} surrounding land"


def _fmt_emergency(a):
    """
    Emergency services: distance plus what kind, or a plain statement that
    nothing was found. The engine uses -1 to mean 'not found'; rendering that
    as '-1 m' is worse than saying nothing.
    """
    try:
        m = float(a.get("nearest_emergency_m", -1))
    except (TypeError, ValueError):
        m = -1
    if m < 0:
        return "None mapped within search area"
    kind = a.get("emergency_kind") or ""
    kind = kind.strip()
    if kind and kind not in ("—", "-"):
        return f"{m:.0f} m ({kind})"
    return f"{m:.0f} m"


def _aqi_category(aqi):
    """Build the Air Quality card from the engine's aqi block."""
    if not aqi:
        return {"title": "Air Quality", "icon": "Wind", "source": "partial", "status": "check",
                "rows": [["Status", "No air-quality data available"]]}
    rows = []
    if aqi.get("aqi") is not None:
        rows.append(["AQI (CPCB)", f'{aqi["aqi"]} — {aqi["band"]}'])
    if aqi.get("pm25") is not None:
        rows.append(["PM2.5", f'{aqi["pm25"]} ug/m3'])
    if aqi.get("station_dist_km") is not None:
        rows.append(["Nearest station", f'{aqi["station_name"]} (~{aqi["station_dist_km"]:.0f} km)'])
    else:
        rows.append(["Station", aqi.get("station_name", "—")])
    rows.append(["Reading", aqi.get("reading", "")])
    return {"title": "Air Quality", "icon": "Wind", "source": "derived",
            "status": aqi.get("status", "check"), "rows": rows}


def _provenance_category(result):
    """
    Explicit, user-facing statement of what is real and what is not.

    This is the card that keeps the product honest: a buyer can see at a glance
    whether the elevation figure came from a satellite DEM or from a plausible
    stand-in.
    """
    live = result.get("live", {})
    sources = result.get("sources", {})
    degraded = result.get("degraded", [])

    rows = []
    for key, label in SOURCE_LABELS.items():
        src = sources.get(key, "unknown")
        is_live = bool(live.get(key))
        mark = "Live data" if is_live else "Simulated"
        rows.append([label, f"{mark} — {src}"])

    if degraded:
        failed = ", ".join(d["source"] for d in degraded)
        rows.append(["Fallbacks used", f"{failed} (live source unavailable, simulated instead)"])

    all_live = all(live.get(k) for k in SOURCE_LABELS)
    any_live = any(live.get(k) for k in SOURCE_LABELS)
    status = "good" if all_live else ("caution" if any_live else "check")

    return {"title": "Data Sources", "icon": "Database", "source": "derived",
            "status": status, "rows": rows,
            "offline_note": ("Items marked Simulated are realistic stand-ins, not "
                             "measurements of this site. Do not rely on them for "
                             "a purchase decision.") if not all_live else None}


def _full_report(result) -> dict:
    """Shape the engine output into the frontend's report format."""
    t = result["terrain"]; a = result["access"]; im = result["imagery"]
    arch = result.get("archetype", "filled_pond")
    tint = TINTS.get(arch, TINTS["filled_pond"])
    live = result.get("live", {})

    veg_status = im["change_status"] if im["change_status"] != "flag" else "caution"

    flow_rows = [["Water-collection index",
                  f'{t["flow_ratio"]}x the typical ground in this area']]
    if t.get("flow_percentile") is not None:
        flow_rows.append(["Runoff concentration",
                          f'Higher than {t["flow_percentile"]:.0f}% of surrounding ground'])
    flow_rows += [
        ["Nearest water", f'{_fmt_distance(a["nearest_water_m"])} ({a["nearest_water_name"]})'],
        ["Drainage bearing", f'{t["drainage_bearing"]:.0f}°'],
        ["Reading", t["reading"]],
    ]

    cats = [
        {"title": "Topography & Geology", "icon": "Mountain", "source": "derived",
         "status": t["water_status"],
         "rows": [["Elevation", f'{t["plot_mean_elev"]} m'],
                  ["Slope", f'{t["mean_slope_pct"]} %'],
                  ["Relative height", _fmt_relative_elevation(t)],
                  ["Landslide potential", "Low"]]},
        {"title": "Water & Drainage", "icon": "Droplets", "source": "derived",
         "status": t["water_status"], "rows": flow_rows},
        {"title": "Climate & Natural", "icon": "CloudRain", "source": "derived", "status": "good",
         "rows": [["Sun path", "E–W, standard for latitude"],
                  ["Note", "Rainfall, wind & seismic added from datasets on live deploy"]]},
        {"title": "Circulation & Access", "icon": "Route", "source": "derived",
         "status": a["access_status"],
         "rows": [["Nearest road", f'{_fmt_distance(a["nearest_road_m"])} ({a["nearest_road_name"]})'],
                  ["Transit", _fmt_distance(a["nearest_transit_m"], "None mapped nearby")],
                  ["Emergency", _fmt_emergency(a)],
                  ["Reading", a["reading"]]]},
        {"title": "Vegetation & Landscaping", "icon": "Trees", "source": "derived",
         "status": veg_status,
         "rows": [["Vegetation cover", f'{im["veg_then_pct"]}% → {im["veg_now_pct"]}%'],
                  ["Trend", "From Sentinel-2 NDVI differencing"
                            if live.get("imagery") else
                            "Simulated — not measured from imagery"]]},
        _aqi_category(result.get("aqi")),
        {"title": "Land-cover change", "icon": "ArrowRightLeft", "source": "derived",
         "status": im["change_status"],
         "rows": [["Water cover", f'{im["water_then_pct"]}% → {im["water_now_pct"]}%'],
                  ["Reading", im["reading"]]]},
        {"title": "Utilities & Infrastructure", "icon": "Plug", "source": "partial",
         "status": "caution",
         "rows": [["Adjacent land use", a["adjacent_landuse"]],
                  ["Mapped utilities", "From OSM; underground lines not mapped"]]},
        {"title": "Development Rules & Legal", "icon": "FileText", "source": "offline",
         "status": "check",
         "rows": [["Title & ownership", "Cannot be checked from satellite"],
                  ["Zoning / land-use", "Cannot be checked from satellite"],
                  ["Easements & setbacks", "Cannot be checked from satellite"]],
         "offline_note": "Satellite data can't see legal status. Verify with the sub-registrar, a property "
                         "lawyer, and the planning authority — this is the costliest place buyers get caught."},
        _provenance_category(result),
    ]
    return {
        "overall": _overall(result),
        "then": {"year": 2017, "cover": tint["then_cover"], "tint": tint["then"]},
        "now": {"year": 2025, "cover": tint["now_cover"], "tint": tint["now"]},
        "categories": cats,
        # Machine-readable provenance for the frontend to badge the UI.
        "provenance": {
            "live": live,
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
        """
        Reports ACTUAL capability, not a fixed string. The previous version
        returned a hardcoded mode that stayed 'synthetic' even when real
        credentials were configured, which hid a live-mode misconfiguration.
        """
        caps = capability_report()
        creds = credentials()
        return {
            "ok": True,
            "mode": MODE,
            "live_capable": caps,
            "credentials_present": {k: bool(v) for k, v in creds.items()},
            "all_live": all(caps.values()),
        }
