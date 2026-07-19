"""
plotlens.render.dossier — assemble the full PDF report.

Composes the three computed artifacts (terrain, rings, change) plus the
8-category readings into one branded, downloadable dossier. reportlab Platypus.

Honesty is structural: every category shows its confidence tag, and the
Development Rules & Legal section states plainly what cannot be satellite-checked.
"""
from __future__ import annotations
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                Table, TableStyle, HRFlowable, PageBreak)

INK = colors.HexColor("#1f1d18")
PAPER = colors.HexColor("#faf7ef")
EDGE = colors.HexColor("#e7e1d2")
MUTE = colors.HexColor("#8a8577")
STATUS_COL = {"good": colors.HexColor("#3f7d4e"),
              "caution": colors.HexColor("#b5862b"),
              "flag": colors.HexColor("#b5452b"),
              "check": colors.HexColor("#5a6b8a")}
SOURCE_LABEL = {"derived": "Satellite-derived", "partial": "Indicative",
                "offline": "Needs site / legal check"}


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("H1", parent=s["Title"], textColor=INK, fontSize=22,
                         spaceAfter=2, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle("Sub", parent=s["Normal"], textColor=MUTE, fontSize=10, spaceAfter=10))
    s.add(ParagraphStyle("Eyebrow", parent=s["Normal"], textColor=MUTE, fontSize=8,
                         spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle("CatTitle", parent=s["Normal"], textColor=INK, fontSize=13,
                         fontName="Helvetica-Bold", spaceAfter=1))
    s.add(ParagraphStyle("Body", parent=s["Normal"], textColor=colors.HexColor("#2c2a23"),
                         fontSize=9.5, leading=13))
    s.add(ParagraphStyle("Small", parent=s["Normal"], textColor=MUTE, fontSize=8, leading=11))
    return s


def _verdict_banner(status, note, S):
    col = STATUS_COL.get(status, INK)
    label = {"good": "Looks good", "caution": "Caution", "flag": "Flag",
             "check": "Verify offline"}.get(status, status.title())
    cell = [[Paragraph(f"<b>Overall read: {label}</b>", ParagraphStyle(
                "v", textColor=colors.white, fontSize=13, fontName="Helvetica-Bold"))],
            [Paragraph(note, ParagraphStyle("vn", textColor=colors.white, fontSize=9.5, leading=13))]]
    t = Table(cell, colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), col),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (0, 0), 10),
                           ("BOTTOMPADDING", (0, -1), (-1, -1), 10)]))
    return t


