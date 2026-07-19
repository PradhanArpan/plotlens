"""
plotlens.render.change — then-vs-now imagery artifact with quantified change.
"""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

INK = "#1f1d18"; PAPER = "#faf7ef"
STATUS_COL = {"good": "#3f7d4e", "caution": "#b5862b", "flag": "#b5452b"}


def _rgb(scene):
    """Natural-ish composite from R/G/NIR (NIR stands in for blue-ish contrast)."""
    r, g, b = scene.red, scene.green, scene.nir * 0.6
    img = np.dstack([r, g, b])
    return np.clip(img / np.percentile(img, 98), 0, 1)


def render(res, out_path):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5), facecolor=PAPER)

    axes[0].imshow(_rgb(res.then)); axes[0].set_title(f"{res.then.year}", fontsize=11, weight="bold", color=INK)
    axes[1].imshow(_rgb(res.now));  axes[1].set_title(f"{res.now.year}", fontsize=11, weight="bold", color=INK)

    # change panel: water lost (red), veg lost (orange), gained (green)
    water_lost = (res.then.ndwi() > 0.2) & (res.now.ndwi() <= 0.2)
    veg_lost = (res.then.ndvi() > 0.3) & (res.now.ndvi() <= 0.3)
    veg_gain = (res.then.ndvi() <= 0.3) & (res.now.ndvi() > 0.3)
    ch = np.zeros((*water_lost.shape, 3))
    ch[..., :] = 0.92  # paper-ish base
    ch[veg_gain] = [0.25, 0.55, 0.30]
    ch[veg_lost] = [0.80, 0.55, 0.20]
    ch[water_lost] = [0.75, 0.27, 0.17]
    axes[2].imshow(ch); axes[2].set_title("Change (red=water lost, orange=veg lost, green=gained)",
                                          fontsize=9.5, weight="bold", color=INK)
    for ax in axes: ax.axis("off")

    col = STATUS_COL.get(res.change_status, INK)
    nums = (f"Water cover:  {res.water_then_pct:.0f}%  ->  {res.water_now_pct:.0f}%      "
            f"Vegetation:  {res.veg_then_pct:.0f}%  ->  {res.veg_now_pct:.0f}%")
    fig.text(0.5, 0.04, nums, ha="center", va="top", fontsize=11, family="monospace",
             color="#2c2a23", bbox=dict(boxstyle="round,pad=0.5", facecolor="#fff", edgecolor="#e7e1d2"))
    fig.text(0.5, -0.05, f"[{res.change_status.upper()}] {res.reading}", ha="center", va="top",
             fontsize=10, color=col, weight="bold", wrap=True)
    fig.suptitle("PlotLens — what changed here (Sentinel-2 then vs now)",
                 fontsize=12, weight="bold", color=INK, y=1.04)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight", facecolor=PAPER)
    plt.close(fig)
    return out_path
