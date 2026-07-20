"""
test_plot_geometry.py -- verify the polygon engine against shapes whose answers
are known independently of the code.

Run from the project root:   python test_plot_geometry.py
Pure computation: no API keys, no network.

The frontage cases exist because of a real bug found on 2026-07-19: without a
parallel-edge test, a 30x20 m plot beside a road reported 43.3 m of frontage
instead of 30 m, because the two side edges had their near ends within the
touch distance. Frontage drives price, so that error mattered more than any
other in this module. Keep these tests.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "backend", "plotlens"))
from plotlens.engine.plot_geometry import (           # noqa: E402
    area, perimeter, is_convex, self_intersects, edge_frontage,
    setback_report, analyse_polygon, SQM_PER_ACRE, SQFT_PER_M2)

FT = 0.3048
FAILED = []


def check(name, got, want, tol):
    good = abs(got - want) <= tol
    if not good:
        FAILED.append(name)
    print(f"  {'PASS' if good else 'FAIL'}  {name:<48} got {got:>9.2f} want {want:>9.2f}")


def istrue(name, got, want=True):
    good = (got is want)
    if not good:
        FAILED.append(name)
    print(f"  {'PASS' if good else 'FAIL'}  {name:<48} {got} (want {want})")


def main():
    print("=== area / perimeter ===")
    w, h = 30 * FT, 40 * FT
    sq = [(0, 0), (w, 0), (w, h), (0, h)]
    check("30x40 ft plot in sqft", area(sq) * SQFT_PER_M2, 1200, 0.5)
    check("perimeter m", perimeter(sq), 2 * (w + h), 0.01)
    side = math.sqrt(SQM_PER_ACRE)
    check("1 acre square m2", area([(0, 0), (side, 0), (side, side), (0, side)]),
          4046.86, 0.5)
    check("3-4-5 triangle m2", area([(0, 0), (30, 0), (0, 40)]), 600.0, 0.01)
    check("winding does not change area",
          area([(0, 0), (0, h), (w, h), (w, 0)]), area(sq), 0.01)

    print("\n=== validity guards ===")
    istrue("bowtie detected", self_intersects([(0, 0), (10, 10), (10, 0), (0, 10)]))
    istrue("square not flagged", self_intersects(sq), False)
    L = [(0, 0), (20, 0), (20, 10), (10, 10), (10, 20), (0, 20)]
    istrue("L-shape is non-convex", is_convex(L), False)
    istrue("square is convex", is_convex(sq))

    print("\n=== setbacks ===")
    p = [(0, 0), (30, 0), (30, 20), (0, 20)]
    check("20x30 m less 3 m all round", setback_report(p, 3.0)["buildable_m2"],
          24 * 14, 0.5)
    istrue("4 m setback eats a 6 m strip",
           setback_report([(0, 0), (20, 0), (20, 6), (0, 6)], 4.0)["feasible"], False)
    istrue("non-convex declined, not guessed",
           setback_report(L, 3.0)["feasible"], None)

    print("\n=== frontage (the bug that mattered) ===")
    road = [{"kind": "road", "name": "Test Road", "coords": [(-50, -6), (80, -6)]}]
    _, total = edge_frontage(p, road)
    check("one road -> one edge only", total, 30.0, 1.0)
    corner = road + [{"kind": "road", "name": "Cross Rd",
                      "coords": [(-6, -50), (-6, 80)]}]
    _, total2 = edge_frontage(p, corner)
    check("corner plot -> two edges", total2, 50.0, 2.0)
    diag = [{"kind": "road", "name": "Diagonal",
             "coords": [(-30, -36), (60, 54)]}]
    _, td = edge_frontage(p, diag)
    check("45-degree road -> no frontage", td, 0.0, 0.01)
    far = [{"kind": "road", "name": "Far Rd", "coords": [(-50, -40), (80, -40)]}]
    _, tf = edge_frontage(p, far)
    check("road 40 m away -> no frontage", tf, 0.0, 0.01)

    print("\n=== raster gate (resolution honesty) ===")
    small = analyse_polygon(sq)
    big = analyse_polygon([(0, 0), (side, 0), (side, side), (0, side)])
    istrue("30x40 ft: raster stats refused", small.raster_stats_meaningful, False)
    istrue("1 acre: raster stats allowed", big.raster_stats_meaningful, True)
    check("40 guntas to the acre", big.area_guntas, 40.0, 0.3)

    print("\n=== bad input rejected ===")
    for bad, label in (([(0, 0), (10, 10), (10, 0), (0, 10)], "bowtie"),
                       ([(0, 0), (1, 1)], "two points")):
        try:
            analyse_polygon(bad)
            print(f"  FAIL  {label} accepted")
            FAILED.append(label)
        except ValueError:
            print(f"  PASS  {label} rejected")

    print()
    if FAILED:
        print("FAILURES:", ", ".join(FAILED))
        sys.exit(1)
    print("ALL PLOT GEOMETRY TESTS PASS")


if __name__ == "__main__":
    main()
