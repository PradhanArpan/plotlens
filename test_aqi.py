"""
test_aqi.py -- two tests in one:

  PART 1: survey nearby OpenAQ stations and show how OLD their PM2.5 data is.
  PART 2: run PlotLens's OWN OpenAQProvider against the live API.

Reads the key from aqkey.txt in the same folder. Nothing to paste, nothing to
set as an environment variable.

Run from the project root:   python test_aqi.py
"""
import datetime as dt
import math
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

HERE = os.path.dirname(os.path.abspath(__file__))
# Let this script import the plotlens package for PART 2.
sys.path.insert(0, os.path.join(HERE, "backend", "plotlens"))

BASE = "https://api.openaq.org/v3"
LAT, LNG = 12.9716, 77.5946     # Bengaluru city centre
RADIUS_M = 25000
PM25_PARAM_ID = 2
MAX_STATIONS = 12


def load_key():
    path = os.path.join(HERE, "aqkey.txt")
    if not os.path.exists(path):
        sys.exit(f"No 'aqkey.txt' found in {HERE}")
    with open(path, encoding="utf-8-sig") as f:
        key = re.sub(r"\s+", "", f.read().strip().strip('"').strip("'"))
    if not key:
        sys.exit("aqkey.txt is empty.")
    print(f"Key loaded: {key[:6]}...{key[-4:]} ({len(key)} chars)\n")
    return key


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_utc(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def part1_survey(key):
    print("=" * 78)
    print("PART 1 - how fresh is PM2.5 data around Bengaluru?")
    print("=" * 78)
    hdr = {"X-API-Key": key}
    now = dt.datetime.now(dt.timezone.utc)

    r = requests.get(f"{BASE}/locations", headers=hdr, timeout=(6, 30),
                     params={"coordinates": f"{LAT},{LNG}", "radius": RADIUS_M,
                             "parameters_id": PM25_PARAM_ID, "limit": 100})
    if r.status_code != 200:
        print(f"HTTP {r.status_code}: {r.text[:200]}")
        return 0
    locs = r.json().get("results", [])
    print(f"{len(locs)} PM2.5-capable stations within {RADIUS_M//1000} km\n")

    scored = []
    for loc in locs:
        c = loc.get("coordinates") or {}
        if c.get("latitude") is None:
            continue
        scored.append((haversine_km(LAT, LNG, c["latitude"], c["longitude"]), loc))
    scored.sort(key=lambda x: x[0])

    print(f"{'dist':>7}  {'id':<9} {'PM2.5 reading age':<26} {'value':>8}  name")
    print("-" * 92)

    fresh = 0
    for dist, loc in scored[:MAX_STATIONS]:
        sensor_param = {s.get("id"): (s.get("parameter") or {}).get("id")
                        for s in loc.get("sensors", [])}
        try:
            lr = requests.get(f"{BASE}/locations/{loc['id']}/latest", headers=hdr,
                              params={"limit": 100}, timeout=(6, 30))
        except requests.RequestException as e:
            print(f"{dist:6.1f}k  {loc['id']:<9} {type(e).__name__:<26} {'':>8}  {loc.get('name')}")
            continue
        if lr.status_code != 200:
            print(f"{dist:6.1f}k  {loc['id']:<9} {'HTTP '+str(lr.status_code):<26} {'':>8}  {loc.get('name')}")
            continue

        val, when = None, None
        for mm in lr.json().get("results", []):
            if sensor_param.get(mm.get("sensorsId")) != PM25_PARAM_ID:
                continue
            t = parse_utc((mm.get("datetime") or {}).get("utc"))
            if t and (when is None or t > when):
                when, val = t, mm.get("value")

        if when is None:
            age, vtxt = "no PM2.5 in latest", ""
        else:
            h = (now - when).total_seconds() / 3600
            vtxt = str(val)
            if h < 48:
                age = f"{h:.1f} h ago  [FRESH]"
                fresh += 1
            elif h < 24 * 30:
                age = f"{h/24:.1f} days ago"
            else:
                age = f"{h/24/365:.1f} YEARS ago  [STALE]"
        print(f"{dist:6.1f}k  {loc['id']:<9} {age:<26} {vtxt:>8}  {loc.get('name')}")

    print("-" * 92)
    print(f"\n{fresh} of {min(MAX_STATIONS, len(scored))} checked stations "
          "have PM2.5 fresher than 48 hours.\n")
    return fresh


def part2_provider(key):
    print("=" * 78)
    print("PART 2 - PlotLens's own OpenAQProvider, live")
    print("=" * 78)
    try:
        from plotlens.data.aqi import OpenAQProvider
    except ImportError as e:
        print(f"Could not import plotlens.data.aqi: {e}")
        return
    try:
        res = OpenAQProvider(key).fetch(LAT, LNG)
    except Exception as e:
        print(f"Provider raised: {type(e).__name__}: {e}")
        return

    for k, v in res.scalars().items():
        print(f"  {k:<18}: {v}")

    print()
    if res.aqi is not None:
        print(">>> LIVE AQI IS VIABLE. Set OPENAQ_API_KEY in Render.")
    else:
        print(">>> No usable current reading. The provider declined to show a")
        print(">>> number rather than present stale data as today's air.")
        print(">>> If this persists, leave the Air Quality card disconnected.")


def main():
    key = load_key()
    part1_survey(key)
    part2_provider(key)


if __name__ == "__main__":
    main()
