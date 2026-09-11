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

from .backtest import CONTRIBUTION_PERIOD, REBALANCE_PERIODS
from .margin import (
    CREDIT_SPREAD,
    CREDIT_THRESHOLD,
    ACCRUAL_DIVISOR,
    IBKR_PRO_USD_TIERS,
    BENCHMARK_FLOOR,
)
from .metrics import TRADING_DAYS
from .inputs import time_input, validate_account


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
    if returns.ndim != 1 or not np.isfinite(returns).all() or min(n_paths, horizon, block) <= 0:
        raise ValueError("finite 1D sample and positive paths/horizon/block required")
    if n < block:
        raise ValueError("return sample is shorter than the block length")
    n_blocks = int(np.ceil(horizon / block))
    starts = rng.integers(0, n - block + 1, size=(n_paths, n_blocks))
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
        cost += amount * (np.maximum(benchmark, BENCHMARK_FLOOR) + spread)
        lower = upper
    return np.divide(cost, loan, out=np.zeros_like(loan), where=loan > 0)


def _credit_rate_vec(cash: np.ndarray, benchmark: float, nav=100_000.0) -> np.ndarray:
    """Vectorised interest paid on idle cash; matches :func:`margin.credit_rate`."""
    paid = np.maximum(benchmark + CREDIT_SPREAD, 0.0)
    return np.clip(np.asarray(nav) / 100_000, 0.0, 1.0) * np.where(
        cash > CREDIT_THRESHOLD, paid * (cash - CREDIT_THRESHOLD) / cash, 0.0
    )


