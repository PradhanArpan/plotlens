"""
plotlens.pipeline — orchestrates one report end to end.

    coordinate --> DEM provider (cached) --> engine --> renderer --> result

Live vs synthetic is decided PER SOURCE, not globally. Each data source goes
live only if its credentials are actually present in the environment, so you
can switch sources on one at a time as you obtain keys.

Credentials read from environment variables (never hardcoded):
    OPENTOPOGRAPHY_API_KEY   -> real elevation (COP30)
    OPENAQ_API_KEY           -> real air quality
    CDSE_CLIENT_ID           -> real satellite imagery (with the secret below)
    CDSE_CLIENT_SECRET
    (OpenStreetMap/Overpass needs no key — it goes live whenever mode allows.)

Honesty rule:
    If a live provider is configured but fails at request time, the pipeline
    falls back to synthetic rather than returning a 500 — BUT it records that
    downgrade in result["sources"] and result["degraded"]. A report must never
    silently present synthetic data as if it were real.
"""
from __future__ import annotations
import os
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


# ----------------------------------------------------------------------
# Credentials
# ----------------------------------------------------------------------
def _env(name: str) -> str | None:
    """Read an env var, treating blank/whitespace as absent."""
    val = os.environ.get(name, "")
    val = val.strip()
    return val or None


def credentials() -> dict:
    """Everything the pipeline knows about available credentials."""
    return {
        "opentopography": _env("OPENTOPOGRAPHY_API_KEY"),
        "openaq": _env("OPENAQ_API_KEY"),
        "cdse_id": _env("CDSE_CLIENT_ID"),
        "cdse_secret": _env("CDSE_CLIENT_SECRET"),
    }


def capability_report() -> dict:
    """
    Which sources CAN run live right now. Useful for a health endpoint and for
    seeing at a glance what a deployment is actually capable of.
    """
    c = credentials()
    return {
        "dem": bool(c["opentopography"]),
        "osm": True,  # keyless
        "imagery": bool(c["cdse_id"] and c["cdse_secret"]),
        "aqi": bool(c["openaq"]),
    }


# ----------------------------------------------------------------------
# Provider builders — each returns (provider, is_live)
# ----------------------------------------------------------------------
def build_provider(mode: str = "synthetic", archetype: str = "filled_pond",
                   srtm_key: str | None = None):
    """
    The ONE place that decides DEM source.

    mode: "synthetic" | "srtm" | "auto"
      auto -> live if OPENTOPOGRAPHY_API_KEY exists, else synthetic.
    """
    key = srtm_key or credentials()["opentopography"]
    want_live = mode == "srtm" or (mode == "auto" and key)
    if want_live:
        if not key:
            raise ValueError(
                "DEM live mode requested but OPENTOPOGRAPHY_API_KEY is not set."
            )
        return CachedDEM(SRTMProvider(api_key=key), cache_dir="cache"), True
    return CachedDEM(SyntheticDEM(archetype=archetype), cache_dir="cache"), False


def build_osm_provider(mode: str = "synthetic", archetype: str = "filled_pond"):
    """OSM source. Keyless, so 'auto' always means live."""
    want_live = mode in ("overpass", "auto")
    if want_live:
        return CachedOSM(OverpassProvider(), cache_dir="cache"), True
    return CachedOSM(SyntheticOSM(archetype=archetype), cache_dir="cache"), False


def build_imagery_provider(mode: str = "synthetic", archetype: str = "filled_pond",
                           imagery_key: str | None = None):
    """
    Imagery source.

    NOTE: Copernicus Data Space uses OAuth2 (client id + secret), not a single
    API key. Sentinel2Provider's constructor has never been run against the
    real service. Verify its signature when CDSE credentials are first added.
    """
    c = credentials()
    key = imagery_key or c["cdse_id"]
    secret = c["cdse_secret"]
    want_live = mode == "sentinel2" or (mode == "auto" and key and secret)
    if want_live:
        if not (key and secret):
            raise ValueError(
                "Imagery live mode requested but CDSE_CLIENT_ID / "
                "CDSE_CLIENT_SECRET are not both set."
            )
        return CachedImagery(Sentinel2Provider(api_key=key), cache_dir="cache"), True
    return CachedImagery(SyntheticImagery(archetype=archetype), cache_dir="cache"), False


