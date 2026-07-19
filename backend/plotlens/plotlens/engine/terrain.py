"""
plotlens.engine.terrain — the compute moat.

Pure numpy/scipy. Takes a DEMTile, returns plot-specific metrics and the arrays
needed to render the artifacts. No I/O, no network, no source-specific code:
this is what an LLM prompt cannot reproduce because it requires the actual
elevation grid for the polygon.

Everything here runs in this sandbox today.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np


@dataclass
class TerrainResult:
    # plot-specific scalars (the believable numbers)
    plot_mean_elev: float
    rel_to_surroundings: float     # +ve = plot sits LOWER than its surroundings
    mean_slope_pct: float
    flow_ratio: float              # water passing through plot vs area average
    drainage_bearing: float        # compass degrees water leaves the plot
    # arrays for rendering
    contour_levels: list
    flow_log: np.ndarray
    grad_x: np.ndarray
    grad_y: np.ndarray
    plot_box: tuple                # (x0,y0,x1,y1) in grid coords
    # interpretation
    water_status: str              # good | caution | flag
    reading: str

    def scalars(self) -> dict:
        return {k: v for k, v in asdict(self).items()
                if isinstance(v, (int, float, str))}


def _plot_box(n: int, frac: float = 0.16) -> tuple:
    half = max(3, int(n * frac / 2))
    c = n // 2
    return (c - half, c - half, c + half, c + half)


def d8_flow_accumulation(z: np.ndarray) -> np.ndarray:
    """Standard D8 single-flow-direction accumulation. Each cell drains to its
    steepest-descent neighbour; accumulation counts upslope contributing cells.
    O(n^2 log n) via elevation-sorted processing."""
    z = np.nan_to_num(z, nan=np.nanmean(z))
    n = z.shape[0]
    nbrs = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    dist = np.array([np.sqrt(2), 1, np.sqrt(2), 1, 1, np.sqrt(2), 1, np.sqrt(2)])
    rec = -np.ones(n * n, dtype=np.int64)
    for i in range(n):
        for j in range(n):
            best, bk = 0.0, -1
            here = z[i, j]
            for k, (di, dj) in enumerate(nbrs):
                ni, nj = i + di, j + dj
                if 0 <= ni < n and 0 <= nj < n:
                    s = (here - z[ni, nj]) / dist[k]
                    if s > best:
                        best, bk = s, ni * n + nj
            rec[i * n + j] = bk
    acc = np.ones(n * n)
    for c in np.argsort(-z.ravel()):
        r = rec[c]
        if r >= 0:
            acc[r] += acc[c]
    return acc.reshape(n, n)


def analyse(tile) -> TerrainResult:
    z = tile.z
    n = z.shape[0]
    x0, y0, x1, y1 = _plot_box(n)

    plot = z[y0:y1, x0:x1]
    pad = (x1 - x0)
    sy0, sy1 = max(0, y0 - pad), min(n, y1 + pad)
    sx0, sx1 = max(0, x0 - pad), min(n, x1 + pad)
    surround = z[sy0:sy1, sx0:sx1]

    plot_mean = float(np.nanmean(plot))
    rel = float(np.nanmean(surround) - plot_mean)          # +ve => plot is lower
    gy, gx = np.gradient(z)
    slope_pct = float(np.nanmean(np.hypot(gx[y0:y1, x0:x1], gy[y0:y1, x0:x1])) / tile.res_m * 100)

    acc = d8_flow_accumulation(z)
    flow_ratio = float(acc[y0:y1, x0:x1].mean() / acc.mean())

    # drainage bearing: mean downhill direction across the plot, as compass deg
    dx, dy = float(np.mean(gx[y0:y1, x0:x1])), float(np.mean(gy[y0:y1, x0:x1]))
    bearing = (np.degrees(np.arctan2(-dx, dy)) + 360) % 360  # water flows downhill

    # transparent rule-based status (auditable, not a black box)
    status, reading = _classify(rel, slope_pct, flow_ratio)

    levels = list(np.linspace(np.nanmin(z), np.nanmax(z), 12))
    return TerrainResult(
        plot_mean_elev=round(plot_mean, 1),
        rel_to_surroundings=round(rel, 1),
        mean_slope_pct=round(slope_pct, 1),
        flow_ratio=round(flow_ratio, 1),
        drainage_bearing=round(bearing, 0),
        contour_levels=levels,
        flow_log=np.log10(acc),
        grad_x=-gx, grad_y=-gy,
        plot_box=(x0, y0, x1, y1),
        water_status=status,
        reading=reading,
    )


def _classify(rel, slope_pct, flow_ratio):
    """Transparent thresholds. Each metric contributes; worst dominates.
    These are deliberately conservative and tunable, not ML."""
    score = 0
    if rel > 2: score += 2          # sits in a dip
    elif rel > 0.5: score += 1
    if slope_pct < 1: score += 2     # too flat to drain
    elif slope_pct < 2: score += 1
    if flow_ratio > 4: score += 2    # water converges here
    elif flow_ratio > 2: score += 1

    if score >= 5:
        return "flag", ("Low pocket with poor slope and converging water flow — "
                        "strong drainage/flood caution. Verify with a site visit in monsoon.")
    if score >= 3:
        return "caution", ("Sits lower than surroundings and/or drains slowly — "
                           "check drainage and soil before committing.")
    return "good", ("Elevated and/or well-drained relative to surroundings on the "
                    "elevation model. Still confirm on the ground.")
