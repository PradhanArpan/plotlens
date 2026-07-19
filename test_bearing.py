"""
Verify the drainage_bearing formula from plotlens/engine/terrain.py against
synthetic slopes with KNOWN downhill directions.

Convention being tested: north-up raster (row 0 = north edge), which is what
OpenTopography GeoTIFFs return. So increasing row index = moving SOUTH.
"""
import numpy as np

def bearing_from_grid(z):
    """Exactly the formula used in terrain.analyse()."""
    gy, gx = np.gradient(z)
    dx, dy = float(np.mean(gx)), float(np.mean(gy))
    return (np.degrees(np.arctan2(-dx, dy)) + 360) % 360

n = 40
rows, cols = np.mgrid[0:n, 0:n]   # rows increase southward, cols increase eastward

cases = {
    # downhill toward NORTH  -> elevation INCREASES going south (with row index)
    "north (0)":  (rows * 1.0,          0.0),
    # downhill toward EAST   -> elevation DECREASES going east (with col index)
    "east (90)":  (-cols * 1.0,        90.0),
    # downhill toward SOUTH  -> elevation DECREASES going south
    "south (180)": (-rows * 1.0,      180.0),
    # downhill toward WEST   -> elevation INCREASES going east
    "west (270)": (cols * 1.0,        270.0),
    # diagonal: downhill toward NORTH-EAST
    "northeast (45)": (rows - cols,    45.0),
}

print(f"{'case':<18}{'expected':>10}{'computed':>12}   result")
print("-" * 55)
ok = True
for label, (z, expected) in cases.items():
    got = bearing_from_grid(z.astype(float))
    diff = min(abs(got - expected), 360 - abs(got - expected))
    passed = diff < 0.5
    ok &= passed
    print(f"{label:<18}{expected:>10.0f}{got:>12.1f}   {'PASS' if passed else 'FAIL'}")

print("-" * 55)
print("ALL PASS" if ok else "FAILURES PRESENT")
