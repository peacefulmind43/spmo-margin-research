"""Charts for the README, rendered in both light and dark so GitHub can swap them.

Colors come from a validated palette (see the ``PALETTE`` tables): categorical slots
for series identity, and a single-hue ordinal ramp where the series are leverage
levels, because leverage is ordered and an ordered variable should read as one hue
getting stronger rather than as unrelated colors.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import offset_copy

FONT_STACK = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]

PALETTE = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink_secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "typical": "#2a78d6",   # categorical slot 1
        "downside": "#e34948",  # categorical slot 8
        "third": "#1baf7a",     # categorical slot 3
        "second": "#eb6834",    # categorical slot 2
        "band": "#cde2fb",
        "ramp": ["#86b6ef", "#3987e5", "#256abf", "#0d366b"],
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "ink_secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "typical": "#3987e5",
        "downside": "#e66767",
        "third": "#199e70",
        "second": "#d95926",
        "band": "#184f95",
        "ramp": ["#184f95", "#256abf", "#5598e7", "#cde2fb"],
    },
}

PCT = FuncFormatter(lambda v, _: f"{v * 100:.0f}%")


def _apply_theme(mode: str) -> dict[str, str]:
    c = PALETTE[mode]
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": FONT_STACK,
            "figure.facecolor": c["surface"],
            "axes.facecolor": c["surface"],
            "savefig.facecolor": c["surface"],
            "text.color": c["ink"],
            "axes.labelcolor": c["ink_secondary"],
            "axes.edgecolor": c["axis"],
            "xtick.color": c["muted"],
            "ytick.color": c["muted"],
            "xtick.labelcolor": c["ink_secondary"],
            "ytick.labelcolor": c["ink_secondary"],
            "grid.color": c["grid"],
            "grid.linewidth": 0.8,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.frameon": False,
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "figure.dpi": 160,
        }
    )
    return c


def _titled(ax, title: str, subtitle: str, c: dict[str, str]) -> None:
    """Left-aligned title with a muted subtitle stacked beneath it, never overlapping."""
    ax.set_title(title, loc="left", color=c["ink"], pad=24)
    if subtitle:
        trans = offset_copy(ax.transAxes, fig=ax.figure, y=5, units="points")
        ax.text(
            0,
            1.0,
            subtitle,
            transform=trans,
            color=c["muted"],
            fontsize=9,
            va="bottom",
            ha="left",
        )


def _label_series_ends(ax, x, entries, min_gap: float = 0.052) -> None:
    """Right-hand direct labels, nudged apart so converging series stay readable.

    Call only after the axis limits are final -- positions are computed against them.
    """
    lo, hi = ax.get_ylim()
    span = hi - lo or 1.0
    placed: list[float] = []
    for y, text, color in sorted(entries, key=lambda e: e[0]):
        frac = (y - lo) / span
        if placed and frac - placed[-1] < min_gap:
            frac = placed[-1] + min_gap
        placed.append(frac)
        ax.text(
            x,
            lo + frac * span,
            f"  {text}",
            color=color,
            fontsize=9,
            va="center",
            fontweight="bold",
        )


def _finish(fig, out: Path, mode: str) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    path = out.with_name(f"{out.stem}_{mode}{out.suffix}")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    return path


def _both_modes(builder, out: Path) -> list[Path]:
    paths = []
    for mode in ("light", "dark"):
        c = _apply_theme(mode)
        fig = builder(c)
        paths.append(_finish(fig, out, mode))
    return paths


def plot_growth_and_downside(table: pd.DataFrame, out: Path) -> list[Path]:
    """The headline: median growth keeps climbing, the 5th percentile does not."""
    lev = table.index.to_numpy(float)

    def build(c):
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(7.4, 7.6), sharex=True, height_ratios=[1.15, 1]
        )

        ax1.fill_between(
            lev, table.cagr_p05, table.cagr_p95, color=c["band"], alpha=0.45, lw=0
        )
        ax1.plot(lev, table.cagr_median, color=c["typical"], lw=2.0)
        ax1.plot(lev, table.cagr_p05, color=c["downside"], lw=2.0)

        # The peak's exact location moves with the bootstrap seed (roughly 1.0x-1.3x),
        # so the chart marks the flat region rather than claiming a precise argmax.
        flat = (lev >= 1.0) & (lev <= 1.5)
        ax1.plot(
            lev[flat],
            table.cagr_p05.to_numpy()[flat],
            color=c["downside"],
            lw=4.5,
            alpha=0.30,
            solid_capstyle="round",
        )
        ax1.annotate(
            "flat to about 1.5x,\nthen falls away",
            xy=(1.25, float(table.cagr_p05.loc[1.25])),
            xytext=(6, -52),
            textcoords="offset points",
            color=c["ink_secondary"],
            fontsize=9,
            arrowprops=dict(arrowstyle="-", color=c["axis"], lw=1),
        )
        ax1.text(
            lev[-1],
            table.cagr_median.iloc[-1],
            "  median",
            color=c["typical"],
            fontsize=9,
            va="center",
            fontweight="bold",
        )
        ax1.text(
            lev[-1],
            table.cagr_p05.iloc[-1],
            "  5th pct",
            color=c["downside"],
            fontsize=9,
            va="center",
            fontweight="bold",
        )
        ax1.axhline(0, color=c["axis"], lw=1)
        ax1.set_ylabel("10-year CAGR")
        ax1.yaxis.set_major_formatter(PCT)
        _titled(
            ax1,
            "More margin buys a better median and a worse floor",
            "shaded band = 5th to 95th percentile of bootstrapped 10-year outcomes",
            c,
        )

        ax2.plot(lev, table.median_max_drawdown, color=c["typical"], lw=2.0)
        ax2.plot(lev, table.worst_5pct_max_drawdown, color=c["downside"], lw=2.0)
        ax2.text(
            lev[-1],
            table.median_max_drawdown.iloc[-1],
            "  median",
            color=c["typical"],
            fontsize=9,
            va="center",
            fontweight="bold",
        )
        ax2.text(
            lev[-1],
            table.worst_5pct_max_drawdown.iloc[-1],
            "  worst 5%",
            color=c["downside"],
            fontsize=9,
            va="center",
            fontweight="bold",
        )
        ax2.set_ylabel("Maximum drawdown")
        ax2.set_xlabel("Target leverage (position value / equity)")
        ax2.yaxis.set_major_formatter(PCT)
        _titled(
            ax2,
            "What you have to sit through to collect it",
            "deepest peak-to-trough loss of account equity over the same paths",
            c,
        )

        for ax in (ax1, ax2):
            ax.set_xlim(lev[0], lev[-1] + 0.28)
            ax.set_axisbelow(True)
        fig.tight_layout()
        return fig

    return _both_modes(build, out)


def plot_equity_curves(
    dates: pd.DatetimeIndex,
    curves: dict[float, np.ndarray],
    out: Path,
    events: tuple[tuple[str, str, str], ...] = (
        ("2000-03-24", "2002-10-09", "dot-com"),
        ("2007-10-09", "2009-03-09", "GFC"),
    ),
) -> list[Path]:
    """Log-scale equity curves, with the bear markets marked."""
    levels = sorted(curves)

    def build(c):
        fig, ax = plt.subplots(figsize=(7.4, 4.9))
        ramp = c["ramp"]

        for start, end, label in events:
            x0, x1 = pd.Timestamp(start), pd.Timestamp(end)
            ax.axvspan(x0, x1, color=c["grid"], alpha=0.55, lw=0)
            ax.text(
                x0 + (x1 - x0) / 2,
                0.965,
                label,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                color=c["muted"],
                fontsize=8,
            )

        deepest = None
        for i, lev in enumerate(levels):
            eq = np.asarray(curves[lev], dtype=float)
            y = np.where(eq > 0, eq / eq[0], np.nan)
            color = ramp[min(i, len(ramp) - 1)]
            ax.plot(dates, y, color=color, lw=2.0)
            last = int(np.nanmax(np.where(np.isfinite(y))[0]))
            ax.text(
                dates[last],
                y[last],
                f"  {lev:g}x",
                color=color,
                fontsize=9,
                va="center",
                fontweight="bold",
            )
            trough = int(np.nanargmin(y / np.maximum.accumulate(y)))
            depth = float(y[trough] / np.maximum.accumulate(y)[trough] - 1.0)
            if lev == levels[-1]:
                deepest = (dates[trough], y[trough], depth, color)

        if deepest is not None:
            when, value, depth, color = deepest
            ax.annotate(
                f"{levels[-1]:g}x drawdown {depth:.0%}\n({when:%b %Y})",
                xy=(when, value),
                xytext=(18, -34),
                textcoords="offset points",
                color=color,
                fontsize=9,
                fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=c["axis"], lw=1),
            )

        ax.set_yscale("log")
        ax.set_ylabel("Growth of $1 (log scale)")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}x"))
        _titled(
            ax,
            "Over 33 years leverage wins - if you never once sold",
            "SPMO extended back to 1993 via its SPY beta; monthly rebalance, IBKR tiered financing",
            c,
        )
        ax.set_axisbelow(True)
        ax.margins(x=0.06)
        fig.tight_layout()
        return fig

    return _both_modes(build, out)


def plot_leverage_vs_saving(
    table: pd.DataFrame,
    out: Path,
) -> list[Path]:
    """Median and 5th-percentile wealth vs leverage, one line per savings rate.

    Each series is indexed to its own value at 1.0x, so the panels compare the
    *shape* of the leverage response rather than the size of the account.
    """
    levels = sorted(table.columns)
    rates = list(table.index.get_level_values("contribution_rate").unique())

    def build(c):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.4, 7.6), sharex=True)
        ramp = c["ramp"]

        for ax, stat, title, subtitle in [
            (
                ax1,
                "median",
                "In the middle of the distribution, leverage pays",
                "terminal wealth relative to the same savings rate held unlevered",
            ),
            (
                ax2,
                "p05",
                "In the bad 5% of decades, leverage only ever costs",
                "saving harder softens the penalty but never turns it into a gain",
            ),
        ]:
            entries = []
            for i, rate in enumerate(rates):
                row = table.loc[(stat, rate)]
                y = row / row[1.0]
                color = ramp[min(i, len(ramp) - 1)]
                ax.plot(levels, [y[l] for l in levels], color=color, lw=2.0)
                label = "no saving" if rate == 0 else f"+{rate:.0%}/yr"
                entries.append((y[levels[-1]], label, color))
            ax.axhline(1.0, color=c["axis"], lw=1)
            ax.set_ylabel("Terminal wealth vs unlevered")
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}x"))
            _titled(ax, title, subtitle, c)
            ax.set_xlim(levels[0], levels[-1] + 0.46)
            ax.set_axisbelow(True)
            _label_series_ends(ax, levels[-1], entries)

        ax2.set_xlabel("Target leverage (constant, monthly rebalance)")
        fig.tight_layout()
        return fig

    return _both_modes(build, out)


def plot_kelly_curves(
    grids: dict[str, tuple[np.ndarray, np.ndarray]],
    out: Path,
) -> list[Path]:
    """Log-growth against leverage under three drift assumptions."""

    def build(c):
        fig, ax = plt.subplots(figsize=(7.4, 4.9))
        colors = [c["typical"], c["second"], c["third"]]

        for (label, (grid, growth)), color in zip(grids.items(), colors):
            ax.plot(grid, growth, color=color, lw=2.0)
            peak = int(np.nanargmax(growth))
            ax.plot(
                grid[peak],
                growth[peak],
                "o",
                ms=8,
                color=color,
                mec=c["surface"],
                mew=2,
            )
            ax.annotate(
                f"{label}\npeak {grid[peak]:.2f}x",
                xy=(grid[peak], growth[peak]),
                xytext=(6, 12),
                textcoords="offset points",
                color=color,
                fontsize=9,
                fontweight="bold",
            )

        ax.axhline(0, color=c["axis"], lw=1)
        ax.axvline(4.0, color=c["axis"], lw=1)
        ax.text(
            3.94,
            0.02,
            "Reg-T maintenance ceiling ",
            transform=ax.get_xaxis_transform(),
            rotation=90,
            ha="right",
            va="bottom",
            color=c["muted"],
            fontsize=8,
        )
        ax.set_xlabel("Leverage")
        ax.set_ylabel("Annualised log growth")
        ax.yaxis.set_major_formatter(PCT)
        _titled(
            ax,
            "The growth peak moves a whole turn of leverage on the drift assumption",
            "same maths, three estimates of momentum's edge - and every peak is flat on top",
            c,
        )
        ax.set_axisbelow(True)
        ax.set_xlim(-0.05, 4.55)
        top = max(np.nanmax(g) for _, g in grids.values())
        ax.set_ylim(top=top * 1.20)
        fig.tight_layout()
        return fig

    return _both_modes(build, out)
