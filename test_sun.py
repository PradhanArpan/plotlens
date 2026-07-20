"""
test_sun.py -- verify the solar engine against first principles and published
values. Pure computation: no keys, no network.

Run from the project root:   python test_sun.py

These tests exist because THREE separate sign/window bugs were found here on
2026-07-19, none of which raised an error — each produced plausible-looking
numbers that were simply wrong:
  1. sunrise and sunset swapped (sunrise reported at 18:48, negative day length)
  2. noon altitude scanned a fixed 11:00-13:00 clock window, so it failed
     wherever solar noon falls outside it (equator at lng 77 in IST -> 38 deg
     instead of 90)
  3. azimuth computed with acos, inverted twice in different ways -- first
     sunrise in the west, then December noon sun due north
Astronomy has known answers. Keep checking against them.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "backend", "plotlens"))
from plotlens.engine.sun import (                      # noqa: E402
    solar_position, sun_event, day_length_h, noon_altitude, shadow_ratio,
    compass, analyse)

FAILED = []


def chk(name, got, want, tol, unit=""):
    good = got is not None and abs(got - want) <= tol
    if not good:
        FAILED.append(name)
    g = f"{got:.2f}" if got is not None else "None"
    print(f"  {'PASS' if good else 'FAIL'}  {name:<46} {g:>8}{unit} (want {want:.2f}{unit})")


def istrue(name, cond, detail=""):
    if not cond:
        FAILED.append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<46} {detail}")


BLR = (12.9716, 77.5946)


def main():
    lat, lng = BLR

    print("=== noon altitude = 90 - |lat - declination| ===")
    for la, lo, label in [(0, 77.0, "equator"), (12.9716, 77.5946, "Bengaluru"),
                          (28.6139, 77.2090, "Delhi"), (-33.87, 151.21, "Sydney")]:
        chk(f"equinox, {label}", noon_altitude(la, lo, dt.date(2026, 3, 20)),
            90 - abs(la), 0.7, "deg")
    chk("Bengaluru Jun solstice", noon_altitude(lat, lng, dt.date(2026, 6, 21)),
        90 - abs(lat - 23.44), 0.7, "deg")
    chk("Bengaluru Dec solstice", noon_altitude(lat, lng, dt.date(2026, 12, 21)),
        90 - abs(lat + 23.44), 0.7, "deg")
    chk("Tropic of Cancer, Jun 21", noon_altitude(23.44, 77.0, dt.date(2026, 6, 21)),
        90.0, 0.7, "deg")

    print("\n=== sunrise / sunset azimuth ===")
    for d, lbl, er, es in [(dt.date(2026, 3, 20), "equinox", 90, 270),
                           (dt.date(2026, 6, 21), "Jun solstice", 66, 294),
                           (dt.date(2026, 12, 21), "Dec solstice", 114, 246)]:
        r, raz = sun_event(lat, lng, d, True)
        s, saz = sun_event(lat, lng, d, False)
        istrue(f"{lbl} rise/set bearing",
               abs(raz - er) <= 3 and abs(saz - es) <= 3,
               f"{r} @ {raz:.0f} {compass(raz)} | {s} @ {saz:.0f} {compass(saz)}")

    print("\n=== hemisphere sanity ===")
    _, az = solar_position(lat, lng, dt.datetime(2026, 12, 21, 12, 25))
    istrue("Bengaluru Dec noon sun is south", 150 < az < 210, f"{az:.0f} deg")
    _, az2 = solar_position(-33.87, 151.21, dt.datetime(2026, 6, 21, 12, 0), tz_offset_h=10)
    istrue("Sydney Jun noon sun is north", az2 < 40 or az2 > 320, f"{az2:.0f} deg")
    _, a8 = solar_position(lat, lng, dt.datetime(2026, 3, 20, 8, 0))
    _, a16 = solar_position(lat, lng, dt.datetime(2026, 3, 20, 16, 0))
    istrue("morning sun east", a8 < 180, f"{a8:.0f} deg")
    istrue("afternoon sun west", a16 > 180, f"{a16:.0f} deg")

    print("\n=== published times (Bengaluru IST, within 5 min) ===")
    def mins(t):
        h, m = map(int, t.split(":"))
        return h * 60 + m
    for d, er, es, lbl in [(dt.date(2026, 6, 21), 355, 1130, "Jun 21 ~05:55/18:50"),
                           (dt.date(2026, 12, 21), 395, 1077, "Dec 21 ~06:35/17:57")]:
        r, _ = sun_event(lat, lng, d, True)
        s, _ = sun_event(lat, lng, d, False)
        istrue(lbl, abs(mins(r) - er) <= 5 and abs(mins(s) - es) <= 5, f"got {r} / {s}")

    print("\n=== day length ===")
    chk("equinox ~12 h", day_length_h(lat, lng, dt.date(2026, 3, 20)), 12.1, 0.25, " h")
    jun = day_length_h(lat, lng, dt.date(2026, 6, 21))
    dec = day_length_h(lat, lng, dt.date(2026, 12, 21))
    istrue("June longer than December", jun > dec, f"{jun} h vs {dec} h")
    swing_b = jun - dec
    swing_d = (day_length_h(28.61, 77.21, dt.date(2026, 6, 21))
               - day_length_h(28.61, 77.21, dt.date(2026, 12, 21)))
    istrue("Delhi swings more than Bengaluru", swing_d > swing_b,
           f"{swing_d:.2f} h vs {swing_b:.2f} h")
    sy_j = day_length_h(-33.87, 151.21, dt.date(2026, 6, 21))
    sy_d = day_length_h(-33.87, 151.21, dt.date(2026, 12, 21))
    istrue("southern hemisphere inverts", sy_d > sy_j, f"Dec {sy_d} h vs Jun {sy_j} h")

    print("\n=== shadow ratio ===")
    chk("45 deg -> 1.00x", shadow_ratio(45), 1.0, 0.001)
    chk("30 deg -> 1.73x", shadow_ratio(30), 1.732, 0.005)
    chk("60 deg -> 0.58x", shadow_ratio(60), 0.577, 0.005)
    istrue("below horizon -> None", shadow_ratio(-5) is None)

    print("\n=== full site summary ===")
    r = analyse(12.9698, 77.7499, 2026)
    print(f"  Jun noon {r.summer_noon_alt} deg | Dec noon {r.winter_noon_alt} deg")
    print(f"  sunrise arc {r.sunrise_arc_deg} deg | zenith passage {r.zenith_passage}")
    print(f"  {r.reading}")

    print()
    if FAILED:
        print("FAILURES:", ", ".join(FAILED))
        sys.exit(1)
    print("ALL SOLAR TESTS PASS")


if __name__ == "__main__":
    main()
