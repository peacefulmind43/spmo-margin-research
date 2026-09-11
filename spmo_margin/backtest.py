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
    ACCRUAL_DIVISOR,
    IBKR_PRO_USD_TIERS,
    blended_margin_rate,
    credit_rate,
)
from .metrics import summarise

REBALANCE_PERIODS = {"daily": 1, "weekly": 5, "monthly": 21, "quarterly": 63}


CONTRIBUTION_PERIOD = 21  # trading days, i.e. roughly monthly


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
    monthly_contribution: float = 0.0
    contribution_mode: str = "deleverage"
    interest_tax_shield: float = 0.0
    intraday_dip: float = 0.0

    def borrow_rate(self, loan: float, benchmark: float) -> float:
        if self.benchmark_override is not None:
            benchmark = self.benchmark_override
        if self.spread_override is not None:
            rate = max(benchmark + self.spread_override, 0.0)
        else:
            rate = blended_margin_rate(loan, benchmark, self.tiers)
        # Deducting margin interest against other taxable income lowers its true
        # cost. Modelled as a reduced effective rate, which assumes the deduction is
        # usable in the year it accrues -- optimistic if investment income is the
        # only income it can offset, and wrong entirely if the income it finances is
        # tax-exempt, in which case the shield should be left at zero.
        return rate * (1.0 - self.interest_tax_shield)


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
    contributions = np.zeros(n)

    for t in range(n):
        # 1. financing accrues on yesterday's balance
        if debit > 0:
            rate = account.borrow_rate(debit, benchmark[t])
            accrual = debit * rate / ACCRUAL_DIVISOR
            debit += accrual
            interest_paid += accrual
        elif debit < 0:
            cash = -debit
            debit -= cash * credit_rate(cash, benchmark[t]) / ACCRUAL_DIVISOR

        # 2. the market moves the position. A broker tests the requirement against
        # the intraday low, not the close, so the day is walked in two steps: down to
        # the low (where a liquidation would happen, at that price) and then on to
        # the close. Getting sold at the low and missing the rebound is the whipsaw
        # a close-only simulation cannot see. intraday_dip = 0 collapses this back to
        # a single close-to-close step.
        close_factor = 1.0 + returns[t]
        low_factor = max(close_factor + account.intraday_dip, 1e-9)
        position *= low_factor
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

        # whatever position survived the low now rides to the close
        position *= close_factor / low_factor
        eq = position - debit
        if eq <= 0 or position <= 0:
            equity_curve[t + 1 :] = 0.0
            leverage_path[t] = np.nan
            ruin_day = t
            break

        leverage_path[t] = position / eq

        # 4. new cash arrives
        if account.monthly_contribution and t % CONTRIBUTION_PERIOD == 0:
            if account.contribution_mode == "invest":
                # buy more of the asset and leave the loan alone, so the debt stays
                # a fixed number of dollars and leverage decays as the account grows
                position += account.monthly_contribution
            elif account.contribution_mode == "deleverage":
                # cash pays down the loan first, the strictly safer default
                debit -= account.monthly_contribution
            else:
                raise ValueError(
                    f"unknown contribution_mode: {account.contribution_mode!r}"
                )
            eq += account.monthly_contribution
            contributions[t] = account.monthly_contribution

        # 5. scheduled rebalance puts the account back on target
        if _rebalance_due(t, position / eq, account):
            position = account.leverage * eq
            debit = position - eq

        equity_curve[t + 1] = eq

    stats = summarise(equity_curve, n_days=n, contributions=contributions)
    stats.update(
        leverage=account.leverage,
        rebalance=account.rebalance,
        interest_paid=interest_paid,
        interest_pct_of_start=interest_paid / account.equity,
        monthly_contribution=account.monthly_contribution,
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
