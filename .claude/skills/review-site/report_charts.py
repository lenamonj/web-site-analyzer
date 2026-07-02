#!/usr/bin/env python3
"""
Trend chart renderer for the executive report.

Draws the quarterly trend PNGs the report embeds: overall score, per-category
score small multiples, and key page metrics. Single-hue navy lines with a
gold current-quarter marker, hairline grid, endpoint-only labels; a None
quarter breaks the line (a gap, never an interpolation). Kept separate from
build_exec_report so matplotlib is only needed when a report actually has a
trend to draw; the scanner suite under tools/ stays stdlib-only.

Dependency:
    pip install matplotlib
"""

import math
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

# The report's design tokens (see build_exec_report.py). Lines carry the
# accent; text stays in ink/muted, never the data color.
NAVY = "#0B1F3A"
GOLD = "#C9A227"
INK = "#262B33"
MUTED = "#5A6672"
HAIRLINE = "#D8DEE9"
SANS = ["Calibri", "DejaVu Sans"]

METRIC_PANELS = [
    ("median_lcp_ms", "Median LCP (ms)", lambda v: f"{v:,.0f}"),
    ("median_weight_kb", "Median page weight (KB)", lambda v: f"{v:,.0f}"),
    ("broken_links", "Broken links", lambda v: f"{v:.0f}"),
]


def drawable(values):
    """A line needs at least two measured points; one point is a dot, not a
    trend, and zero is nothing."""
    return bool(values) and sum(v is not None for v in values) >= 2


def metric_panels(series):
    return [(key, title, fmt) for key, title, fmt in METRIC_PANELS
            if drawable(series.get(key))]


def _last_point(values):
    for i in range(len(values) - 1, -1, -1):
        if values[i] is not None:
            return i, values[i]
    return None


def _plot_series(ax, values, linewidth=2, markersize=7, endpoint_size=9):
    xs = list(range(len(values)))
    ys = [math.nan if v is None else v for v in values]
    ax.plot(xs, ys, color=NAVY, linewidth=linewidth,
            solid_joinstyle="round", solid_capstyle="round",
            marker="o", markersize=markersize, markerfacecolor=NAVY,
            markeredgecolor="white", markeredgewidth=1.5)
    last = _last_point(values)
    if last is not None:
        ax.plot([last[0]], [last[1]], marker="o", markersize=endpoint_size,
                color=GOLD, markeredgecolor="white", markeredgewidth=1.5,
                zorder=5)


def _style_axis(ax):
    ax.tick_params(axis="both", length=0, labelsize=8, labelcolor=MUTED)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(HAIRLINE)
    ax.grid(axis="y", color=HAIRLINE, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)


def _quarter_ticks(ax, quarters, full=True, fontsize=8):
    if full:
        ax.set_xticks(range(len(quarters)))
        ax.set_xticklabels(quarters, fontsize=fontsize, color=MUTED)
    else:
        # Narrow panels: first and last quarter only, so labels never collide.
        ax.set_xticks([0, len(quarters) - 1])
        ax.set_xticklabels([quarters[0], quarters[-1]],
                           fontsize=fontsize, color=MUTED)
    ax.set_xlim(-0.35, len(quarters) - 0.65)


def _label_endpoint(ax, values, fmt, fontsize=8.5):
    last = _last_point(values)
    if last is not None:
        ax.annotate(fmt(last[1]), (last[0], last[1]),
                    textcoords="offset points", xytext=(0, 9), ha="center",
                    fontsize=fontsize, color=INK, fontweight="bold")


def _save(fig, path):
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def render_trend_charts(trend, out_dir, prefix):
    """Render the report's trend PNGs; returns {'caption','path'} dicts in
    embed order. Only series with at least two measured quarters draw."""
    if not HAVE_MPL:
        raise RuntimeError("matplotlib is required to draw the trend charts "
                           "in this report: pip install matplotlib")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = SANS
    quarters = trend["quarters"]
    series = trend.get("series") or {}
    charts = []

    overall = series.get("overall_score")
    if drawable(overall):
        fig, ax = plt.subplots(figsize=(6.8, 2.2))
        _plot_series(ax, overall)
        _style_axis(ax)
        _quarter_ticks(ax, quarters)
        ax.set_ylim(0, 1.08)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
        _label_endpoint(ax, overall, lambda v: f"{v:.2f}")
        path = out_dir / f"{prefix}_trend_overall.png"
        _save(fig, path)
        charts.append({"caption": "Overall measured score by quarter "
                                  "(0 to 1; higher is better).",
                       "path": str(path)})

    cats = [k for k in series
            if k.endswith("_score") and k != "overall_score"
            and drawable(series[k])]
    if cats:
        cols = min(4, len(cats))
        rows = -(-len(cats) // cols)
        fig, axes = plt.subplots(rows, cols,
                                 figsize=(6.8, 1.45 * rows + 0.3),
                                 squeeze=False)
        for i, key in enumerate(cats):
            ax = axes[i // cols][i % cols]
            _plot_series(ax, series[key], markersize=4, endpoint_size=6)
            _style_axis(ax)
            ax.set_title(key[:-len("_score")], fontsize=8.5, color=INK, pad=3)
            ax.set_ylim(0, 1.08)
            ax.set_yticks([0, 1])
            if i // cols == rows - 1:
                _quarter_ticks(ax, quarters, full=False, fontsize=6.5)
            else:
                ax.set_xticks([])
                ax.set_xlim(-0.35, len(quarters) - 0.65)
        for j in range(len(cats), rows * cols):
            axes[j // cols][j % cols].axis("off")
        fig.tight_layout()
        path = out_dir / f"{prefix}_trend_categories.png"
        _save(fig, path)
        charts.append({"caption": "Category scores by quarter "
                                  "(shared 0 to 1 scale).",
                       "path": str(path)})

    panels = metric_panels(series)
    if panels:
        fig, axes = plt.subplots(1, len(panels), figsize=(6.8, 2.0),
                                 squeeze=False)
        for ax, (key, title, fmt) in zip(axes[0], panels):
            _plot_series(ax, series[key], markersize=5, endpoint_size=7)
            _style_axis(ax)
            ax.set_title(title, fontsize=8.5, color=INK, pad=3)
            _quarter_ticks(ax, quarters, full=False, fontsize=6.5)
            ax.set_ylim(bottom=0)
            _label_endpoint(ax, series[key], fmt, fontsize=8)
        fig.tight_layout()
        path = out_dir / f"{prefix}_trend_metrics.png"
        _save(fig, path)
        charts.append({"caption": "Key page metrics by quarter (site "
                                  "medians; a gap is a quarter where the "
                                  "metric was not captured).",
                       "path": str(path)})

    return charts
