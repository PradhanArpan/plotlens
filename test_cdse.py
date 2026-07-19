"""
test_cdse.py -- verify Copernicus Data Space credentials and fetch a REAL
Sentinel-2 true-colour image of Bengaluru.

Setup:
  1. Create cdsekey.txt next to this script with EXACTLY two lines:
         line 1: your client_id
         line 2: your client_secret
     Nothing else. No labels, no quotes.
  2. Run:  python test_cdse.py

What it does:
  PART 1 - exchanges client_id/secret for an OAuth2 access token
  PART 2 - calls the Process API for a small bbox and saves a PNG you can open

Note on tokens: CDSE access tokens expire after about an hour. This script
gets a fresh one each run; the real provider will need caching with expiry.
"""
import base64
import datetime as dt
import json
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, "cdsekey.txt")

TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
             "/protocol/openid-connect/token")
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Small bbox over Whitefield, Bengaluru — same area as the elevation test.
# Order is min-lon, min-lat, max-lon, max-lat (WGS84).
BBOX = [77.740, 12.960, 77.760, 12.980]
OUT_PNG = os.path.join(HERE, "cdse_test.png")

# True colour. Bands B04/B03/B02 = red/green/blue, brightened by 2.5x because
# raw reflectance values are dark.
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: ["B02", "B03", "B04"],
    output: { bands: 3 }
  };
}
function evaluatePixel(s) {
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02];
}
"""


def load_credentials():
    if not os.path.exists(KEYFILE):
        sys.exit(f"No 'cdsekey.txt' found in {HERE}\n"
                 "Create it with client_id on line 1 and client_secret on line 2.")
    with open(KEYFILE, encoding="utf-8-sig") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if len(lines) < 2:
        sys.exit("cdsekey.txt needs TWO non-empty lines: client_id, then client_secret.")
    cid, secret = lines[0], lines[1]
    print(f"client_id     : {cid[:8]}...{cid[-4:]}  ({len(cid)} chars)")
    print(f"client_secret : {'*' * 8}...  ({len(secret)} chars)")
    return cid, secret


def get_token(cid, secret):
    print("\n" + "=" * 70)
    print("PART 1 - requesting OAuth2 access token")
    print("=" * 70)
    try:
        r = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials",
                  "client_id": cid,
                  "client_secret": secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=(6, 30))
    except requests.RequestException as e:
        sys.exit(f"NETWORK ERROR: {type(e).__name__}: {e}")

    print(f"HTTP status : {r.status_code}")
    if r.status_code != 200:
        print(f"Body        : {r.text[:400]}")
        print("\n401/400 usually means the client_id or client_secret is wrong,")
        print("or the OAuth client was created but not saved. Re-check both lines")
        print("of cdsekey.txt against the Sentinel Hub dashboard.")
        sys.exit(1)

    data = r.json()
    token = data.get("access_token")
    expires = data.get("expires_in")
    if not token:
        sys.exit(f"200 but no access_token in response: {json.dumps(data)[:300]}")
    print(f"token       : {token[:20]}... ({len(token)} chars)")
    print(f"expires_in  : {expires} seconds (~{expires/60:.0f} min)"
          if expires else "expires_in  : not reported")
    print("TOKEN OK")
    return token


def fetch_image(token):
    print("\n" + "=" * 70)
    print("PART 2 - Process API request for real Sentinel-2 imagery")
    print("=" * 70)

    # Look back 90 days; Sentinel-2 revisits every ~5 days but monsoon cloud
    # over Bengaluru in July means a short window may return nothing usable.
    today = dt.date.today()
    start = today - dt.timedelta(days=90)
    print(f"bbox        : {BBOX}")
    print(f"time range  : {start} to {today}")

    payload = {
        "input": {
            "bounds": {
                "bbox": BBOX,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": f"{start}T00:00:00Z",
                        "to": f"{today}T23:59:59Z",
                    },
                    # Prefer the least cloudy scene in the window.
                    "maxCloudCoverage": 40,
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {
            "width": 512,
            "height": 512,
            "responses": [{"identifier": "default",
                           "format": {"type": "image/png"}}],
        },
        "evalscript": EVALSCRIPT,
    }

    try:
        r = requests.post(PROCESS_URL, json=payload, timeout=(6, 90),
                          headers={"Authorization": f"Bearer {token}"})
    except requests.RequestException as e:
        sys.exit(f"NETWORK ERROR: {type(e).__name__}: {e}")

    print(f"HTTP status : {r.status_code}")
    print(f"Content-type: {r.headers.get('content-type')}")
    print(f"Bytes       : {len(r.content):,}")

    if r.status_code != 200:
        print("\n--- FAILED. Server said: ---")
        print(r.text[:600])
        if r.status_code == 403:
            print("\n403 often means the account lacks Sentinel Hub access, or the")
            print("processing-unit quota is exhausted. Check the dashboard.")
        return False

    if not r.content.startswith(b"\x89PNG"):
        print("\n200 but the body is not a PNG:")
        print(r.content[:300])
        return False

    with open(OUT_PNG, "wb") as f:
        f.write(r.content)
    print(f"Saved       : {OUT_PNG}")
    print("\nREAL SENTINEL-2 IMAGERY DOWNLOADED.")
    print("Open the PNG. You should see Whitefield from above at ~10 m per pixel:")
    print("roads, tanks and built-up blocks should be recognisable; individual")
    print("plots will NOT be, because a 30x40 ft plot is about one pixel.")
    print("\nIf the image is mostly white, that is monsoon cloud, not a bug —")
    print("try raising maxCloudCoverage or widening the time range.")
    return True


def main():
    cid, secret = load_credentials()
    token = get_token(cid, secret)
    fetch_image(token)


if __name__ == "__main__":
    main()
