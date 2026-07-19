"""
plotlens.engine.terrain — the compute moat.

Pure numpy/scipy. Takes a DEMTile, returns site-specific metrics and the arrays
needed to render the artifacts. No I/O, no network, no source-specific code.

Honesty notes (important, read before changing thresholds):

1. SCALE. The analysis box is a fraction of the DEM window — with the default
   3600 m window that is a ~576 m square. At COP30's ~30 m native resolution a
   real 30x40 ft plot is a fraction of ONE pixel. These are therefore SITE
   VICINITY metrics, not plot-boundary metrics, and the wording of every
   reading reflects that. Do not relabel them as plot-specific.

2. SIGN CONVENTION. rel_to_surroundings is POSITIVE when the site sits LOWER
   than the ring of land around it (i.e. positive = in a dip = worse). This is
   the opposite of the intuitive reading, so every string that mentions it
   states the direction in words rather than relying on the sign.

3. FLOW METRICS. D8 accumulation is heavily right-skewed: a few channel cells
   carry very large values while most cells sit near 1. Comparing means (the
   previous approach) produced a number that barely moved between completely
   different terrains. We instead use percentile-based measures, which are
   scale-free and actually discriminate.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import numpy as np


@dataclass
class TerrainResult:
    # site-specific scalars
    plot_mean_elev: float
    rel_to_surroundings: float     # +ve = site sits LOWER than surroundings
    rel_direction: str             # "below" | "above" | "level with"
    mean_slope_pct: float
    flow_ratio: float              # site flow concentration vs typical ground
    flow_percentile: float         # where site flow sits in the window (0-100)
    drainage_bearing: float        # compass degrees water leaves the site
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


def _surrounding_ring(z, x0, y0, x1, y1, n):
    """
    Mean elevation of the land AROUND the site, excluding the site itself.

    The previous version took a padded box that CONTAINED the site box, so site
    cells were counted on both sides of the comparison. That pulled every
    result toward zero and understated real dips and rises.
    """
    pad = (x1 - x0)
    sy0, sy1 = max(0, y0 - pad), min(n, y1 + pad)
    sx0, sx1 = max(0, x0 - pad), min(n, x1 + pad)

    outer = z[sy0:sy1, sx0:sx1]
    mask = np.ones(outer.shape, dtype=bool)
    # punch out the site box (coordinates relative to the outer window)
    mask[y0 - sy0:y1 - sy0, x0 - sx0:x1 - sx0] = False
    ring = outer[mask]
    if ring.size == 0:            # degenerate tiny grid
        return float(np.nanmean(outer))
    return float(np.nanmean(ring))


def analyse(tile) -> TerrainResult:
    z = tile.z
    n = z.shape[0]
    x0, y0, x1, y1 = _plot_box(n)

    plot = z[y0:y1, x0:x1]
    plot_mean = float(np.nanmean(plot))
    ring_mean = _surrounding_ring(z, x0, y0, x1, y1, n)
    rel = ring_mean - plot_mean                    # +ve => site is lower

    if rel > 0.5:
        rel_dir = "below"
    elif rel < -0.5:
        rel_dir = "above"
    else:
        rel_dir = "level with"

    gy, gx = np.gradient(z)
    slope_pct = float(
        np.nanmean(np.hypot(gx[y0:y1, x0:x1], gy[y0:y1, x0:x1])) / tile.res_m * 100)

    acc = d8_flow_accumulation(z)
    site_acc = acc[y0:y1, x0:x1]

    # Percentile-based flow metrics (see honesty note 3 at top of file).
    # We characterise the site by its 90th percentile accumulation: the wettest
    # part of the site, without letting a single freak cell dominate.
    site_p90 = float(np.percentile(site_acc, 90))
    grid_median = float(np.median(acc))
    flow_ratio = site_p90 / grid_median if grid_median > 0 else 0.0

    # Where does that sit in the distribution of the whole window? Scale-free,
    # and directly interpretable: "wetter than X% of the surrounding ground".
    flow_percentile = float((acc < site_p90).mean() * 100)

    # drainage bearing: mean downhill direction across the site, as compass deg.
    # NOTE: verify against the rendered arrows in render/artifact.py before
    # relying on this in user-facing copy — array row order vs compass north is
    # easy to get inverted and has not been checked against a known slope.
    dx, dy = float(np.mean(gx[y0:y1, x0:x1])), float(np.mean(gy[y0:y1, x0:x1]))
    bearing = (np.degrees(np.arctan2(-dx, dy)) + 360) % 360

    status, reading = _classify(rel, rel_dir, slope_pct, flow_percentile)

    levels = list(np.linspace(np.nanmin(z), np.nanmax(z), 12))
    return TerrainResult(
        plot_mean_elev=round(plot_mean, 1),
        rel_to_surroundings=round(rel, 1),
        rel_direction=rel_dir,
        mean_slope_pct=round(slope_pct, 1),
        flow_ratio=round(flow_ratio, 2),
        flow_percentile=round(flow_percentile, 1),
        drainage_bearing=round(bearing, 0),
        contour_levels=levels,
        flow_log=np.log10(acc),
        grad_x=-gx, grad_y=-gy,
        plot_box=(x0, y0, x1, y1),
        water_status=status,
        reading=reading,
    )


def _classify(rel, rel_dir, slope_pct, flow_percentile):
    """
    Transparent thresholds. Each metric contributes; the total decides status.

    The reading is BUILT FROM the same numbers that drive the score, so the
    prose can never contradict the figures shown beside it. Previously the text
    was written independently and could disagree with the data.
    """
    score = 0
    concerns = []
    positives = []

    # --- relative elevation ---
    if rel > 2:
        score += 2
        concerns.append(f"sits about {abs(rel):.1f} m below the surrounding land")
    elif rel > 0.5:
        score += 1
        concerns.append(f"sits slightly below the surrounding land ({abs(rel):.1f} m)")
    elif rel < -0.5:
        positives.append(f"sits about {abs(rel):.1f} m above the surrounding land")

    # --- slope ---
    if slope_pct < 1:
        score += 2
        concerns.append(f"is very flat ({slope_pct:.1f}% slope), so surface water clears slowly")
    elif slope_pct < 2:
        score += 1
        concerns.append(f"has limited fall ({slope_pct:.1f}% slope)")
    else:
        positives.append(f"has usable fall ({slope_pct:.1f}% slope)")

    # --- flow convergence ---
    if flow_percentile >= 99:
        score += 2
        concerns.append(
            f"lies on a drainage path carrying more water than {flow_percentile:.0f}% "
            "of the surrounding ground")
    elif flow_percentile >= 95:
        score += 1
        concerns.append(
            f"collects more runoff than {flow_percentile:.0f}% of the surrounding ground")
    else:
        positives.append("is not on a significant drainage path")

    caveat = ("Based on a ~30 m elevation model over the site vicinity, not a "
              "surveyed plot boundary. Confirm on the ground, ideally in monsoon.")

    if score >= 5:
        status = "flag"
    elif score >= 3:
        status = "caution"
    else:
        status = "good"

    if concerns:
        body = "This site " + "; ".join(concerns) + "."
        if positives:
            body += " On the positive side, it " + "; ".join(positives) + "."
    else:
        body = "This site " + "; ".join(positives) + "." if positives else \
            "No drainage concerns were detected in the elevation model."

    return status, f"{body} {caveat}"
