"""
plotlens.pipeline — orchestrates one report end to end.

    coordinate --> DEM provider (cached) --> engine --> renderer --> result

This is exactly the worker job the API would enqueue. Runs fully here on the
synthetic provider; in production you pass SRTMProvider instead (one line in
build_provider) and nothing else changes.
"""
from __future__ import annotations
import time
from pathlib import Path

from plotlens.data.dem import SyntheticDEM, SRTMProvider, CachedDEM
from plotlens.data.osm import SyntheticOSM, OverpassProvider, CachedOSM
from plotlens.data.imagery import SyntheticImagery, Sentinel2Provider, CachedImagery
from plotlens.data.aqi import SyntheticAQI, OpenAQProvider, CachedAQI
from plotlens.engine.terrain import analyse as analyse_terrain
from plotlens.engine.access import analyse as analyse_access
from plotlens.render.artifact import render as render_terrain
from plotlens.render.rings import render as render_rings
from plotlens.render.change import render as render_change
from plotlens.render.dossier import build as build_dossier

SPAN_M = 3600     # ~3.6 km analysis window
RES_M = 30        # Copernicus GLO-30 native resolution


def build_provider(mode: str = "synthetic", archetype: str = "filled_pond",
                   srtm_key: str | None = None):
    """The ONE place that decides DEM source. Swap mode='srtm' to go live."""
    if mode == "srtm":
        if not srtm_key:
            raise ValueError("srtm mode needs an OpenTopography API key")
        inner = SRTMProvider(api_key=srtm_key)
    else:
        inner = SyntheticDEM(archetype=archetype)
    return CachedDEM(inner, cache_dir="cache")


def build_osm_provider(mode: str = "synthetic", archetype: str = "filled_pond"):
    """OSM source. Swap mode='overpass' to go live."""
    inner = OverpassProvider() if mode == "overpass" else SyntheticOSM(archetype=archetype)
    return CachedOSM(inner, cache_dir="cache")


def build_imagery_provider(mode: str = "synthetic", archetype: str = "filled_pond",
                           imagery_key: str | None = None):
    """Imagery source. Swap mode='sentinel2' to go live."""
    if mode == "sentinel2":
        if not imagery_key:
            raise ValueError("sentinel2 mode needs an imagery API key")
        inner = Sentinel2Provider(api_key=imagery_key)
    else:
        inner = SyntheticImagery(archetype=archetype)
    return CachedImagery(inner, cache_dir="cache")


def build_aqi_provider(mode: str = "synthetic", archetype: str = "filled_pond",
                       openaq_key: str | None = None):
    """AQI source. Swap mode='openaq' to go live."""
    if mode == "openaq":
        if not openaq_key:
            raise ValueError("openaq mode needs an OpenAQ API key")
        inner = OpenAQProvider(api_key=openaq_key)
    else:
        inner = SyntheticAQI(archetype=archetype)
    return CachedAQI(inner)


def run_report(lat: float, lng: float, out_dir: str = "out",
               mode: str = "synthetic", archetype: str = "filled_pond") -> dict:
    t0 = time.time()
    live = mode == "srtm"
    dem_provider = build_provider(mode=mode, archetype=archetype)
    osm_provider = build_osm_provider(mode="overpass" if live else "synthetic", archetype=archetype)
    img_provider = build_imagery_provider(mode="sentinel2" if live else "synthetic", archetype=archetype)
    aqi_provider = build_aqi_provider(mode="openaq" if live else "synthetic", archetype=archetype)

    # --- terrain ---
    tile = dem_provider.fetch(lat, lng, SPAN_M, RES_M)
    terrain = analyse_terrain(tile)
    # --- access (OSM) ---
    osm = osm_provider.fetch(lat, lng, SPAN_M)
    access = analyse_access(osm)
    # --- imagery change ---
    imagery = img_provider.fetch(lat, lng, SPAN_M)
    # --- air quality ---
    aqi = aqi_provider.fetch(lat, lng)

    # --- render all three artifacts ---
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    img_terrain = f"{out_dir}/terrain_{lat:.4f}_{lng:.4f}.png"
    img_rings = f"{out_dir}/rings_{lat:.4f}_{lng:.4f}.png"
    img_change = f"{out_dir}/change_{lat:.4f}_{lng:.4f}.png"
    render_terrain(tile, terrain, img_terrain)
    render_rings(osm, access, img_rings)
    render_change(imagery, img_change)

    result = {
        "coords": {"lat": lat, "lng": lng},
        "sources": {"dem": tile.source, "osm": osm.source, "imagery": imagery.source, "aqi": aqi.source},
        "terrain": terrain.scalars(),
        "access": access.scalars(),
        "imagery": imagery.scalars(),
        "aqi": aqi.scalars(),
        "artifacts": {"terrain": img_terrain, "rings": img_rings, "change": img_change},
        "total_ms": round((time.time() - t0) * 1000, 1),
    }
    pdf = f"{out_dir}/dossier_{lat:.4f}_{lng:.4f}.pdf"
    build_dossier(result, pdf)
    result["pdf"] = pdf
    result["total_ms"] = round((time.time() - t0) * 1000, 1)
    return result


if __name__ == "__main__":
    import json
    coords = {"filled_pond": (12.9698, 77.7499),
              "riverside": (12.5223, 76.8951),
              "upland": (13.1986, 77.4066)}
    for arch, (lat, lng) in coords.items():
        r = run_report(lat, lng, archetype=arch)
        print(f"=== {arch} ===")
        print("sources:", r["sources"])
        print("terrain:", json.dumps(r["terrain"], default=str)[:200])
        print("access :", json.dumps(r["access"], default=str)[:200])
        print("imagery:", json.dumps(r["imagery"], default=str)[:240])
        print("artifacts:", list(r["artifacts"].values()), f"({r['total_ms']} ms)\n")