def simulate_paths(
    paths: np.ndarray,
    leverage: float,
    benchmark: float,
    rebalance: str = "monthly",
    maintenance_margin: float = 0.25,
    equity0: float = 100_000.0,
    liquidation_slippage: float = 0.001,
    tiers: list[tuple[float, float]] = IBKR_PRO_USD_TIERS,
    monthly_contribution: float = 0.0,
    contribution_mode: str = "deleverage",
    interest_tax_shield: float = 0.0,
    intraday_dip: float = 0.0,
    rebalance_cost: float = 0.0002,
    band: float = 0.25,  # must match Account.band, or the twins disagree
    max_leverage: float | None = None,
    max_loan: float = np.inf,
    annual_drag: float = 0.0,
    borrow_surcharge: float = 0.0,
    withdrawals=0.0,
    position0=None,
) -> dict[str, np.ndarray]:
    """Step many return paths through the margin account simultaneously.

    Returns and drawdowns are time-weighted -- contributions are excluded from the
    performance measurement, so results stay comparable across funding levels.
    """
    paths = np.asarray(paths, dtype=float)
    if paths.ndim != 2 or min(paths.shape) < 1 or not np.isfinite(paths).all() or (paths < -1).any():
        raise ValueError("paths must be a nonempty finite matrix with returns >= -1")
    n_paths, horizon = paths.shape
    validate_account(leverage, equity0, rebalance_cost, liquidation_slippage, band,
                     interest_tax_shield, monthly_contribution, max_leverage, max_loan,
                     resuming=position0 is not None)
    if contribution_mode not in {"invest", "deleverage"}:
        raise ValueError("unknown contribution mode")
    if not np.isfinite([annual_drag, borrow_surcharge]).all() or min(annual_drag, borrow_surcharge) < 0:
        raise ValueError("drag and surcharge must be finite and nonnegative")
    requirements = time_input(maintenance_margin, paths.shape, "maintenance")
    withdrawals = time_input(withdrawals, paths.shape, "withdrawals")
    if ((requirements < 0) | (requirements > 1)).any() or (withdrawals < 0).any():
        raise ValueError("maintenance must be in [0, 1]; withdrawals must be nonnegative")
    # A scalar, common time series, or one financing path per return path.
    benchmark = np.asarray(benchmark, dtype=float)
    if not np.isfinite(benchmark).all():
        raise ValueError("benchmark must be finite")
    if benchmark.ndim > 2 or (benchmark.ndim == 1 and benchmark.shape != (horizon,)) or (benchmark.ndim == 2 and benchmark.shape != paths.shape):
        raise ValueError("benchmark must be scalar, horizon-length, or paths-shaped")
    period = REBALANCE_PERIODS.get(rebalance)
    if rebalance not in {"never", "band"} and period is None:
        raise ValueError(f"unsupported rebalance schedule: {rebalance!r}")

    equity = np.full(n_paths, equity0)
    position = np.full(n_paths, equity0 * leverage) if position0 is None else np.broadcast_to(np.asarray(position0, dtype=float), (n_paths,)).copy()
    if not np.isfinite(position).all() or (position < 0).any():
        raise ValueError("position0 must be finite and nonnegative")
    debit = position - equity

    twr = np.ones(n_paths)
    peak = np.ones(n_paths)
    max_dd = np.zeros(n_paths)
    contributed = np.full(n_paths, equity0)
    worst_vs_in = np.ones(n_paths)
    margin_calls = np.zeros(n_paths, dtype=int)
    interest_paid = np.zeros(n_paths)
    alive = np.ones(n_paths, dtype=bool)
    leverage_sum = np.zeros(n_paths)
    leverage_days = np.zeros(n_paths)
    rebalances = np.zeros(n_paths, dtype=int)
    rebalance_cost_paid = np.zeros(n_paths)
    withdrawals_paid = np.zeros(n_paths)
    withdrawal_failures = np.zeros(n_paths, dtype=int)
    deficit = np.zeros(n_paths)

    for t in range(horizon):
        opening = equity.copy()
        m = requirements[:, t]
        bm = benchmark if benchmark.ndim == 0 else (benchmark[t] if benchmark.ndim == 1 else benchmark[:, t])

        # 1. financing accrues on yesterday's debit balance
        borrowing = alive & (debit > 0)
        if borrowing.any():
            rate = _blended_rate_vec(debit[borrowing], bm[borrowing] if bm.ndim else bm, tiers)
            accrual = debit[borrowing] * (rate + borrow_surcharge) * (1.0 - interest_tax_shield) / ACCRUAL_DIVISOR
            debit[borrowing] += accrual
            interest_paid[borrowing] += accrual

        # cash balances (which contributions create) earn credit interest instead
        lending = alive & (debit < 0)
        if lending.any():
            cash = -debit[lending]
            debit[lending] -= cash * _credit_rate_vec(cash, bm[lending] if bm.ndim else bm, opening[lending]) / ACCRUAL_DIVISOR

        # 2. the market moves the position, low first then close (see backtest.py)
        close_factor = np.maximum(1.0 + paths[:, t] - annual_drag / 252, 0.0)
        low_factor = np.maximum(close_factor + intraday_dip, 1e-9)
        position[alive] *= low_factor[alive]
        equity = np.where(alive, position - debit, 0.0)

        dead_now = alive & (equity <= 0)
        if dead_now.any():
            deficit[dead_now] = np.maximum(-equity[dead_now], 0.0)
            alive &= ~dead_now
            equity[dead_now] = 0.0
            position[dead_now] = 0.0
            debit[dead_now] = 0.0

        # 3. maintenance margin breach -> forced sale down to the requirement
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(position > 0, equity / position, 1.0)
        called = alive & (ratio < m)
        if called.any():
            den = m[called] - liquidation_slippage
            sold = np.minimum(position[called], np.divide(
                m[called] * position[called] - equity[called], den,
                out=position[called].copy(), where=den > 0))
            cost = sold * liquidation_slippage
            equity[called] -= cost
            position[called] -= sold
            debit[called] = position[called] - equity[called]
            margin_calls[called] += 1
            broke = called & (equity <= 0)
            if broke.any():
                deficit[broke] = np.maximum(-equity[broke], 0.0)
                alive &= ~broke
                equity[broke] = 0.0
                position[broke] = 0.0
                debit[broke] = 0.0

        # whatever position survived the low now rides to the close
        position[alive] *= (close_factor / low_factor)[alive]
        equity = np.where(alive, position - debit, 0.0)
        dead_now = alive & (equity <= 0)
        if dead_now.any():
            deficit[dead_now] = np.maximum(-equity[dead_now], 0.0)
            alive &= ~dead_now
            equity[dead_now] = 0.0
            position[dead_now] = 0.0
            debit[dead_now] = 0.0

        # 4. new cash arrives
        added = np.zeros(n_paths)
        if monthly_contribution and t % CONTRIBUTION_PERIOD == 0:
            if contribution_mode == "invest":
                bought = monthly_contribution / (1 + rebalance_cost)
                fee = bought * rebalance_cost
                position[alive] += bought
                equity[alive] -= fee
                rebalance_cost_paid[alive] += fee
            elif contribution_mode == "deleverage":
                debit[alive] -= monthly_contribution
            else:
                raise ValueError(f"unknown contribution_mode: {contribution_mode!r}")
            equity[alive] += monthly_contribution
            contributed[alive] += monthly_contribution
            added[alive] = monthly_contribution

        requested = withdrawals[:, t]
        cash_used = np.minimum(requested, np.maximum(-debit, 0.0))
        sold = (requested - cash_used) / (1.0 - rebalance_cost)
        fee = sold * rebalance_cost
        payable = alive & (requested > 0) & (sold <= position) & (requested + fee < equity)
        withdrawal_failures += (requested > 0) & ~payable
        position[payable] -= sold[payable]
        debit[payable] += cash_used[payable]
        equity[payable] -= requested[payable] + fee[payable]
        added[payable] -= requested[payable]
        withdrawals_paid[payable] += requested[payable]
        rebalance_cost_paid[payable] += fee[payable]
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(position > 0, equity / position, 1.0)
        called = payable & (ratio < m)
        if called.any():
            den = m[called] - liquidation_slippage
            extra = np.minimum(position[called], np.divide(
                m[called] * position[called] - equity[called], den,
                out=position[called].copy(), where=den > 0))
            loss = extra * liquidation_slippage
            position[called] -= extra
            equity[called] -= loss
            debit[called] = position[called] - equity[called]
            margin_calls[called] += 1
            dead_now = called & (equity <= 0)
            deficit[dead_now] = np.maximum(-equity[dead_now], 0.0)
            alive &= ~dead_now
            equity[dead_now] = position[dead_now] = debit[dead_now] = 0.0

        # 5. rebalance back to target -- on a schedule, or when a band is breached
        if rebalance == "band" and leverage > 0:
            with np.errstate(divide="ignore", invalid="ignore"):
                held = np.where(equity > 0, position / equity, leverage)
            due = alive & (np.abs(held / leverage - 1.0) > band)
        else:
            due = alive if (period is not None and t % period == 0) else np.zeros_like(alive)
        if due.any():
            maintenance_cap = np.divide(1.0, m[due], out=np.full(due.sum(), np.inf), where=m[due] > 0)
            ceiling = np.minimum(leverage, maintenance_cap)
            if max_leverage is not None:
                ceiling = np.minimum(ceiling, max_leverage)
            direction = np.where(ceiling * equity[due] >= position[due], 1., -1.)
            target = ceiling * (equity[due] + direction * rebalance_cost * position[due]) / (1 + direction * rebalance_cost * ceiling)
            direction = np.where(position[due] - equity[due] > max_loan, -1., 1.)
            cap = (equity[due] + direction * rebalance_cost * position[due] + max_loan) / (1 + direction * rebalance_cost)
            target = np.maximum(0.0, np.minimum(target, cap))
            cost = np.abs(target - position[due]) * rebalance_cost
            equity[due] -= cost
            rebalance_cost_paid[due] += cost
            rebalances[due] += 1
            position[due] = target
            debit[due] = position[due] - equity[due]

        # Performance for the day: everything that happened to the account except the
        # deposit. This has to come after the rebalance, or its cost is dropped from
        # the return series -- the scalar simulator measures the same way, which is
        # what the equivalence test caught when this was ordered wrongly.
        with np.errstate(divide="ignore", invalid="ignore"):
            step = np.where(opening > 0, (equity - added) / opening - 1.0, 0.0)
            worst_vs_in = np.minimum(worst_vs_in, equity / contributed)
        twr *= 1.0 + np.clip(step, -1.0, None)
        peak = np.maximum(peak, twr)
        max_dd = np.minimum(max_dd, twr / peak - 1.0)

        # a fixed dollar loan lets leverage decay, so record what it actually was
        with np.errstate(divide="ignore", invalid="ignore"):
            held = np.where(alive & (equity > 0), position / equity, 0.0)
        leverage_sum += held
        leverage_days += alive & (equity > 0)

    years = horizon / TRADING_DAYS
    with np.errstate(divide="ignore", invalid="ignore"):
        cagr = np.where(twr > 0, twr ** (1.0 / years) - 1.0, -1.0)

    return {
        "terminal_equity": equity,
        "terminal_net_equity": equity - deficit,
        "ruin_deficit": deficit,
        "terminal_position": position,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "margin_calls": margin_calls,
        "interest_paid": interest_paid,
        "wiped_out": ~alive,
        "total_contributed": contributed,
        "terminal_vs_contributed": equity / contributed,
        "worst_vs_contributed": worst_vs_in,
        "rebalances": rebalances,
        "rebalance_cost_paid": rebalance_cost_paid,
        "withdrawals_paid": withdrawals_paid,
        "withdrawal_failures": withdrawal_failures,
        "mean_leverage": np.divide(
            leverage_sum,
            leverage_days,
            out=np.zeros_like(leverage_sum),
            where=leverage_days > 0,
        ),
        "final_leverage": np.where(equity > 0, position / np.maximum(equity, 1e-9), 0.0),
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
                "median_terminal_vs_contributed": float(
                    np.median(out["terminal_vs_contributed"])
                ),
                "median_worst_vs_contributed": float(
                    np.median(out["worst_vs_contributed"])
                ),
                "p05_worst_vs_contributed": float(
                    np.percentile(out["worst_vs_contributed"], 5)
                ),
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
