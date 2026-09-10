"""Optimal leverage from the Kelly criterion, analytic and empirical.

Two versions, because they disagree and the disagreement is the point:

* The Gaussian formula ``f* = (mu - r) / sigma**2`` assumes returns are normal. It is
  a closed form, it is what everyone quotes, and it is optimistic — normality has no
  room for the days that actually damage a levered account.
* The empirical version maximises realised ``E[log(1 + f*r - (f-1)*i)]`` over the
  actual daily return sample, so every fat-tailed day is priced in at its true weight.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize_scalar

from .margin import ACCRUAL_DIVISOR
from .metrics import TRADING_DAYS


def gaussian_kelly(returns: np.ndarray, borrow_rate: float) -> dict[str, float]:
    """Continuous-time Kelly leverage under a lognormal assumption.

    Growth is ``g(f) = r + f*(mu - r) - f**2 * sigma**2 / 2``, maximised at
    ``f* = (mu - r) / sigma**2`` with ``mu`` the arithmetic annualised drift.
    """
    returns = np.asarray(returns, dtype=float)
    mu = float(returns.mean() * TRADING_DAYS)
    sigma = float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
    f_star = (mu - borrow_rate) / sigma**2
    return {
        "mu_arith": mu,
        "sigma": sigma,
        "borrow_rate": borrow_rate,
        "f_star": float(f_star),
        "growth_at_f_star": float(
            borrow_rate + f_star * (mu - borrow_rate) - 0.5 * f_star**2 * sigma**2
        ),
    }


def _log_growth(f: float, returns: np.ndarray, daily_borrow: np.ndarray) -> float:
    """Mean daily log return of a continuously rebalanced account at leverage ``f``."""
    equity_ret = f * returns - (f - 1.0) * daily_borrow
    if np.any(equity_ret <= -1.0):
        return -np.inf
    return float(np.mean(np.log1p(equity_ret)))


def empirical_kelly(
    returns: np.ndarray,
    benchmark: np.ndarray,
    borrow_spread: float = 0.015,
    bounds: tuple[float, float] = (0.0, 6.0),
) -> dict[str, float]:
    """Leverage that maximises realised log growth on the observed return sample."""
    returns = np.asarray(returns, dtype=float)
    daily_borrow = (np.asarray(benchmark, dtype=float) + borrow_spread) / ACCRUAL_DIVISOR

    result = minimize_scalar(
        lambda f: -_log_growth(f, returns, daily_borrow),
        bounds=bounds,
        method="bounded",
        options={"xatol": 1e-4},
    )
    f_star = float(result.x)
    g_star = _log_growth(f_star, returns, daily_borrow)
    return {
        "f_star": f_star,
        "growth_at_f_star": float(np.expm1(g_star * TRADING_DAYS)),
        "borrow_spread": borrow_spread,
    }


def growth_curve(
    returns: np.ndarray,
    benchmark: np.ndarray,
    borrow_spread: float = 0.015,
    grid: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Annualised log-growth rate across a grid of leverage levels."""
    if grid is None:
        grid = np.arange(0.0, 4.01, 0.05)
    daily_borrow = (np.asarray(benchmark, dtype=float) + borrow_spread) / ACCRUAL_DIVISOR
    growth = np.array(
        [np.expm1(_log_growth(float(f), returns, daily_borrow) * TRADING_DAYS) for f in grid]
    )
    return grid, growth
