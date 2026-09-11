"""Turning the sweep into an answer under different definitions of "best".

"Optimal" is not one number, it is a choice of objective:

``growth``
    Maximise median or expected compound growth. This is Kelly. It is correct only
    if the estimated drift is correct, and drift is the hardest thing to estimate.
``robust``
    Maximise a lower percentile of outcomes. Answers "what leverage leaves me best
    off if the next decade disappoints" instead of "if it repeats".
``drawdown_budget``
    Take the largest leverage whose drawdown stays inside a limit you can actually
    sit through. The binding constraint for most people is behavioural, not
    mathematical: the optimal leverage you abandon at the bottom is worse than a
    smaller one you keep.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _interpolate_argmax(x: np.ndarray, y: np.ndarray) -> float:
    """Peak of a parabola through the best grid point and its two neighbours."""
    i = int(np.nanargmax(y))
    if i == 0 or i == len(x) - 1:
        return float(x[i])
    denom = y[i - 1] - 2 * y[i] + y[i + 1]
    if denom == 0:
        return float(x[i])
    shift = 0.5 * (y[i - 1] - y[i + 1]) / denom
    return float(x[i] + shift * (x[i + 1] - x[i]))


def growth_optimal(bootstrap_table: pd.DataFrame, column: str = "cagr_median") -> float:
    """Leverage maximising a central-tendency growth measure."""
    return _interpolate_argmax(
        bootstrap_table.index.to_numpy(float), bootstrap_table[column].to_numpy(float)
    )


def robust_optimal(bootstrap_table: pd.DataFrame, column: str = "cagr_p05") -> float:
    """Leverage maximising a lower percentile of the outcome distribution."""
    return _interpolate_argmax(
        bootstrap_table.index.to_numpy(float), bootstrap_table[column].to_numpy(float)
    )


def drawdown_budget(
    table: pd.DataFrame,
    limit: float,
    column: str = "median_max_drawdown",
) -> float:
    """Largest leverage whose drawdown measure stays within ``limit`` (e.g. -0.35).

    Linearly interpolates between grid points, so a budget of -35% can land at 1.18x
    rather than being rounded to whichever level happened to be simulated.
    """
    lev = table.index.to_numpy(float)
    dd = table[column].to_numpy(float)
    order = np.argsort(lev)
    lev, dd = lev[order], dd[order]

    ok = dd >= limit  # drawdowns are negative; >= limit means shallower than budget
    if not ok.any():
        return float("nan")
    if ok.all():
        return float(lev[-1])
    last = int(np.where(ok)[0].max())
    if last == len(lev) - 1:
        return float(lev[-1])
    x0, x1 = lev[last], lev[last + 1]
    y0, y1 = dd[last], dd[last + 1]
    if y0 == y1:
        return float(x0)
    return float(x0 + (limit - y0) * (x1 - x0) / (y1 - y0))


def half_kelly(f_star: float) -> float:
    """Half-Kelly: gives up ~25% of the growth for ~50% of the volatility.

    Standard practice when the drift estimate is uncertain, which it always is. If the
    true optimum is half of what you estimated, full Kelly on the estimate is already
    over-levered, while half-Kelly is still on the safe side of the growth peak.
    """
    return f_star / 2.0


def constrained_growth_optimal(table: pd.DataFrame, threshold: float) -> float:
    """Maximise piecewise-linear median growth over the feasible leverage set.

    Include boundary crossings, rather than assuming growth increases until the
    drawdown budget binds. Ties choose the smaller exposure.
    """
    table = table.sort_index()
    x = table.index.to_numpy(float)
    g = table["median_cagr"].to_numpy(float)
    d = table["prob_deep_drawdown"].to_numpy(float)
    candidates = [(x[i], g[i]) for i in range(len(x)) if d[i] <= threshold]
    for i in range(len(x) - 1):
        if (d[i] - threshold) * (d[i + 1] - threshold) < 0:
            w = (threshold - d[i]) / (d[i + 1] - d[i])
            candidates.append((x[i] + w * (x[i + 1] - x[i]), g[i] + w * (g[i + 1] - g[i])))
    return float(max(candidates, key=lambda p: (p[1], -p[0]))[0]) if candidates else float("nan")


def summarise_answers(
    bootstrap_table: pd.DataFrame,
    kelly_estimates: dict[str, float],
    drawdown_budgets: tuple[float, ...] = (-0.25, -0.35, -0.50),
) -> pd.DataFrame:
    """One table of every "optimal leverage" this repo can defend, and its basis."""
    rows = [
        {
            "criterion": "growth-optimal (median CAGR)",
            "leverage": growth_optimal(bootstrap_table),
            "basis": "maximises median 10y CAGR across bootstrap paths",
        },
        {
            "criterion": "robust-optimal (5th pct CAGR)",
            "leverage": robust_optimal(bootstrap_table, "cagr_p05"),
            "basis": "maximises the 5th percentile of 10y CAGR",
        },
        {
            "criterion": "robust-optimal (25th pct CAGR)",
            "leverage": robust_optimal(bootstrap_table, "cagr_p25"),
            "basis": "maximises the 25th percentile of 10y CAGR",
        },
    ]
    for name, f in kelly_estimates.items():
        rows.append(
            {
                "criterion": f"full Kelly ({name})",
                "leverage": f,
                "basis": "growth-optimal under that sample's drift estimate",
            }
        )
        rows.append(
            {
                "criterion": f"half Kelly ({name})",
                "leverage": half_kelly(f),
                "basis": "haircut for drift-estimation error",
            }
        )
    for limit in drawdown_budgets:
        rows.append(
            {
                "criterion": f"drawdown budget {limit:.0%} (median)",
                "leverage": drawdown_budget(bootstrap_table, limit),
                "basis": f"largest leverage with median max drawdown inside {limit:.0%}",
            }
        )
    return pd.DataFrame(rows)
