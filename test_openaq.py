"""
test_openaq.py -- verify an OpenAQ v3 API key works, and find out which
coordinate order the API actually wants.

Setup:
  1. Create aqkey.txt next to this script.
  2. Paste ONLY your OpenAQ API key into it. Nothing else. Save.
  3. Run:  python test_openaq.py

Why it tries both coordinate orders:
  The OpenAQ API reference says `coordinates` is "latitude,longitude"
  (e.g. 38.9074,-77.0373), but one of their own examples passes
  136.90610,35.14942 and calls it latitude,longitude -- those are Nagoya's
  coordinates the other way round. Rather than guess, we send both and see
  which one returns stations that are actually near Bengaluru.
"""
import math
import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

BASE = "https://api.openaq.org/v3"
KEYFILE = "aqkey.txt"

# Bengaluru city centre. Dense monitoring, so a real key should find stations.
LAT, LNG = 12.9716, 77.5946
RADIUS_M = 25000          # API maximum. Default is only 1000 m if omitted.


def load_key():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, KEYFILE)
    if not os.path.exists(path):
        sys.exit(f"No '{KEYFILE}' found in {here}\n"
                 f"Create it and paste ONLY your OpenAQ API key inside.")
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read()
    key = raw.strip().strip('"').strip("'")
    if ":" in key:
        key = key.split(":")[-1].strip()
    key = re.sub(r"\s+", "", key)
    if not key:
        sys.exit(f"'{KEYFILE}' is empty.")
    print(f"Key loaded  : {key[:6]}...{key[-4:]}  ({len(key)} chars)")
    return key


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def try_locations(key, coord_str, label):
    """Query /v3/locations with a given coordinate string."""
    print(f"\n--- {label}: coordinates={coord_str} ---")
    try:
        r = requests.get(
            f"{BASE}/locations",
            params={"coordinates": coord_str, "radius": RADIUS_M, "limit": 100},
            headers={"X-API-Key": key},
            timeout=(6, 30),
        )
    except requests.RequestException as e:
        print(f"  NETWORK ERROR: {type(e).__name__}: {e}")
        return None

    print(f"  HTTP status : {r.status_code}")
    if r.status_code == 401:
        print("  401 = key rejected. Check aqkey.txt contains only the key.")
        return None
    if r.status_code == 422:
        print(f"  422 = unprocessable. Body: {r.text[:200]}")
        return None
    if r.status_code != 200:
        print(f"  Body: {r.text[:250]}")
        return None

    try:
        data = r.json()
    except ValueError:
        print("  200 but body was not JSON.")
        return None

    results = data.get("results", [])
    found = data.get("meta", {}).get("found")
    print(f"  meta.found  : {found}")
    print(f"  results     : {len(results)}")
    if not results:
        print("  No stations returned for this coordinate order.")
        return None

    # Measure how far the returned stations really are from our point.
    scored = []
    for loc in results:
        c = loc.get("coordinates") or {}
        la, lo = c.get("latitude"), c.get("longitude")
        if la is None or lo is None:
            continue
        scored.append((haversine_km(LAT, LNG, la, lo), loc))
    scored.sort(key=lambda x: x[0])

    if not scored:
        print("  Stations returned but none had coordinates.")
        return None

    print(f"  Nearest 5 stations to Bengaluru ({LAT}, {LNG}):")
    for dist, loc in scored[:5]:
        params = ", ".join(
            sorted({(s.get("parameter") or {}).get("name", "?")
                    for s in loc.get("sensors", [])}))
        print(f"    {dist:7.1f} km  id={loc.get('id'):<7} {loc.get('name')}"
              f"  [{params}]")

    nearest_km = scored[0][0]
    if nearest_km > 100:
        print(f"  WARNING: nearest station is {nearest_km:.0f} km away — this "
              "coordinate order is probably wrong.")
        return None
    return scored[0][1]


def show_latest(key, loc):
    """Fetch the latest measurements for one location."""
    loc_id = loc.get("id")
    print(f"\n--- latest measurements for location {loc_id} ({loc.get('name')}) ---")
    try:
        r = requests.get(f"{BASE}/locations/{loc_id}/latest",
                         headers={"X-API-Key": key},
                         params={"limit": 100},
                         timeout=(6, 30))
    except requests.RequestException as e:
        print(f"  NETWORK ERROR: {type(e).__name__}: {e}")
        return

    print(f"  HTTP status : {r.status_code}")
    if r.status_code != 200:
        print(f"  Body: {r.text[:250]}")
        return

    results = r.json().get("results", [])
    if not results:
        print("  Station exists but reported no recent measurements.")
        print("  (Not a key problem — some stations go quiet.)")
        return

    # Map sensor ids to parameter names using the location record.
    sensor_names = {s.get("id"): (s.get("parameter") or {}).get("name", "?")
                    for s in loc.get("sensors", [])}
    for m in results[:10]:
        sid = m.get("sensorsId")
        name = sensor_names.get(sid, f"sensor {sid}")
        value = m.get("value")
        when = (m.get("datetime") or {}).get("utc", "?")
        print(f"    {name:<8} {value:>10}   at {when}")


def main():
    key = load_key()

    # The API reference says latitude,longitude. Try that first.
    loc = try_locations(key, f"{LAT},{LNG}", "Order A (latitude,longitude)")
    order = "latitude,longitude"

    if loc is None:
        loc = try_locations(key, f"{LNG},{LAT}", "Order B (longitude,latitude)")
        order = "longitude,latitude"

    if loc is None:
        print("\nNeither coordinate order returned usable nearby stations.")
        print("If both showed HTTP 200 with 0 results, the key works but no")
        print("station data was found — try a different city to confirm.")
        return

    print(f"\n>>> WORKING COORDINATE ORDER: {order}")
    print(">>> Use this in plotlens/data/aqi.py")
    show_latest(key, loc)


if __name__ == "__main__":
    main()
