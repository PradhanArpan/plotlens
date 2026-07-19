"""
plotlens.data.aqi — air quality for the plot location.

Same provider pattern as dem.py / osm.py / imagery.py. The honest output is the
nearest monitoring station's recent PM2.5/PM10 turned into an AQI band — or a
clear "no nearby station" when coverage is absent (OpenAQ coverage is uneven;
empty != clean air).

SyntheticAQI runs anywhere. OpenAQProvider is the live deploy swap (needs a free
OpenAQ v3 key + network).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math


# CPCB-style AQI bands for PM2.5 (24h, ug/m3). Simplified to the sub-index that
# usually dominates in Indian cities. Good enough for a buyer-facing indicator.
PM25_BANDS = [
    (0, 30, 0, 50, "Good"),
    (31, 60, 51, 100, "Satisfactory"),
    (61, 90, 101, 200, "Moderate"),
    (91, 120, 201, 300, "Poor"),
    (121, 250, 301, 400, "Very Poor"),
    (251, 500, 401, 500, "Severe"),
]


def pm25_to_aqi(c):
    """Convert a PM2.5 concentration (ug/m3) to CPCB AQI sub-index + band."""
    for clo, chi, ilo, ihi, label in PM25_BANDS:
        if clo <= c <= chi:
            aqi = (ihi - ilo) / (chi - clo) * (c - clo) + ilo
            return round(aqi), label
    if c > 250:
        return 500, "Severe"
    return None, "Unknown"


# AQI band -> our good/caution/flag status for the report card
def _status_for(aqi):
    if aqi is None:
        return "check"
    if aqi <= 100:
        return "good"
    if aqi <= 200:
        return "caution"
    return "flag"


@dataclass
class AQIResult:
    aqi: int | None              # CPCB AQI (None if no station)
    band: str                    # Good / Moderate / ... / Unknown
    pm25: float | None           # ug/m3
    station_name: str
    station_dist_km: float | None
    status: str                  # good | caution | flag | check
    reading: str
    source: str

    def scalars(self):
        return {k: v for k, v in asdict(self).items()}


class AQIProvider:
    name = "abstract"
    def fetch(self, lat, lng) -> AQIResult:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Synthetic — plausible AQI per region so the pipeline runs offline.
# ----------------------------------------------------------------------
class SyntheticAQI(AQIProvider):
    name = "synthetic"

    # rough PM2.5 by archetype/region (ug/m3). Bengaluru urban worse than rural.
    PROFILE = {"filled_pond": (72, "Whitefield AQ station", 3.1),
               "riverside": (38, "Mandya AQ station", 11.4),
               "upland": (45, "Tumkur AQ station", 6.0)}

    def __init__(self, archetype="filled_pond"):
        self.archetype = archetype

    def fetch(self, lat, lng) -> AQIResult:
        pm, name, dist = self.PROFILE.get(self.archetype, self.PROFILE["filled_pond"])
        aqi, band = pm25_to_aqi(pm)
        status = _status_for(aqi)
        return AQIResult(
            aqi=aqi, band=band, pm25=pm, station_name=name, station_dist_km=dist,
            status=status, reading=_reading(aqi, band, dist), source=f"synthetic:{self.archetype}")


# ----------------------------------------------------------------------
# Live — OpenAQ v3. Deploy swap. Needs network + a free X-API-Key.
# ----------------------------------------------------------------------
class OpenAQProvider(AQIProvider):
    name = "openaq"
    BASE = "https://api.openaq.org/v3"

    def __init__(self, api_key: str, radius_m: int = 25000):
        self.api_key = api_key
        self.radius_m = radius_m

    def fetch(self, lat, lng) -> AQIResult:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("OpenAQProvider needs `requests` + network.") from e
        headers = {"X-API-Key": self.api_key}
        # 1) find nearest location measuring PM2.5 (parameters_id=2)
        r = requests.get(f"{self.BASE}/locations",
                         params={"coordinates": f"{lat},{lng}", "radius": self.radius_m,
                                 "parameters_id": 2, "limit": 1},
                         headers=headers, timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return AQIResult(None, "Unknown", None, "—", None, "check",
                             "No air-quality monitoring station within 25 km. "
                             "This is missing coverage, not a clean-air reading.",
                             "openaq")
        loc = results[0]
        name = loc.get("name", "Unknown station")
        # distance from returned coords
        coords = loc.get("coordinates", {})
        dist = _haversine_km(lat, lng, coords.get("latitude"), coords.get("longitude")) \
            if coords.get("latitude") else None
        # 2) latest PM2.5 value for that location
        sensors = [s for s in loc.get("sensors", []) if s.get("parameter", {}).get("id") == 2]
        pm = None
        if sensors:
            sid = sensors[0]["id"]
            lr = requests.get(f"{self.BASE}/sensors/{sid}/measurements",
                              params={"limit": 1}, headers=headers, timeout=20)
            if lr.ok:
                vals = lr.json().get("results", [])
                if vals:
                    pm = vals[0].get("value")
        if pm is None:
            return AQIResult(None, "Unknown", None, name, round(dist, 1) if dist else None,
                             "check", "Nearest station has no recent PM2.5 reading.", "openaq")
        aqi, band = pm25_to_aqi(pm)
        return AQIResult(aqi, band, round(pm, 1), name, round(dist, 1) if dist else None,
                         _status_for(aqi), _reading(aqi, band, dist), "openaq")


def _reading(aqi, band, dist):
    if aqi is None:
        return "No usable air-quality data near this plot."
    d = f" (nearest station ~{dist:.0f} km)" if dist else ""
    if aqi <= 100:
        return f"Air quality is {band.lower()} (AQI {aqi}){d} — generally fine for living."
    if aqi <= 200:
        return f"Air quality is {band.lower()} (AQI {aqi}){d} — sensitive groups should note this."
    return f"Air quality is {band.lower()} (AQI {aqi}){d} — a real health consideration; check seasonal variation."


def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class CachedAQI(AQIProvider):
    """AQI changes hourly, so cache briefly. For dev, just pass through."""
    def __init__(self, inner: AQIProvider):
        self.inner = inner
        self.name = f"cached({inner.name})"

    def fetch(self, lat, lng) -> AQIResult:
        return self.inner.fetch(lat, lng)