def _category(cat, S):
    """cat: dict with title, source, status, rows[[k,v]], optional offline_note."""
    col = STATUS_COL.get(cat["status"], INK)
    col_hex = "#" + col.hexval()[2:]
    head = Table([[Paragraph(cat["title"], S["CatTitle"]),
                   Paragraph(f'<font color="{col_hex}"><b>{cat["status"].upper()}</b></font>'
                             f'<br/><font size=7 color="#888888">{SOURCE_LABEL[cat["source"]]}</font>',
                             ParagraphStyle("r", alignment=2, fontSize=9))]],
                 colWidths=[120 * mm, 50 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    rows = [[Paragraph(k, S["Small"]), Paragraph(str(v), S["Body"])] for k, v in cat["rows"]]
    body = Table(rows, colWidths=[55 * mm, 115 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LINEBELOW", (0, 0), (-1, -2), 0.4, EDGE),
                              ("TOPPADDING", (0, 0), (-1, -1), 4),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    flow = [head, Spacer(1, 4), body]
    if cat.get("offline_note"):
        flow += [Spacer(1, 4), Paragraph(f'<i>{cat["offline_note"]}</i>',
                 ParagraphStyle("off", textColor=STATUS_COL["check"], fontSize=8.5, leading=12))]
    flow += [Spacer(1, 6), HRFlowable(width="100%", color=EDGE, thickness=0.6), Spacer(1, 8)]
    return flow


def build(result: dict, out_path: str):
    """result: the dict from pipeline.run_report (+ optional address)."""
    S = _styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=16 * mm,
                            title="PlotLens Site Analysis")
    story = []
    c = result["coords"]
    story.append(Paragraph("PlotLens — Site Analysis", S["H1"]))
    story.append(Paragraph(result.get("address",
                 f'{c["lat"]:.4f}, {c["lng"]:.4f}'), S["Sub"]))

    # overall = worst of the three engine statuses
    statuses = [result["terrain"]["water_status"],
                result["access"]["access_status"],
                result["imagery"]["change_status"]]
    rank = {"good": 0, "caution": 1, "flag": 2}
    overall = max(statuses, key=lambda s: rank.get(s, 0))
    note = {"good": "No major natural-hazard signals on satellite data. Still confirm on the ground and check title/zoning.",
            "caution": "One or more factors need a closer look before you commit. See flagged categories below.",
            "flag": "Strong caution on at least one factor. Treat the flagged categories as deal-critical to verify."}[overall]
    story.append(_verdict_banner(overall, note, S))
    story.append(Spacer(1, 12))

    # ---- the three computed artifacts ----
    story.append(Paragraph("COMPUTED ANALYSIS", S["Eyebrow"]))
    sizes = {"terrain": (170, 88), "change": (170, 63), "rings": (110, 110)}
    for key, cap in [("terrain", "Terrain: contours, slope & water-flow accumulation"),
                     ("change", "Then vs now: land-cover change (Sentinel-2)"),
                     ("rings", "Access & surroundings: distances to roads, water, services")]:
        img = result["artifacts"].get(key)
        if img:
            w, h = sizes[key]
            story.append(Image(img, width=w * mm, height=h * mm))
            story.append(Paragraph(cap, S["Small"]))
            story.append(Spacer(1, 8))

    story.append(PageBreak())
    story.append(Paragraph("SITE ANALYSIS · 8 CATEGORIES", S["Eyebrow"]))

    t, a, im = result["terrain"], result["access"], result["imagery"]
    cats = [
        {"title": "1 · Topography & Geology", "source": "derived", "status": t["water_status"],
         "rows": [["Elevation", f'{t["plot_mean_elev"]} m'], ["Slope", f'{t["mean_slope_pct"]} %'],
                  ["Below surroundings", f'{t["rel_to_surroundings"]} m'],
                  ["Rock/soil", "Inferred from regional geology — confirm with a bore test"]]},
        {"title": "2 · Water & Drainage", "source": "derived", "status": t["water_status"],
         "rows": [["Water-collection index", f'{t["flow_ratio"]}x area average'],
                  ["Nearest water body", f'{a["nearest_water_m"]:.0f} m ({a["nearest_water_name"]})'],
                  ["Drainage bearing", f'{t["drainage_bearing"]:.0f} deg'],
                  ["Reading", t["reading"]]]},
        {"title": "3 · Climate & Natural Factors", "source": "derived", "status": "good",
         "rows": [["Sun path", "E-W, standard for latitude"],
                  ["Note", "Rainfall, wind & seismic zone added from climate/seismic datasets on deploy"]]},
        {"title": "4 · Circulation & Access", "source": "derived", "status": a["access_status"],
         "rows": [["Nearest road", f'{a["nearest_road_m"]:.0f} m ({a["nearest_road_name"]})'],
                  ["Public transport", f'{a["nearest_transit_m"]:.0f} m'],
                  ["Emergency services", f'{a["nearest_emergency_m"]:.0f} m ({a["emergency_kind"]})'],
                  ["Reading", a["reading"]]]},
        {"title": "5 · Vegetation & Landscaping", "source": "derived",
         "status": im["change_status"] if im["change_status"] != "flag" else "caution",
         "rows": [["Vegetation cover", f'{im["veg_then_pct"]}% -> {im["veg_now_pct"]}%'],
                  ["Trend", "From Sentinel-2 NDVI differencing"]]},
        {"title": "6 · Land-cover change", "source": "derived", "status": im["change_status"],
         "rows": [["Water cover", f'{im["water_then_pct"]}% -> {im["water_now_pct"]}%'],
                  ["Reading", im["reading"]]]},
        {"title": "7 · Utilities & Infrastructure", "source": "partial", "status": "caution",
         "rows": [["Adjacent land use", a["adjacent_landuse"]],
                  ["Mapped utilities", "From OSM; underground lines not mapped — confirm with local authority"]]},
        {"title": "8 · Development Rules & Legal", "source": "offline", "status": "check",
         "rows": [["Title & ownership", "Cannot be checked from satellite"],
                  ["Zoning / land-use class", "Cannot be checked from satellite"],
                  ["Easements & setbacks", "Cannot be checked from satellite"],
                  ["Encumbrance", "Cannot be checked from satellite"]],
         "offline_note": "Satellite data cannot see legal or title status. Verify these with the "
                         "sub-registrar, a property lawyer, and the local planning authority. "
                         "This is the costliest place buyers get caught."},
    ]
    for cat in cats:
        for fl in _category(cat, S):
            story.append(fl)

    # ---- sources + disclaimer ----
    story.append(Spacer(1, 4))
    story.append(Paragraph("SOURCES & LIMITS", S["Eyebrow"]))
    src = result["sources"]
    story.append(Paragraph(
        f'Elevation: {src["dem"]} · Map features: {src["osm"]} · Imagery: {src["imagery"]}.',
        S["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Indicators are derived from public satellite, elevation and map data and are "
        "indicative only. They support your judgment — they are not a guarantee against "
        "flooding, nor a substitute for a site survey, soil test, or legal title check. "
        "Elevation is ~30 m resolution; a single plot spans only a few pixels.", S["Small"]))

    doc.build(story)
    return out_path
