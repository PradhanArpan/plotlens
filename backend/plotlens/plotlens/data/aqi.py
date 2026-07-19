"""
plotlens.data.aqi — air quality for the plot location.

Same provider pattern as dem.py / osm.py / imagery.py.

Design note — WHY STATION SELECTION IS NOT "NEAREST":
    OpenAQ's /latest endpoint returns each station's most recent reading
    whenever that happened to be. Probing Bengaluru on 2026-07-19, the nearest
    station (id 797, 2.7 km) last reported in FEBRUARY 2018, and measured no
    PM2.5 at all. Selecting by distance alone would therefore put eight-year-old
    figures — or none — into a report labelled as current air quality.

    So selection is: stations that measure PM2.5, ordered by distance, first one
    whose latest PM2.5 reading is fresher than MAX_AGE_HOURS. If none qualify we
    return no AQI and say why. An empty card is correct; a stale number is not.

SyntheticAQI runs anywhere. OpenAQProvider is the live deploy swap (needs a free
OpenAQ v3 key + network).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import datetime as dt
import math
import time


# CPCB AQI breakpoints for PM2.5 (24h, ug/m3).
# Boundaries are CONTINUOUS: the previous table used (0,30),(31,60),(61,90)...
# which left gaps, so an ordinary fractional reading like 30.4 matched no band
# and silently became "Unknown".
PM25_BANDS = [
    (0.0, 30.0, 0, 50, "Good"),
    (30.0, 60.0, 51, 100, "Satisfactory"),
    (60.0, 90.0, 101, 200, "Moderate"),
    (90.0, 120.0, 201, 300, "Poor"),
    (120.0, 250.0, 301, 400, "Very Poor"),
    (250.0, 500.0, 401, 500, "Severe"),
]


def pm25_to_aqi(c):
    """Convert a PM2.5 concentration (ug/m3) to CPCB AQI sub-index + band."""
    if c is None or c < 0:
        return None, "Unknown"
    for clo, chi, ilo, ihi, label in PM25_BANDS:
        if clo <= c <= chi:
            aqi = (ihi - ilo) / (chi - clo) * (c - clo) + ilo
            return round(aqi), label
    if c > 500:
        return 500, "Severe"
    return None, "Unknown"


def _status_for(aqi):
    """AQI band -> report card status."""
    if aqi is None:
        return "check"
    if aqi <= 100:
        return "good"
    if aqi <= 200:
        return "caution"
    return "flag"


@dataclass
class AQIResult:
    aqi: int | None              # CPCB AQI (None if no usable station)
    band: str                    # Good / Moderate / ... / Unknown
    pm25: float | None           # ug/m3
    station_name: str
    station_dist_km: float | None
    status: str                  # good | caution | flag | check
    reading: str
    source: str
    measured_at: str | None = None    # ISO timestamp of the reading used
    age_hours: float | None = None    # how old that reading is
    stations_checked: int = 0         # how many were probed before giving up

    def scalars(self):
        return {k: v for k, v in asdict(self).items()}


class AQIProvider:
    name = "abstract"

    def fetch(self, lat, lng) -> AQIResult:
        raise NotImplementedError


# ----------------------------------------------------------------------
# Synthetic — plausible AQI so the pipeline runs offline.
# ----------------------------------------------------------------------
class SyntheticAQI(AQIProvider):
    """
    NOTE: station names here are deliberately generic. An earlier version named
    real-sounding stations ("Whitefield AQ station", 3.1 km) which then appeared
    in reports for locations 25 km from Whitefield — invented detail specific
    enough that a user could act on it.
    """
    name = "synthetic"

    PROFILE = {"filled_pond": 72.0, "riverside": 38.0, "upland": 45.0}

    def __init__(self, archetype="filled_pond"):
        self.archetype = archetype

    def fetch(self, lat, lng) -> AQIResult:
        pm = self.PROFILE.get(self.archetype, 72.0)
        aqi, band = pm25_to_aqi(pm)
        return AQIResult(
            aqi=aqi, band=band, pm25=pm,
            station_name="Simulated station (not a real monitor)",
            station_dist_km=None,
            status=_status_for(aqi),
            reading=("Simulated air-quality figure for demonstration. "
                     "Not a measurement of this location."),
            source=f"synthetic:{self.archetype}")


# ----------------------------------------------------------------------
# Live — OpenAQ v3.
# ----------------------------------------------------------------------
class OpenAQProvider(AQIProvider):
    """
    Endpoints used (both verified against the live API on 2026-07-19):
        GET /v3/locations?coordinates=LAT,LNG&radius=..&parameters_id=2
        GET /v3/locations/{id}/latest

    Coordinate order is latitude,longitude. This matches the API reference; note
    that one of OpenAQ's own doc examples shows the reverse order, so it was
    confirmed empirically rather than taken from the docs.

    We do NOT use /sensors/{id}/measurements?limit=1 — its default sort order is
    unspecified, so "limit 1" could return the oldest measurement rather than the
    newest. /latest is unambiguous.
    """
    name = "openaq"
    BASE = "https://api.openaq.org/v3"
    PM25_PARAM_ID = 2

    def __init__(self, api_key: str, radius_m: int = 25000,
                 max_age_hours: float = 48.0, max_stations: int = 8,
                 timeout: int = 20):
        if not api_key:
            raise ValueError("OpenAQProvider requires an API key.")
        self.api_key = api_key
        # OpenAQ caps radius at 25 km and defaults to 1 km if omitted.
        self.radius_m = min(int(radius_m), 25000)
        self.max_age_hours = max_age_hours
        self.max_stations = max_stations
        self.timeout = timeout

    # -- helpers ------------------------------------------------------
    @staticmethod
    def _parse_utc(s):
        if not s:
            return None
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _latest_pm25(self, requests, loc):
        """Return (value, timestamp) of the freshest PM2.5 reading, or (None, None)."""
        loc_id = loc.get("id")
        sensor_param = {s.get("id"): (s.get("parameter") or {}).get("id")
                        for s in loc.get("sensors", [])}
        try:
            r = requests.get(f"{self.BASE}/locations/{loc_id}/latest",
                             params={"limit": 100},
                             headers={"X-API-Key": self.api_key},
                             timeout=self.timeout)
        except Exception:
            return None, None
        if r.status_code != 200:
            return None, None

        best_val, best_when = None, None
        for m in r.json().get("results", []):
            if sensor_param.get(m.get("sensorsId")) != self.PM25_PARAM_ID:
                continue
            when = self._parse_utc((m.get("datetime") or {}).get("utc"))
            if when and (best_when is None or when > best_when):
                best_when, best_val = when, m.get("value")
        return best_val, best_when

    # -- main ---------------------------------------------------------
    def fetch(self, lat, lng) -> AQIResult:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError("OpenAQProvider needs `requests` + network.") from e

        headers = {"X-API-Key": self.api_key}
        try:
            r = requests.get(
                f"{self.BASE}/locations",
                params={"coordinates": f"{lat:.4f},{lng:.4f}",
                        "radius": self.radius_m,
                        "parameters_id": self.PM25_PARAM_ID,
                        "limit": 100},
                headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise RuntimeError(f"OpenAQ request failed: {type(e).__name__}: {e}") from e

        if r.status_code != 200:
            raise RuntimeError(f"OpenAQ HTTP {r.status_code}: {r.text[:200]}")

        results = r.json().get("results", [])
        if not results:
            return AQIResult(
                None, "Unknown", None, "—", None, "check",
                f"No PM2.5 monitoring station within {self.radius_m/1000:.0f} km. "
                "This is missing coverage, not a clean-air reading.",
                "openaq")

        # Order candidates by real distance; the API does not guarantee this.
        scored = []
        for loc in results:
            c = loc.get("coordinates") or {}
            la, lo = c.get("latitude"), c.get("longitude")
            if la is None or lo is None:
                continue
            scored.append((_haversine_km(lat, lng, la, lo), loc))
        scored.sort(key=lambda x: x[0])

        now = dt.datetime.now(dt.timezone.utc)
        checked = 0
        stalest = None      # remember the best-but-too-old candidate, for the message

        for dist, loc in scored[:self.max_stations]:
            checked += 1
            pm, when = self._latest_pm25(requests, loc)
            if pm is None or when is None:
                continue
            age_h = (now - when).total_seconds() / 3600.0
            if age_h <= self.max_age_hours:
                aqi, band = pm25_to_aqi(pm)
                return AQIResult(
                    aqi=aqi, band=band, pm25=round(float(pm), 1),
                    station_name=loc.get("name", "Unknown station"),
                    station_dist_km=round(dist, 1),
                    status=_status_for(aqi),
                    reading=_reading(aqi, band, dist, age_h),
                    source="openaq",
                    measured_at=when.isoformat(),
                    age_hours=round(age_h, 1),
                    stations_checked=checked)
            if stalest is None or age_h < stalest[0]:
                stalest = (age_h, loc.get("name", "station"), dist)

        # Nothing fresh enough. Say so precisely rather than showing old numbers.
        if stalest:
            age_h, name, dist = stalest
            if age_h > 24 * 365:
                age_txt = f"{age_h/24/365:.1f} years old"
            elif age_h > 48:
                age_txt = f"{age_h/24:.0f} days old"
            else:
                age_txt = f"{age_h:.0f} hours old"
            msg = (f"Nearby monitoring stations exist, but the freshest PM2.5 "
                   f"reading found ({name}, {dist:.0f} km) is {age_txt}. "
                   "No current air-quality figure is shown, because a stale "
                   "reading presented as today's air would be misleading.")
        else:
            msg = (f"{checked} nearby station(s) listed PM2.5 but none returned "
                   "any reading. No current air-quality figure available.")

        return AQIResult(None, "Unknown", None,
                         stalest[1] if stalest else "—",
                         round(stalest[2], 1) if stalest else None,
                         "check", msg, "openaq", stations_checked=checked)


def _reading(aqi, band, dist, age_h=None):
    if aqi is None:
        return "No usable air-quality data near this plot."
    d = f" (nearest station ~{dist:.0f} km" if dist else ""
    if d and age_h is not None:
        d += f", measured {age_h:.0f} h ago)"
    elif d:
        d += ")"
    if aqi <= 100:
        return f"Air quality is {band.lower()} (AQI {aqi}){d} — generally fine for living."
    if aqi <= 200:
        return f"Air quality is {band.lower()} (AQI {aqi}){d} — sensitive groups should note this."
    return (f"Air quality is {band.lower()} (AQI {aqi}){d} — a real health "
            "consideration; check seasonal variation.")


def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class CachedAQI(AQIProvider):
    """
    In-memory TTL cache.

    The previous version was a pass-through that did nothing despite its name,
    so every report made a live OpenAQ call. Air quality changes hourly at most,
    and monitoring stations typically publish hourly, so a 30-minute TTL costs
    nothing in accuracy and removes most repeat calls.
    """

    def __init__(self, inner: AQIProvider, ttl_s: int = 1800):
        self.inner = inner
        self.ttl_s = ttl_s
        self.name = f"cached({inner.name})"
        self._store: dict[str, tuple[float, AQIResult]] = {}

    def fetch(self, lat, lng) -> AQIResult:
        # ~1 km granularity: air quality does not vary meaningfully below that,
        # and it keeps nearby taps on the same cache entry.
        key = f"{self.inner.name}|{lat:.2f}|{lng:.2f}"
        hit = self._store.get(key)
        if hit and (time.time() - hit[0]) < self.ttl_s:
            return hit[1]
        res = self.inner.fetch(lat, lng)
        self._store[key] = (time.time(), res)
        return res
