"""
plotlens.engine.sun — solar geometry for a site. Pure computation.

No API, no key, no rate limit, no network. Solar position is a closed-form
function of latitude, longitude and date, so this is the one module in PlotLens
whose answers cannot be stale, throttled, or wrong because a provider changed
something.

Algorithm: NOAA Solar Calculator (Astronomical Algorithms, Meeus). Accurate to
roughly a minute for sunrise/sunset and a fraction of a degree in azimuth over
the years and latitudes PlotLens covers. That is far finer than any decision a
plot buyer makes from it.

WHAT THIS IS FOR:
    Which way the plot faces the sun, how high the sun gets in summer and
    winter, where it rises and sets across the year, and how long a shadow a
    neighbouring building casts. In India these drive room layout, terrace
    orientation, solar-panel viability and — for many buyers — vaastu.

WHAT IT IS NOT:
    It is astronomy, not meteorology. It says where the sun IS, not whether
    cloud will be in the way. Anything about cloudiness or actual insolation
    needs a climate source and must not be inferred from this module.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import datetime as dt
import math

# India Standard Time. Kept explicit rather than assumed from the system clock,
# which on a server is usually UTC.
IST_OFFSET_H = 5.5

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg):
    """Compass point for a bearing in degrees."""
    if deg is None:
        return None
    return COMPASS_16[int((deg % 360) / 22.5 + 0.5) % 16]


# ----------------------------------------------------------------------
# NOAA solar position
# ----------------------------------------------------------------------
def _julian_day(d: dt.date) -> float:
    y, m, day = d.year, d.month, d.day
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
            + day + b - 1524.5)


def _solar_terms(jd, minutes_utc):
    """Return (declination_deg, equation_of_time_min) for a moment."""
    jc = (jd + minutes_utc / 1440.0 - 2451545.0) / 36525.0

    # geometric mean longitude and anomaly of the sun
    gml = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    gma = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)

    # equation of centre -> true longitude -> apparent longitude
    c = (math.sin(math.radians(gma)) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
         + math.sin(math.radians(2 * gma)) * (0.019993 - 0.000101 * jc)
         + math.sin(math.radians(3 * gma)) * 0.000289)
    true_long = gml + c
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    # obliquity of the ecliptic, corrected
    seconds = 21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))
    e0 = 23.0 + (26.0 + seconds / 60.0) / 60.0
    e = e0 + 0.00256 * math.cos(math.radians(omega))

    decl = math.degrees(math.asin(
        math.sin(math.radians(e)) * math.sin(math.radians(app_long))))

    # equation of time
    var_y = math.tan(math.radians(e / 2.0)) ** 2
    eot = 4.0 * math.degrees(
        var_y * math.sin(2 * math.radians(gml))
        - 2.0 * 0.016708634 * math.sin(math.radians(gma))
        + 4.0 * 0.016708634 * var_y * math.sin(math.radians(gma))
          * math.cos(2 * math.radians(gml))
        - 0.5 * var_y * var_y * math.sin(4 * math.radians(gml))
        - 1.25 * 0.016708634 * 0.016708634 * math.sin(2 * math.radians(gma)))
    return decl, eot


def solar_position(lat, lng, when_local: dt.datetime, tz_offset_h=IST_OFFSET_H):
    """
    Sun altitude and azimuth for a local wall-clock time.
    Returns (altitude_deg, azimuth_deg) with azimuth measured clockwise from
    north. Altitude is NOT refraction-corrected; near the horizon the true
    geometric angle is what shadow maths wants.
    """
    d = when_local.date()
    minutes_local = when_local.hour * 60 + when_local.minute + when_local.second / 60.0
    minutes_utc = minutes_local - tz_offset_h * 60.0
    jd = _julian_day(d)
    decl, eot = _solar_terms(jd, minutes_utc)

    true_solar_min = (minutes_local + eot + 4.0 * lng - 60.0 * tz_offset_h) % 1440.0
    hour_angle = true_solar_min / 4.0 - 180.0

    la, de, ha = map(math.radians, (lat, decl, hour_angle))
    cos_zen = (math.sin(la) * math.sin(de)
               + math.cos(la) * math.cos(de) * math.cos(ha))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.acos(cos_zen)
    altitude = 90.0 - math.degrees(zenith)

    # Azimuth clockwise from north, via atan2.
    #
    # Deliberately NOT the acos form. Two earlier attempts with acos both came
    # out inverted — first sunrise at 270 degrees, then Bengaluru's December
    # noon sun due north — because acos only spans 0-180 and the quadrant has
    # to be chosen by hand, which is easy to get backwards and produces output
    # that still looks superficially reasonable. atan2 resolves the quadrant
    # from the signs of both components, so it cannot be inverted.
    #
    #   x = sin(H)
    #   y = cos(H) * sin(lat) - tan(decl) * cos(lat)
    #   azimuth = atan2(x, y) measured from SOUTH, + 180 to reference north.
    x = math.sin(ha)
    y = math.cos(ha) * math.sin(la) - math.tan(de) * math.cos(la)
    azimuth = (math.degrees(math.atan2(x, y)) + 180.0) % 360.0
    return altitude, azimuth


def _event_minutes(lat, lng, d: dt.date, rising: bool, tz_offset_h=IST_OFFSET_H):
    """
    Local minutes past midnight for sunrise or sunset, or None if the sun
    neither rises nor sets that day (polar cases; not reachable in India but
    handled rather than crashing).
    """
    jd = _julian_day(d)
    decl, eot = _solar_terms(jd, 720.0 - tz_offset_h * 60.0)
    # 90.833 deg accounts for refraction and the solar disc radius
    la, de = math.radians(lat), math.radians(decl)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(de))
              - math.tan(la) * math.tan(de))
    if cos_ha > 1 or cos_ha < -1:
        return None
    ha = math.degrees(math.acos(cos_ha))
    # Sunrise is at NEGATIVE hour angle (before solar noon), sunset positive.
    # The 720 - 4*(lng + ha) form already negates ha, so `rising` takes ha as
    # returned by acos and `setting` negates it. Getting this backwards swaps
    # the two events — it produced "sunrise 18:48, sunset 05:54" and negative
    # day lengths, which is how the bug was caught.
    if not rising:
        ha = -ha
    return 720.0 - 4.0 * (lng + ha) - eot + tz_offset_h * 60.0


def sun_event(lat, lng, d: dt.date, rising: bool, tz_offset_h=IST_OFFSET_H):
    """Returns (time_str 'HH:MM', azimuth_deg) or (None, None)."""
    mins = _event_minutes(lat, lng, d, rising, tz_offset_h)
    if mins is None:
        return None, None
    mins %= 1440.0
    t = dt.datetime.combine(d, dt.time()) + dt.timedelta(minutes=mins)
    _, az = solar_position(lat, lng, t, tz_offset_h)
    return t.strftime("%H:%M"), round(az, 1)


def day_length_h(lat, lng, d: dt.date, tz_offset_h=IST_OFFSET_H):
    r = _event_minutes(lat, lng, d, True, tz_offset_h)
    s = _event_minutes(lat, lng, d, False, tz_offset_h)
    if r is None or s is None:
        return None
    return round((s - r) / 60.0, 2)


def solar_noon_minutes(lat, lng, d: dt.date, tz_offset_h=IST_OFFSET_H):
    """Local minutes past midnight at solar noon."""
    jd = _julian_day(d)
    _, eot = _solar_terms(jd, 720.0 - tz_offset_h * 60.0)
    return (720.0 - 4.0 * lng - eot + tz_offset_h * 60.0) % 1440.0


def noon_altitude(lat, lng, d: dt.date, tz_offset_h=IST_OFFSET_H):
    """
    Sun altitude at solar noon — the day's maximum.

    Computes solar noon directly rather than scanning a fixed clock window.
    An earlier version scanned only 11:00-13:00 local, which is wrong wherever
    solar noon falls outside that band: on the equator at longitude 77 in IST,
    or anywhere far from its timezone meridian. It returned 38 degrees for the
    equator at equinox, where the true answer is 90.
    """
    centre = solar_noon_minutes(lat, lng, d, tz_offset_h)
    base = dt.datetime.combine(d, dt.time())
    best = -90.0
    for k in range(-20, 21, 2):      # +/- 20 min around true solar noon
        t = base + dt.timedelta(minutes=centre + k)
        alt, _ = solar_position(lat, lng, t, tz_offset_h)
        best = max(best, alt)
    return round(best, 1)


def shadow_ratio(altitude_deg):
    """
    Shadow length as a multiple of object height. A 10 m building at 20 deg
    altitude casts 10 * 2.75 = 27.5 m. Returns None at or below the horizon.
    """
    if altitude_deg is None or altitude_deg <= 0.5:
        return None
    return round(1.0 / math.tan(math.radians(altitude_deg)), 2)


# ----------------------------------------------------------------------
# Site-level summary
# ----------------------------------------------------------------------
@dataclass
class SunResult:
    summer_noon_alt: float          # ~21 Jun, degrees above horizon
    winter_noon_alt: float          # ~21 Dec
    equinox_noon_alt: float         # ~21 Mar
    summer_sunrise: str
    summer_sunrise_az: float
    summer_sunset: str
    summer_sunset_az: float
    winter_sunrise: str
    winter_sunrise_az: float
    winter_sunset: str
    winter_sunset_az: float
    summer_day_h: float
    winter_day_h: float
    sunrise_arc_deg: float          # spread of sunrise bearings across the year
    winter_shadow_ratio: float | None   # at winter noon, per unit height
    zenith_passage: str | None      # dates the sun is directly overhead
    best_facade: str                # which orientation gets winter sun
    reading: str
    source: str = "computed (NOAA solar position algorithm)"

    def scalars(self):
        return asdict(self)


def _zenith_passage_dates(lat, lng, year, tz_offset_h=IST_OFFSET_H):
    """
    Dates when the sun passes within half a degree of vertical. Only happens
    between the tropics — which includes almost all of India south of ~23.4 N,
    a fact many buyers find striking: for a few days a year, walls cast no
    shadow at noon.
    """
    hits = []
    d = dt.date(year, 1, 1)
    prev = None
    while d.year == year:
        alt = noon_altitude(lat, lng, d, tz_offset_h)
        if prev is not None and ((prev < 90.0 <= alt) or (prev > 90.0 >= alt)):
            hits.append(d)
        if abs(alt - 90.0) < 0.35 and (not hits or (d - hits[-1]).days > 5):
            hits.append(d)
        prev = alt
        d += dt.timedelta(days=1)
    if not hits:
        return None
    return ", ".join(h.strftime("%d %b") for h in hits[:2])


def analyse(lat, lng, year=None, tz_offset_h=IST_OFFSET_H) -> SunResult:
    year = year or dt.date.today().year
    jun = dt.date(year, 6, 21)
    dec = dt.date(year, 12, 21)
    mar = dt.date(year, 3, 21)

    s_rise, s_rise_az = sun_event(lat, lng, jun, True, tz_offset_h)
    s_set, s_set_az = sun_event(lat, lng, jun, False, tz_offset_h)
    w_rise, w_rise_az = sun_event(lat, lng, dec, True, tz_offset_h)
    w_set, w_set_az = sun_event(lat, lng, dec, False, tz_offset_h)

    summer_alt = noon_altitude(lat, lng, jun, tz_offset_h)
    winter_alt = noon_altitude(lat, lng, dec, tz_offset_h)
    equinox_alt = noon_altitude(lat, lng, mar, tz_offset_h)

    arc = abs((s_rise_az or 0) - (w_rise_az or 0))
    ratio = shadow_ratio(winter_alt)
    zenith = _zenith_passage_dates(lat, lng, year, tz_offset_h)

    # In the northern hemisphere the winter sun sits in the southern sky, so a
    # south-facing wall receives it. Stated as geometry, not as a vaastu claim.
    facade = "south" if lat >= 0 else "north"

    parts = [
        f"At solar noon the sun reaches {summer_alt:.0f}° in June and "
        f"{winter_alt:.0f}° in December.",
    ]
    if ratio:
        parts.append(f"A 10 m building to the {facade} casts a {ratio * 10:.0f} m "
                     f"shadow at midwinter noon — the worst case for the year.")
    parts.append(f"Sunrise swings {arc:.0f}° across the year, from "
                 f"{compass(w_rise_az)} in winter to {compass(s_rise_az)} in summer.")
    if zenith:
        parts.append(f"The sun passes directly overhead around {zenith}, when "
                     f"vertical walls cast almost no shadow at noon.")
    parts.append(f"Openings on the {facade} side receive the most winter sun.")

    return SunResult(
        summer_noon_alt=summer_alt, winter_noon_alt=winter_alt,
        equinox_noon_alt=equinox_alt,
        summer_sunrise=s_rise, summer_sunrise_az=s_rise_az,
        summer_sunset=s_set, summer_sunset_az=s_set_az,
        winter_sunrise=w_rise, winter_sunrise_az=w_rise_az,
        winter_sunset=w_set, winter_sunset_az=w_set_az,
        summer_day_h=day_length_h(lat, lng, jun, tz_offset_h),
        winter_day_h=day_length_h(lat, lng, dec, tz_offset_h),
        sunrise_arc_deg=round(arc, 1),
        winter_shadow_ratio=ratio,
        zenith_passage=zenith,
        best_facade=facade,
        reading=" ".join(parts),
    )
