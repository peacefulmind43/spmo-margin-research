"""Block-bootstrap Monte Carlo over leverage levels.

One historical path is one sample. SPMO's own history is a single ten-year draw that
happens to contain a huge momentum bull market and no 2008, so ranking leverage on it
alone measures luck as much as anything else. Resampling 21-day blocks preserves
short-horizon volatility clustering while generating many alternative paths, which
turns "3x won" into a distribution with a visible ruin probability.

The simulator here is a vectorised twin of :func:`spmo_margin.backtest.simulate` --
same account mechanics, but stepping thousands of paths forward together so a full
sweep runs in seconds. ``tests/test_consistency.py`` checks the two agree.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import REBALANCE_PERIODS
from .margin import DAY_COUNT, IBKR_PRO_USD_TIERS, MARGIN_RATE_FLOOR
from .metrics import TRADING_DAYS


def moving_block_paths(
    returns: np.ndarray,
    n_paths: int,
    horizon: int,
    block: int = 21,
    seed: int = 20260910,
) -> np.ndarray:
    """Draw ``n_paths`` return paths of length ``horizon`` by resampling blocks."""
    returns = np.asarray(returns, dtype=float)
    rng = np.random.default_rng(seed)
    n = len(returns)
    if n <= block:
        raise ValueError("return sample is shorter than the block length")
    n_blocks = int(np.ceil(horizon / block))
    starts = rng.integers(0, n - block, size=(n_paths, n_blocks))
    offsets = np.arange(block)
    idx = (starts[:, :, None] + offsets[None, None, :]).reshape(n_paths, -1)
    return returns[idx[:, :horizon]]


def _blended_rate_vec(
    loan: np.ndarray,
    benchmark: float,
    tiers: list[tuple[float, float]],
) -> np.ndarray:
    """Vectorised tiered margin rate for an array of loan balances."""
    loan = np.maximum(loan, 0.0)
    cost = np.zeros_like(loan)
    lower = 0.0
    for upper, spread in tiers:
        amount = np.clip(np.minimum(loan, upper) - lower, 0.0, None)
        cost += amount * max(benchmark + spread, MARGIN_RATE_FLOOR)
        lower = upper
    return np.divide(cost, loan, out=np.zeros_like(loan), where=loan > 0)


def simulate_paths(
    paths: np.ndarray,
    leverage: float,
    benchmark: float,
    rebalance: str = "monthly",
    maintenance_margin: float = 0.25,
    equity0: float = 100_000.0,
    liquidation_slippage: float = 0.001,
    tiers: list[tuple[float, float]] = IBKR_PRO_USD_TIERS,
) -> dict[str, np.ndarray]:
    """Step many return paths through the margin account simultaneously."""
    n_paths, horizon = paths.shape
    period = REBALANCE_PERIODS.get(rebalance) if rebalance != "never" else None
    if rebalance != "never" and period is None:
        raise ValueError(f"unsupported rebalance schedule: {rebalance!r}")

    equity = np.full(n_paths, equity0)
    position = np.full(n_paths, equity0 * leverage)
    debit = position - equity

    peak = equity.copy()
    max_dd = np.zeros(n_paths)
    margin_calls = np.zeros(n_paths, dtype=int)
    interest_paid = np.zeros(n_paths)
    alive = np.ones(n_paths, dtype=bool)

    for t in range(horizon):
        # 1. financing accrues on yesterday's debit balance
        borrowing = alive & (debit > 0)
        if borrowing.any():
            rate = _blended_rate_vec(debit[borrowing], benchmark, tiers)
            accrual = debit[borrowing] * rate / DAY_COUNT
            debit[borrowing] += accrual
            interest_paid[borrowing] += accrual

        # 2. the market moves the position
        position[alive] *= 1.0 + paths[alive, t]
        equity = np.where(alive, position - debit, 0.0)

        dead_now = alive & ((equity <= 0) | (position <= 0))
        if dead_now.any():
            alive &= ~dead_now
            equity[dead_now] = 0.0
            position[dead_now] = 0.0
            debit[dead_now] = 0.0
            max_dd[dead_now] = -1.0

        # 3. maintenance margin breach -> forced sale down to the requirement
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(position > 0, equity / position, 1.0)
        called = alive & (ratio < maintenance_margin)
        if called.any():
            target = equity[called] / maintenance_margin
            cost = (position[called] - target) * liquidation_slippage
            equity[called] -= cost
            position[called] = equity[called] / maintenance_margin
            debit[called] = position[called] - equity[called]
            margin_calls[called] += 1
            broke = called & (equity <= 0)
            if broke.any():
                alive &= ~broke
                equity[broke] = 0.0
                position[broke] = 0.0
                debit[broke] = 0.0
                max_dd[broke] = -1.0

        # 4. scheduled rebalance back to target leverage
        if period is not None and t % period == 0:
            position[alive] = leverage * equity[alive]
            debit[alive] = position[alive] - equity[alive]

        peak = np.maximum(peak, equity)
        with np.errstate(divide="ignore", invalid="ignore"):
            dd = np.where(peak > 0, equity / peak - 1.0, -1.0)
        max_dd = np.minimum(max_dd, dd)

    years = horizon / TRADING_DAYS
    with np.errstate(divide="ignore", invalid="ignore"):
        cagr = np.where(equity > 0, (equity / equity0) ** (1.0 / years) - 1.0, -1.0)

    return {
        "terminal_equity": equity,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "margin_calls": margin_calls,
        "interest_paid": interest_paid,
        "wiped_out": ~alive,
    }


def bootstrap_sweep(
    returns: np.ndarray,
    leverages,
    benchmark_level: float,
    n_paths: int = 4000,
    horizon_years: float = 10.0,
    block: int = 21,
    rebalance: str = "monthly",
    seed: int = 20260910,
    **sim_kwargs,
) -> pd.DataFrame:
    """Distribution of outcomes at each leverage level across shared bootstrap paths.

    Every leverage level sees the *same* set of paths, so per-path comparisons against
    the unlevered account are meaningful rather than an artefact of different draws.
    """
    horizon = int(round(horizon_years * TRADING_DAYS))
    paths = moving_block_paths(returns, n_paths, horizon, block=block, seed=seed)

    baseline = simulate_paths(
        paths, 1.0, benchmark_level, rebalance=rebalance, **sim_kwargs
    )["cagr"]

    rows = []
    for lev in leverages:
        out = simulate_paths(
            paths, float(lev), benchmark_level, rebalance=rebalance, **sim_kwargs
        )
        cagr, mdd = out["cagr"], out["max_drawdown"]
        rows.append(
            {
                "leverage": float(lev),
                "cagr_p05": float(np.percentile(cagr, 5)),
                "cagr_p25": float(np.percentile(cagr, 25)),
                "cagr_median": float(np.median(cagr)),
                "cagr_p75": float(np.percentile(cagr, 75)),
                "cagr_p95": float(np.percentile(cagr, 95)),
                "cagr_mean": float(cagr.mean()),
                "median_max_drawdown": float(np.median(mdd)),
                "worst_5pct_max_drawdown": float(np.percentile(mdd, 5)),
                "prob_ruin": float(out["wiped_out"].mean()),
                "prob_dd_over_50": float((mdd < -0.50).mean()),
                "prob_dd_over_70": float((mdd < -0.70).mean()),
                "prob_beat_unlevered": float((cagr > baseline).mean()),
                "median_margin_calls": float(np.median(out["margin_calls"])),
            }
        )
    return pd.DataFrame(rows).set_index("leverage")
