"""
probe_imagery_years.py -- work out WHY vegetation appears to increase between
2017 and 2026 at sites that have visibly urbanised.

Method: sample the SAME location, in the SAME calendar window (Jan-Mar), for
every year from 2017 to now. Land cover changes gradually, so a well-behaved
series should drift smoothly. Anything else is an artefact, and the shape of
the series tells us which artefact:

  * A STEP around 2022        -> Sentinel-2 processing baseline 04.00, which
                                 introduced a radiometric offset in Jan 2022.
                                 Composites either side are not comparable
                                 unless harmonised.
  * 2017 uniquely LOW         -> real conditions. Karnataka's 2016-17 drought
                                 would depress vegetation, making 2017 a poor
                                 baseline even though the number is correct.
  * 2017 low COVERAGE / noise -> thin early archive. Sentinel-2B only launched
                                 in March 2017, so early 2017 has one satellite
                                 and a sparser composite.
  * Smooth drift              -> the trend is real and the earlier reading of
                                 "urbanisation should mean less vegetation" was
                                 simply wrong for this site.

It also reports mean band reflectance, because the baseline offset shows up
there directly even when NDVI hides it (NDVI is a ratio and partly cancels it).

Run from the project root:  python probe_imagery_years.py
Reads cdsekey.txt. Costs roughly one Process API call per year.
"""
import datetime as dt
import os
import re
import sys
from io import BytesIO

try:
    import requests
    import numpy as np
    import tifffile
except ImportError as e:
    sys.exit(f"Missing package: {e.name}. Run:  pip install requests numpy tifffile")

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE"
             "/protocol/openid-connect/token")
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Whitefield, Bengaluru — the site that showed 43% -> 38% vegetation.
LAT, LNG, SPAN_M = 12.9698, 77.7499, 3600.0
SEASON = (1, 1, 3, 31)          # Jan 1 - Mar 31, same as the provider
OUT_PX = 128                    # small: we only need statistics, not pictures
MAX_CLOUD = 40
YEARS = list(range(2017, dt.date.today().year + 1))

EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B03", "B08", "dataMask"]}],
    output: {bands: 4, sampleType: "FLOAT32"}
  };
}
function evaluatePixel(s) {
  return [s.B04, s.B03, s.B08, s.dataMask];
}
"""


def load_creds():
    path = os.path.join(HERE, "cdsekey.txt")
    if not os.path.exists(path):
        sys.exit("No cdsekey.txt found in the project root.")
    lines = [re.sub(r"\s+", "", l) for l in open(path, encoding="utf-8-sig") if l.strip()]
    if len(lines) < 2:
        sys.exit("cdsekey.txt needs client_id on line 1, client_secret on line 2.")
    return lines[0], lines[1]


def get_token(cid, secret):
    r = requests.post(TOKEN_URL,
                      data={"grant_type": "client_credentials",
                            "client_id": cid, "client_secret": secret},
                      timeout=(6, 30))
    if r.status_code != 200:
        sys.exit(f"Token failed HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["access_token"]


def bbox(lat, lng, span_m):
    dlat = (span_m / 2) / 111_320
    dlng = (span_m / 2) / (111_320 * np.cos(np.radians(lat)))
    return [lng - dlng, lat - dlat, lng + dlng, lat + dlat]


def fetch_year(token, bb, year, harmonize=False):
    sm, sd, em, ed = SEASON
    start, end = dt.date(year, sm, sd), dt.date(year, em, ed)

    data_entry = {
        "type": "sentinel-2-l2a",
        "dataFilter": {
            "timeRange": {"from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"},
            "maxCloudCoverage": MAX_CLOUD,
            "mosaickingOrder": "leastCC",
        },
    }
    if harmonize:
        # Ask Sentinel Hub to undo the 2022 baseline offset so all years are on
        # the same radiometric scale.
        data_entry["processing"] = {"harmonizeValues": True}

    payload = {
        "input": {"bounds": {"bbox": bb,
                             "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                  "data": [data_entry]},
        "output": {"width": OUT_PX, "height": OUT_PX,
                   "responses": [{"identifier": "default",
                                  "format": {"type": "image/tiff"}}]},
        "evalscript": EVALSCRIPT,
    }
    r = requests.post(PROCESS_URL, json=payload,
                      headers={"Authorization": f"Bearer {token}"},
                      timeout=(6, 90))
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:120]}"

    arr = np.asarray(tifffile.imread(BytesIO(r.content)), dtype=float)
    if arr.ndim != 3 or arr.shape[-1] < 4:
        return None, f"unexpected shape {arr.shape}"

    red, green, nir, mask = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    valid = mask > 0
    cov = float(valid.mean())
    if cov < 0.05:
        return None, f"coverage only {cov*100:.0f}%"

    def idx(a, b):
        d = a + b
        d = np.where(d == 0, 1e-6, d)
        return (a - b) / d

    ndvi = idx(nir, red)
    ndwi = idx(green, nir)
    return {
        "coverage": cov * 100,
        "veg_pct": float((ndvi[valid] > 0.3).mean() * 100),
        "water_pct": float((ndwi[valid] > 0.2).mean() * 100),
        "ndvi_mean": float(ndvi[valid].mean()),
        "red_mean": float(red[valid].mean()),
        "green_mean": float(green[valid].mean()),
        "nir_mean": float(nir[valid].mean()),
    }, None


def run(token, bb, harmonize):
    label = "HARMONIZED (baseline offset removed)" if harmonize else "RAW (as the provider currently requests)"
    print("\n" + "=" * 96)
    print(label)
    print("=" * 96)
    print(f"{'year':<6}{'cover%':>8}{'veg%':>8}{'water%':>8}{'ndvi':>8}"
          f"{'red':>9}{'green':>9}{'nir':>9}   note")
    print("-" * 96)
    rows = {}
    for y in YEARS:
        res, err = fetch_year(token, bb, y, harmonize=harmonize)
        if res is None:
            print(f"{y:<6}{'--':>8}{'--':>8}{'--':>8}{'--':>8}{'--':>9}{'--':>9}{'--':>9}   {err}")
            continue
        rows[y] = res
        note = ""
        if res["coverage"] < 60:
            note = "LOW COVERAGE"
        print(f"{y:<6}{res['coverage']:>8.0f}{res['veg_pct']:>8.1f}{res['water_pct']:>8.1f}"
              f"{res['ndvi_mean']:>8.3f}{res['red_mean']:>9.4f}{res['green_mean']:>9.4f}"
              f"{res['nir_mean']:>9.4f}   {note}")
    return rows


def interpret(raw, harm):
    print("\n" + "=" * 96)
    print("INTERPRETATION")
    print("=" * 96)

    if not raw:
        print("No usable years returned; cannot interpret.")
        return

    # 1. Step around 2022 in RAW reflectance?
    pre = [v["red_mean"] for y, v in raw.items() if y <= 2021]
    post = [v["red_mean"] for y, v in raw.items() if y >= 2022]
    if pre and post:
        jump = abs(np.mean(post) - np.mean(pre))
        rel = jump / max(np.mean(pre), 1e-6)
        print(f"\nRAW red reflectance: pre-2022 mean {np.mean(pre):.4f}, "
              f"2022+ mean {np.mean(post):.4f}  (shift {rel*100:.0f}%)")
        if rel > 0.15:
            print("  >> Large step across 2022. Consistent with the Sentinel-2")
            print("     processing baseline 04.00 offset. Compare the HARMONIZED")
            print("     table: if the step disappears there, the provider should")
            print("     set processing.harmonizeValues = true.")
        else:
            print("  >> No large step across 2022. Baseline offset is NOT the cause")
            print("     (or Sentinel Hub already harmonises by default).")

    # 2. Is 2017 an outlier low?
    if 2017 in raw and len(raw) > 2:
        others = [v["veg_pct"] for y, v in raw.items() if y != 2017]
        print(f"\n2017 vegetation {raw[2017]['veg_pct']:.1f}%  vs  "
              f"mean of other years {np.mean(others):.1f}% "
              f"(min {min(others):.1f}, max {max(others):.1f})")
        if raw[2017]["veg_pct"] < min(others):
            print("  >> 2017 is the LOWEST year in the series. Consistent with the")
            print("     2016-17 Karnataka drought. The number is real but 2017 is a")
            print("     poor baseline; a multi-year baseline would be fairer.")
        else:
            print("  >> 2017 is not an outlier low. Drought is not the explanation.")
        if raw[2017]["coverage"] < 60:
            print(f"  >> 2017 coverage is only {raw[2017]['coverage']:.0f}% — thin early")
            print("     archive (Sentinel-2B launched March 2017) may distort it.")

    # 3. Harmonized comparison
    if harm and raw:
        common = sorted(set(raw) & set(harm))
        if common:
            diffs = [abs(harm[y]["veg_pct"] - raw[y]["veg_pct"]) for y in common]
            print(f"\nHarmonizing changed vegetation % by "
                  f"{np.mean(diffs):.1f} points on average "
                  f"(max {max(diffs):.1f}).")
            if np.mean(diffs) > 3:
                print("  >> Harmonization matters. Set processing.harmonizeValues=true")
                print("     in imagery.py.")
            else:
                print("  >> Harmonization barely changes the result; not the cause.")

    print("\nWhat to do with this:")
    print("  - Series drifts smoothly            -> trend is real, keep as is.")
    print("  - Step at 2022 fixed by harmonizing -> enable harmonizeValues.")
    print("  - 2017 uniquely low                 -> use a multi-year baseline")
    print("                                         (e.g. mean of 2017-2019).")


def main():
    cid, secret = load_creds()
    token = get_token(cid, secret)
    bb = bbox(LAT, LNG, SPAN_M)
    print(f"Location : {LAT}, {LNG}  (Whitefield, Bengaluru)")
    print(f"Window   : Jan 1 - Mar 31, each year {YEARS[0]}-{YEARS[-1]}")
    print(f"Raster   : {OUT_PX}x{OUT_PX} over {SPAN_M/1000:.1f} km")

    raw = run(token, bb, harmonize=False)
    harm = run(token, bb, harmonize=True)
    interpret(raw, harm)


if __name__ == "__main__":
    main()
