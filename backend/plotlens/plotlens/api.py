"""
plotlens.api — FastAPI wrapper around the pipeline.

Run with:
    python -m uvicorn plotlens.api:app --reload --port 8000

This version:
- enables CORS so the Vite frontend (localhost:5173/5174) can call it,
- returns the FULL 8-category report (paywall deferred) in the exact shape
  the frontend's FULL mock used, so the UI renders real engine data.
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

from plotlens.pipeline import run_report

MODE = os.environ.get("PLOTLENS_MODE", "synthetic")
OUT_DIR = os.environ.get("PLOTLENS_OUT", "out")

JOBS: dict[str, dict] = {}
_lock = threading.Lock()

# tints for the then/now slider, per archetype (frontend uses these)
TINTS = {
    "filled_pond": {"then": "#3f6b3a", "now": "#7d7a6b",
                    "then_cover": "Open scrub & a seasonal pond", "now_cover": "Partly built-up, road access added"},
    "riverside":   {"then": "#2f5d6b", "now": "#8a8160",
                    "then_cover": "Floodplain near river channel", "now_cover": "Cleared, levelled, plotted"},
    "upland":      {"then": "#5a5340", "now": "#6b6147",
                    "then_cover": "Rocky upland, sparse trees", "now_cover": "Same upland, access track added"},
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


def _full_report(result) -> dict:
    """Shape the engine output into the frontend's report format (all 8 categories)."""
    t = result["terrain"]; a = result["access"]; im = result["imagery"]
    arch = result.get("archetype", "filled_pond")
    tint = TINTS.get(arch, TINTS["filled_pond"])

    veg_status = im["change_status"] if im["change_status"] != "flag" else "caution"

    cats = [
        {"title": "Topography & Geology", "icon": "Mountain", "source": "derived", "status": t["water_status"],
         "rows": [["Elevation", f'{t["plot_mean_elev"]} m'], ["Slope", f'{t["mean_slope_pct"]} %'],
                  ["Below surroundings", f'{t["rel_to_surroundings"]} m'], ["Landslide potential", "Low"]]},
        {"title": "Water & Drainage", "icon": "Droplets", "source": "derived", "status": t["water_status"],
         "rows": [["Water-collection index", f'{t["flow_ratio"]}x area average'],
                  ["Nearest water", f'{a["nearest_water_m"]:.0f} m ({a["nearest_water_name"]})'],
                  ["Drainage bearing", f'{t["drainage_bearing"]:.0f}°'], ["Reading", t["reading"]]]},
        {"title": "Climate & Natural", "icon": "CloudRain", "source": "derived", "status": "good",
         "rows": [["Sun path", "E–W, standard for latitude"],
                  ["Note", "Rainfall, wind & seismic added from datasets on live deploy"]]},
        {"title": "Circulation & Access", "icon": "Route", "source": "derived", "status": a["access_status"],
         "rows": [["Nearest road", f'{a["nearest_road_m"]:.0f} m ({a["nearest_road_name"]})'],
                  ["Transit", f'{a["nearest_transit_m"]:.0f} m'],
                  ["Emergency", f'{a["nearest_emergency_m"]:.0f} m ({a["emergency_kind"]})'],
                  ["Reading", a["reading"]]]},
        {"title": "Vegetation & Landscaping", "icon": "Trees", "source": "derived", "status": veg_status,
         "rows": [["Vegetation cover", f'{im["veg_then_pct"]}% → {im["veg_now_pct"]}%'],
                  ["Trend", "From Sentinel-2 NDVI differencing"]]},
        _aqi_category(result.get("aqi")),
        {"title": "Land-cover change", "icon": "ArrowRightLeft", "source": "derived", "status": im["change_status"],
         "rows": [["Water cover", f'{im["water_then_pct"]}% → {im["water_now_pct"]}%'], ["Reading", im["reading"]]]},
        {"title": "Utilities & Infrastructure", "icon": "Plug", "source": "partial", "status": "caution",
         "rows": [["Adjacent land use", a["adjacent_landuse"]],
                  ["Mapped utilities", "From OSM; underground lines not mapped"]]},
        {"title": "Development Rules & Legal", "icon": "FileText", "source": "offline", "status": "check",
         "rows": [["Title & ownership", "Cannot be checked from satellite"],
                  ["Zoning / land-use", "Cannot be checked from satellite"],
                  ["Easements & setbacks", "Cannot be checked from satellite"]],
         "offline_note": "Satellite data can't see legal status. Verify with the sub-registrar, a property "
                         "lawyer, and the planning authority — this is the costliest place buyers get caught."},
    ]
    return {
        "overall": _overall(result),
        "then": {"year": 2017, "cover": tint["then_cover"], "tint": tint["then"]},
        "now": {"year": 2025, "cover": tint["now_cover"], "tint": tint["now"]},
        "categories": cats,
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
        return {"ok": True, "mode": MODE}
