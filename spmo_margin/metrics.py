"""Performance and risk statistics for an equity curve.

Contributions complicate every one of these. Cash arriving in the account raises
equity without being a return, so it has to be stripped out before any return is
computed, and the usual "growth of $1" is meaningless once you keep adding dollars.
Where an account is being funded over time this module reports:

* a **time-weighted** return, contributions removed -- the honest measure of the
  strategy itself, comparable across contribution levels;
* a **money-weighted** return (IRR) -- what the investor actually earned on the
  money, which differs whenever the contribution schedule interacts with the path;
* ``worst_vs_contributed`` -- at the worst moment, how many cents the account held
  per dollar ever put in. For someone still funding an account this is the number
  that hurts, and it is far worse than the headline drawdown suggests.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

TRADING_DAYS = 252


def drawdown_series(equity: np.ndarray) -> np.ndarray:
    peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peak > 0, equity / peak - 1.0, -1.0)
    return dd


def max_drawdown(equity: np.ndarray) -> float:
    return float(drawdown_series(equity).min())


def longest_underwater_days(equity: np.ndarray) -> int:
    dd = drawdown_series(equity)
    longest = current = 0
    for value in dd:
        current = current + 1 if value < -1e-12 else 0
        longest = max(longest, current)
    return int(longest)


def ulcer_index(equity: np.ndarray) -> float:
    dd = drawdown_series(equity)
    return float(np.sqrt(np.mean(np.square(dd * 100.0))))


def money_weighted_return(equity: np.ndarray, contributions: np.ndarray) -> float:
    """Annualised IRR of the actual cashflows into and out of the account."""
    n = len(equity) - 1
    cashflows = np.zeros(n + 1)
    cashflows[0] = -equity[0]
    cashflows[1:] -= contributions
    cashflows[n] += equity[-1]

    def npv(annual: float) -> float:
        daily = (1.0 + annual) ** (1.0 / TRADING_DAYS)
        return float(np.sum(cashflows * daily ** -np.arange(n + 1)))

    lo, hi = -0.95, 5.0
    try:
        if npv(lo) * npv(hi) > 0:
            return float("nan")
        return float(brentq(npv, lo, hi, xtol=1e-10))
    except (ValueError, RuntimeError):
        return float("nan")


def summarise(
    equity: np.ndarray,
    n_days: int | None = None,
    contributions: np.ndarray | None = None,
) -> dict[str, float]:
    """Headline statistics for an equity curve that starts at ``equity[0]``.

    ``contributions[t]`` is cash added at step ``t``, already reflected in
    ``equity[t + 1]``. Pass it whenever the account is being funded over time.
    """
    equity = np.asarray(equity, dtype=float)
    n = n_days if n_days is not None else len(equity) - 1
    years = n / TRADING_DAYS
    funded = contributions is not None and np.any(contributions)
    contributions = (
        np.zeros(len(equity) - 1)
        if contributions is None
        else np.asarray(contributions, dtype=float)
    )

    # Strip deposits before measuring returns: cash arriving is not performance.
    alive = equity > 0
    rets = np.zeros(len(equity) - 1)
    valid = alive[:-1] & alive[1:]
    rets[valid] = (equity[1:][valid] - contributions[valid]) / equity[:-1][valid] - 1.0
    rets = np.clip(rets, -1.0, None)

    growth = float(np.prod(1.0 + rets))
    twr = growth ** (1.0 / years) - 1.0 if growth > 0 else -1.0
    index = np.concatenate([[1.0], np.cumprod(1.0 + rets)])

    vol = float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(rets) > 1 else np.nan
    mdd = max_drawdown(index)

    total_in = float(equity[0] + contributions.sum())
    cumulative_in = equity[0] + np.cumsum(contributions)
    with np.errstate(divide="ignore", invalid="ignore"):
        vs_in = np.where(cumulative_in > 0, equity[1:] / cumulative_in, np.nan)

    stats = {
        "terminal_multiple": float(equity[-1] / equity[0]),
        "cagr": float(twr),
        "vol": vol,
        "sharpe_naive": float(twr / vol) if vol and vol > 0 else np.nan,
        "max_drawdown": mdd,
        "calmar": float(twr / abs(mdd)) if mdd < 0 else np.nan,
        "ulcer_index": ulcer_index(index),
        "worst_day": float(rets.min()) if len(rets) else np.nan,
        "longest_underwater_days": longest_underwater_days(index),
        "wiped_out": bool(equity[-1] <= 0),
    }
    if funded:
        stats.update(
            total_contributed=total_in,
            terminal_vs_contributed=float(equity[-1] / total_in),
            money_weighted_return=money_weighted_return(equity, contributions),
            worst_vs_contributed=float(np.nanmin(vs_in)),
        )
    return stats
