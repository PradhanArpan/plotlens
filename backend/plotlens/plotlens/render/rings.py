"""
plotlens.render.rings — the distance-rings artifact.

Plot at centre, concentric distance rings, OSM roads/water/land use/POIs drawn in
metres-relative space. The computed visual for Circulation & Access.
"""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon
import numpy as np

INK = "#1f1d18"; PAPER = "#faf7ef"; RED = "#b5452b"
COL = {"road": "#6b6657", "water": "#2f6db5", "landuse": "#cdd6c0", "poi": "#b5862b"}
STATUS_COL = {"good": "#3f7d4e", "caution": "#b5862b", "flag": "#b5452b"}
RINGS = [250, 500, 1000, 2000]   # metres


def render(osm, acc, out_path):
    h = osm.span_m / 2
    fig, ax = plt.subplots(figsize=(7.6, 7.6), facecolor=PAPER)
    ax.set_facecolor(PAPER)

    # land use polygons (under everything)
    for f in osm.of("landuse"):
        xs = [c[0] for c in f.coords]; ys = [c[1] for c in f.coords]
        ax.add_patch(Polygon(list(zip(xs, ys)), closed=True, facecolor=COL["landuse"],
                             edgecolor="none", alpha=0.5, zorder=1))

    # distance rings
    for r in RINGS:
        if r <= h:
            ax.add_patch(Circle((0, 0), r, fill=False, edgecolor="#d8d2c2", linewidth=1, zorder=2))
            ax.text(0, r, f"{r} m" if r < 1000 else f"{r/1000:.0f} km",
                    fontsize=8, color="#a39e8f", ha="center", va="bottom", zorder=2)

    # roads
    for f in osm.of("road"):
        xs = [c[0] for c in f.coords]; ys = [c[1] for c in f.coords]
        ax.plot(xs, ys, color=COL["road"], linewidth=2, zorder=3)
    # water
    for f in osm.of("water"):
        xs = [c[0] for c in f.coords]; ys = [c[1] for c in f.coords]
        if len(f.coords) > 4 and f.subtype in ("pond", "lake", "water"):
            ax.add_patch(Polygon(list(zip(xs, ys)), closed=True, facecolor=COL["water"],
                                 edgecolor="none", alpha=0.6, zorder=3))
        else:
            ax.plot(xs, ys, color=COL["water"], linewidth=2.5, zorder=3)
    # POIs
    for f in osm.of("poi"):
        x, y = f.coords[0]
        ax.scatter([x], [y], c=COL["poi"], s=40, zorder=4, edgecolors="white", linewidths=1)
        ax.annotate(f.subtype.replace("_", " "), (x, y), fontsize=7.5, color="#7a6420",
                    xytext=(5, 5), textcoords="offset points", zorder=4)

    # the plot
    ax.scatter([0], [0], c=RED, s=120, marker="s", zorder=5, edgecolors="white", linewidths=1.5)
    ax.annotate("YOUR PLOT", (0, 0), fontsize=9, color=RED, weight="bold",
                xytext=(8, 8), textcoords="offset points", zorder=5)

    ax.set_xlim(-h, h); ax.set_ylim(-h, h)
    ax.set_aspect("equal"); ax.axis("off")

    col = STATUS_COL.get(acc.access_status, INK)
    summary = (f"Nearest road:   {acc.nearest_road_m:.0f} m  ({acc.nearest_road_name})\n"
               f"Nearest water:  {acc.nearest_water_m:.0f} m  ({acc.nearest_water_name})\n"
               f"Transit:        {acc.nearest_transit_m:.0f} m\n"
               f"Emergency:      {acc.nearest_emergency_m:.0f} m  ({acc.emergency_kind})\n"
               f"Adjacent use:   {acc.adjacent_landuse}\n"
               f"OSM coverage:   {acc.coverage}")
    fig.text(0.5, 0.02, summary, ha="center", va="top", fontsize=9, family="monospace",
             color="#2c2a23", bbox=dict(boxstyle="round,pad=0.5", facecolor="#fff", edgecolor="#e7e1d2"))
    fig.text(0.5, -0.13, f"[{acc.access_status.upper()}] {acc.reading}", ha="center", va="top",
             fontsize=9.5, color=col, weight="bold", wrap=True)
    ax.set_title("PlotLens — access & surroundings", fontsize=12, weight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)
    return out_path
