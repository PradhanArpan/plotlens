"""
plotlens.render.artifact — turn a TerrainResult into the shareable image.
matplotlib only. Mirrors the prototype the user approved.
"""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
import numpy as np

INK = "#1f1d18"; PAPER = "#faf7ef"; RED = "#b5452b"
STATUS_COL = {"good": "#3f7d4e", "caution": "#b5862b", "flag": "#b5452b"}


def render(tile, res, out_path: str):
    z = np.nan_to_num(tile.z, nan=np.nanmean(tile.z))
    x0, y0, x1, y1 = res.plot_box
    n = z.shape[0]
    yy, xx = np.mgrid[0:n, 0:n]

    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), facecolor=PAPER)
    ls = LightSource(azdeg=315, altdeg=45)

    # A: contours + drainage arrows
    ax = axes[0]
    ax.imshow(ls.hillshade(z, vert_exag=3), cmap="gray", alpha=0.55)
    cs = ax.contour(z, levels=res.contour_levels, colors="#5a4a2a", linewidths=0.8, alpha=0.9)
    ax.clabel(cs, inline=True, fontsize=7, fmt="%d m")
    step = max(4, n // 13)
    ax.quiver(xx[::step, ::step], yy[::step, ::step],
              res.grad_x[::step, ::step], res.grad_y[::step, ::step],
              color="#2f6db5", scale=40, width=0.004, alpha=0.8)
    _plot_rect(ax, x0, y0, x1, y1)
    ax.set_title("Contours + drainage direction", fontsize=11, weight="bold", color=INK)
    ax.axis("off")

    # B: flow accumulation
    ax = axes[1]
    ax.imshow(res.flow_log, cmap="YlGnBu")
    _plot_rect(ax, x0, y0, x1, y1)
    ax.set_title("Water flow accumulation (blue = water collects)", fontsize=11, weight="bold", color=INK)
    ax.axis("off")

    col = STATUS_COL.get(res.water_status, INK)
    stats = (f"Plot mean elevation:    {res.plot_mean_elev:6.1f} m\n"
             f"Lower than surroundings: {res.rel_to_surroundings:5.1f} m\n"
             f"Mean slope across plot:  {res.mean_slope_pct:5.1f} %\n"
             f"Water-collection index:  {res.flow_ratio:5.1f}x area average\n"
             f"Drainage bearing:        {res.drainage_bearing:5.0f}deg\n"
             f"Source: {tile.source}")
    fig.text(0.5, -0.04, stats, ha="center", va="top", fontsize=10, family="monospace",
             color="#2c2a23", bbox=dict(boxstyle="round,pad=0.6", facecolor="#fff", edgecolor="#e7e1d2"))
    fig.text(0.5, -0.20, f"[{res.water_status.upper()}]  {res.reading}", ha="center", va="top",
             fontsize=10.5, color=col, weight="bold", wrap=True)
    fig.suptitle("PlotLens — computed terrain analysis", fontsize=12, weight="bold", color=INK, y=1.02)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)
    return out_path


def _plot_rect(ax, x0, y0, x1, y1):
    ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor=RED, linewidth=2.5))
    ax.text((x0 + x1) / 2, y0 - 3, "YOUR PLOT", color=RED, fontsize=9, weight="bold", ha="center")
