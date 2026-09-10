"""Day-by-day simulation of a margin-financed position with forced liquidation.

The account is modelled the way IBKR actually holds it: a position value ``P``, a
debit balance ``D`` that accrues tiered interest, and equity ``E = P - D``. Leverage
is ``P / E``. Nothing about this is a leveraged ETF: the borrowing cost is explicit
and the position is only reset to target leverage on the chosen rebalance schedule,
so leverage drifts up during a drawdown exactly as it does in a real account.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .margin import (
    DAY_COUNT,
    IBKR_PRO_USD_TIERS,
    blended_margin_rate,
    credit_rate,
)
from .metrics import summarise

REBALANCE_PERIODS = {"daily": 1, "weekly": 5, "monthly": 21, "quarterly": 63}


@dataclass
class Account:
    """Configuration of the margin account being simulated."""

    leverage: float
    rebalance: str = "monthly"
    band: float = 0.25
    maintenance_margin: float = 0.25
    equity: float = 100_000.0
    tiers: list[tuple[float, float]] = field(default_factory=lambda: IBKR_PRO_USD_TIERS)
    spread_override: float | None = None
    liquidation_slippage: float = 0.001
    benchmark_override: float | None = None

    def borrow_rate(self, loan: float, benchmark: float) -> float:
        if self.benchmark_override is not None:
            benchmark = self.benchmark_override
        if self.spread_override is not None:
            return max(benchmark + self.spread_override, 0.0)
        return blended_margin_rate(loan, benchmark, self.tiers)


def _rebalance_due(t: int, actual_lev: float, account: Account) -> bool:
    if account.rebalance == "never":
        return False
    if account.rebalance == "band":
        if account.leverage <= 0:
            return False
        return abs(actual_lev / account.leverage - 1.0) > account.band
    period = REBALANCE_PERIODS.get(account.rebalance)
    if period is None:
        raise ValueError(f"unknown rebalance schedule: {account.rebalance!r}")
    return t % period == 0


def simulate(returns: np.ndarray, benchmark: np.ndarray, account: Account) -> dict:
    """Run the account through a return path and report the equity curve."""
    returns = np.asarray(returns, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    n = len(returns)

    equity_curve = np.empty(n + 1)
    equity_curve[0] = account.equity
    leverage_path = np.full(n, np.nan)

    position = account.equity * account.leverage
    debit = position - account.equity

    interest_paid = 0.0
    liquidation_cost = 0.0
    margin_calls = 0
    ruin_day = -1

    for t in range(n):
        # 1. financing accrues on yesterday's balance
        if debit > 0:
            rate = account.borrow_rate(debit, benchmark[t])
            accrual = debit * rate / DAY_COUNT
            debit += accrual
            interest_paid += accrual
        elif debit < 0:
            cash = -debit
            debit -= cash * credit_rate(cash, benchmark[t]) / DAY_COUNT

        # 2. the market moves the position
        position *= 1.0 + returns[t]
        eq = position - debit

        if eq <= 0 or position <= 0:
            equity_curve[t + 1 :] = 0.0
            leverage_path[t] = np.nan
            ruin_day = t
            break

        # 3. maintenance margin check -> forced sale down to the requirement
        if eq / position < account.maintenance_margin:
            target_position = eq / account.maintenance_margin
            sold = position - target_position
            cost = sold * account.liquidation_slippage
            liquidation_cost += cost
            eq -= cost
            position = eq / account.maintenance_margin
            debit = position - eq
            margin_calls += 1
            if eq <= 0:
                equity_curve[t + 1 :] = 0.0
                ruin_day = t
                break

        leverage_path[t] = position / eq

        # 4. scheduled rebalance back to target leverage
        if _rebalance_due(t, position / eq, account):
            position = account.leverage * eq
            debit = position - eq

        equity_curve[t + 1] = eq

    stats = summarise(equity_curve, n_days=n)
    stats.update(
        leverage=account.leverage,
        rebalance=account.rebalance,
        interest_paid=interest_paid,
        interest_pct_of_start=interest_paid / account.equity,
        liquidation_cost=liquidation_cost,
        margin_calls=margin_calls,
        ruin_day=ruin_day,
        max_leverage_reached=(
            float(np.nanmax(leverage_path))
            if n and not np.all(np.isnan(leverage_path))
            else np.nan
        ),
    )
    return {"stats": stats, "equity": equity_curve, "leverage_path": leverage_path}


def sweep(
    data: pd.DataFrame,
    leverages,
    rebalance: str = "monthly",
    **account_kwargs,
) -> tuple[pd.DataFrame, dict[float, np.ndarray]]:
    """Simulate a grid of leverage levels over one historical path."""
    rows, curves = [], {}
    for lev in leverages:
        account = Account(leverage=float(lev), rebalance=rebalance, **account_kwargs)
        out = simulate(data["ret"].to_numpy(), data["bm"].to_numpy(), account)
        rows.append(out["stats"])
        curves[float(lev)] = out["equity"]
    return pd.DataFrame(rows).set_index("leverage"), curves
