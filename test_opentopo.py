"""
test_opentopo.py -- verify an OpenTopography API key works.

Reads the key from a plain text file 'otkey.txt' in the SAME folder,
so there is no blind pasting into the terminal.

Setup:
  1. Create otkey.txt next to this script.
  2. Paste ONLY the key into it. Nothing else. Save.
  3. Run:  python test_opentopo.py
"""

import os
import re
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing 'requests'. Run:  pip install requests")

# Small bbox over Whitefield, Bengaluru (~2 km square).
SOUTH, NORTH = 12.960, 12.980
WEST, EAST = 77.740, 77.760

URL = "https://portal.opentopography.org/API/globaldem"
KEYFILE = "otkey.txt"
OUT = "opentopo_test.tif"


def load_key():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, KEYFILE)
    if not os.path.exists(path):
        sys.exit(f"No '{KEYFILE}' found in {here}\n"
                 f"Create it and paste ONLY your API key inside.")

    with open(path, "r", encoding="utf-8-sig") as f:
        raw = f.read()

    # Strip whitespace, newlines, quotes, and any stray label like "API Key:"
    key = raw.strip().strip('"').strip("'")
    if ":" in key:
        key = key.split(":")[-1].strip()
    key = re.sub(r"\s+", "", key)

    if not key:
        sys.exit(f"'{KEYFILE}' is empty.")

    # OpenTopography keys are 32 hexadecimal characters.
    if not re.fullmatch(r"[0-9a-fA-F]{32}", key):
        print(f"WARNING: key looks unusual -- {len(key)} chars, expected 32 hex.")
        print(f"         Read as: {key[:6]}...{key[-4:]}")
        print("         Check otkey.txt contains ONLY the key.\n")
    else:
        print(f"Key loaded  : {key[:6]}...{key[-4:]}  ({len(key)} chars, looks valid)")

    return key


def main():
    key = load_key()

    params = {
        "demtype": "SRTMGL1",
        "south": SOUTH, "north": NORTH,
        "west": WEST, "east": EAST,
        "outputFormat": "GTiff",
        "API_Key": key,
    }

    print("Requesting elevation for Whitefield, Bengaluru ...")
    try:
        r = requests.get(URL, params=params, timeout=90)
    except requests.RequestException as e:
        sys.exit(f"NETWORK ERROR: {e}")

    print(f"HTTP status : {r.status_code}")
    print(f"Bytes       : {len(r.content):,}")

    if r.status_code != 200:
        print("\n--- FAILED. Server said: ---")
        print(r.text[:600])
        return

    if r.content[:2] not in (b"II", b"MM"):
        print("\n--- Got 200 but this is NOT a GeoTIFF: ---")
        print(r.content[:400])
        return

    with open(OUT, "wb") as f:
        f.write(r.content)
    print(f"Saved       : {OUT}")

    try:
        import numpy as np
        import tifffile
    except ImportError:
        print("\nKEY WORKS -- real GeoTIFF downloaded.")
        print("(pip install tifffile numpy  to also print elevation values.)")
        return

    arr = tifffile.imread(OUT).astype("float64")
    valid = arr[arr > -1000]
    if valid.size == 0:
        print("\nDownloaded, but all elevation values are void.")
        return

    print("\n--- REAL ELEVATION DATA ---")
    print(f"Grid shape  : {arr.shape}")
    print(f"Min         : {valid.min():.1f} m")
    print(f"Max         : {valid.max():.1f} m")
    print(f"Mean        : {valid.mean():.1f} m")
    print(f"Relief      : {valid.max() - valid.min():.1f} m")
    print("\nBengaluru sits around 880-920 m.")
    print("A mean in that range means this is genuinely real data.")


if __name__ == "__main__":
    main()
