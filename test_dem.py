"""
test_dem.py -- exercise PlotLens's OWN SRTMProvider (not a standalone request).

Place next to otkey.txt in C:\\Users\\HP\\plotlens-project\\
Run:  python test_dem.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "backend", "plotlens"))

try:
    from plotlens.data.dem import SRTMProvider, SyntheticDEM
except ImportError as e:
    sys.exit(f"Could not import PlotLens dem module: {e}\n"
             f"Check that backend/plotlens/plotlens/data/dem.py exists.")


def load_key():
    path = os.path.join(HERE, "otkey.txt")
    if not os.path.exists(path):
        sys.exit("No otkey.txt found next to this script.")
    with open(path, encoding="utf-8-sig") as f:
        return re.sub(r"\s+", "", f.read().strip())


# Whitefield, Bengaluru. 400 m window, engine asks for 5 m grid.
LAT, LNG, SPAN, RES = 12.9698, 77.7500, 400.0, 5.0


def show(tile, label):
    z = tile.z
    print(f"\n--- {label} ---")
    print(f"source      : {tile.source}")
    print(f"grid shape  : {z.shape}")
    print(f"res_m       : {tile.res_m:.2f} m/px   <-- used for slope math")
    print(f"min / max   : {z.min():.1f} / {z.max():.1f} m")
    print(f"mean        : {z.mean():.1f} m")
    print(f"relief      : {z.max() - z.min():.1f} m")
    print(f"any NaN?    : {bool(__import__('numpy').isnan(z).any())}")

    # Crude slope check, same way terrain.py does it.
    import numpy as np
    gy, gx = np.gradient(z, tile.res_m)
    slope_pct = np.hypot(gx, gy) * 100
    print(f"mean slope  : {slope_pct.mean():.2f} %")
    print(f"max slope   : {slope_pct.max():.2f} %")


def main():
    print("Fetching SYNTHETIC tile for comparison ...")
    show(SyntheticDEM(archetype="upland").fetch(LAT, LNG, SPAN, RES), "SYNTHETIC")

    key = load_key()
    for dem_type in ("SRTMGL1", "COP30"):
        print(f"\nFetching REAL tile: {dem_type} ...")
        try:
            tile = SRTMProvider(key, dem_type=dem_type).fetch(LAT, LNG, SPAN, RES)
            show(tile, f"REAL {dem_type}")
        except Exception as e:
            print(f"  FAILED ({dem_type}): {e}")

    print("\nSanity: Whitefield mean should be ~880 m, slopes gentle (a few %).")
    print("If real slope is wildly higher than synthetic, res_m is still wrong.")


if __name__ == "__main__":
    main()