def build_aqi_provider(mode: str = "synthetic", archetype: str = "filled_pond",
                       openaq_key: str | None = None):
    """AQI source."""
    key = openaq_key or credentials()["openaq"]
    want_live = mode == "openaq" or (mode == "auto" and key)
    if want_live:
        if not key:
            raise ValueError(
                "AQI live mode requested but OPENAQ_API_KEY is not set."
            )
        return CachedAQI(OpenAQProvider(api_key=key)), True
    return CachedAQI(SyntheticAQI(archetype=archetype)), False


# ----------------------------------------------------------------------
# Fetch with honest fallback
# ----------------------------------------------------------------------
def _fetch_or_fallback(label, live_provider, is_live, fetch, fallback_builder,
                       degraded: list):
    """
    Try the configured provider. If it is live and fails, fall back to the
    synthetic equivalent and RECORD the downgrade. Never silently pretend.
    """
    try:
        return fetch(live_provider)
    except Exception as e:
        if not is_live:
            raise  # synthetic failing is a real bug, do not mask it
        degraded.append({"source": label, "error": f"{type(e).__name__}: {e}"})
        provider, _ = fallback_builder()
        return fetch(provider)


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
def run_report(lat: float, lng: float, out_dir: str = "out",
               mode: str = "auto", archetype: str = "filled_pond") -> dict:
    """
    mode:
      "auto"      -> each source goes live if its credentials exist (default)
      "synthetic" -> force everything synthetic
      "srtm"      -> legacy alias, treated as "auto"
      "live"      -> same as auto
    """
    t0 = time.time()
    if mode in ("srtm", "live"):
        mode = "auto"

    per_source = "auto" if mode == "auto" else "synthetic"
    degraded: list = []

    dem_provider, dem_live = build_provider(
        mode=per_source, archetype=archetype)
    osm_provider, osm_live = build_osm_provider(
        mode=per_source, archetype=archetype)
    img_provider, img_live = build_imagery_provider(
        mode=per_source, archetype=archetype)
    aqi_provider, aqi_live = build_aqi_provider(
        mode=per_source, archetype=archetype)

    # --- terrain ---
    tile = _fetch_or_fallback(
        "dem", dem_provider, dem_live,
        lambda p: p.fetch(lat, lng, SPAN_M, RES_M),
        lambda: build_provider(mode="synthetic", archetype=archetype),
        degraded)
    terrain = analyse_terrain(tile)

    # --- access (OSM) ---
    osm = _fetch_or_fallback(
        "osm", osm_provider, osm_live,
        lambda p: p.fetch(lat, lng, SPAN_M),
        lambda: build_osm_provider(mode="synthetic", archetype=archetype),
        degraded)
    access = analyse_access(osm)

    # --- imagery change ---
    imagery = _fetch_or_fallback(
        "imagery", img_provider, img_live,
        lambda p: p.fetch(lat, lng, SPAN_M),
        lambda: build_imagery_provider(mode="synthetic", archetype=archetype),
        degraded)

    # --- air quality ---
    aqi = _fetch_or_fallback(
        "aqi", aqi_provider, aqi_live,
        lambda p: p.fetch(lat, lng),
        lambda: build_aqi_provider(mode="synthetic", archetype=archetype),
        degraded)

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
        "mode": mode,
        "sources": {
            "dem": tile.source,
            "osm": osm.source,
            "imagery": imagery.source,
            "aqi": aqi.source,
        },
        # True only where the returned data is genuinely from a live API.
        "live": {
            "dem": dem_live and not any(d["source"] == "dem" for d in degraded),
            "osm": osm_live and not any(d["source"] == "osm" for d in degraded),
            "imagery": img_live and not any(d["source"] == "imagery" for d in degraded),
            "aqi": aqi_live and not any(d["source"] == "aqi" for d in degraded),
        },
        "degraded": degraded,
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
    print("Capabilities (which sources can run live here):")
    print(json.dumps(capability_report(), indent=2))
    print()

    coords = {"filled_pond": (12.9698, 77.7499),
              "riverside": (12.5223, 76.8951),
              "upland": (13.1986, 77.4066)}
    for arch, (lat, lng) in coords.items():
        r = run_report(lat, lng, archetype=arch)
        print(f"=== {arch} ===")
        print("live   :", r["live"])
        if r["degraded"]:
            print("DEGRADED:", r["degraded"])
        print("sources:", r["sources"])
        print("terrain:", json.dumps(r["terrain"], default=str)[:200])
        print("access :", json.dumps(r["access"], default=str)[:200])
        print("imagery:", json.dumps(r["imagery"], default=str)[:240])
        print("artifacts:", list(r["artifacts"].values()), f"({r['total_ms']} ms)\n")
