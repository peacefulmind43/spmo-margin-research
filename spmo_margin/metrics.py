"""Performance and risk statistics for an equity curve."""

from __future__ import annotations

import numpy as np

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


def summarise(equity: np.ndarray, n_days: int | None = None) -> dict[str, float]:
    """Headline statistics for an equity curve that starts at ``equity[0]``."""
    equity = np.asarray(equity, dtype=float)
    n = n_days if n_days is not None else len(equity) - 1
    years = n / TRADING_DAYS
    start, end = equity[0], equity[-1]

    if end <= 0:
        cagr = -1.0
    else:
        cagr = float((end / start) ** (1.0 / years) - 1.0)

    alive = equity > 0
    rets = np.zeros(len(equity) - 1)
    valid = alive[:-1] & alive[1:]
    rets[valid] = equity[1:][valid] / equity[:-1][valid] - 1.0
    vol = float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(rets) > 1 else np.nan
    mdd = max_drawdown(equity)

    return {
        "terminal_multiple": float(end / start),
        "cagr": cagr,
        "vol": vol,
        "sharpe_naive": float(cagr / vol) if vol and vol > 0 else np.nan,
        "max_drawdown": mdd,
        "calmar": float(cagr / abs(mdd)) if mdd < 0 else np.nan,
        "ulcer_index": ulcer_index(equity),
        "worst_day": float(rets.min()) if len(rets) else np.nan,
        "longest_underwater_days": longest_underwater_days(equity),
        "wiped_out": bool(end <= 0),
    }
