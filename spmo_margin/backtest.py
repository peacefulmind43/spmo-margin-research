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
from .inputs import time_input, validate_account

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
    # commission plus half-spread on the notional traded. Without this a rebalance
    # is free and the optimal no-trade band is trivially zero.
    rebalance_cost: float = 0.0002
    max_leverage: float | None = None  # explicit opening/rebalance cap, e.g. Reg T 2x
    max_loan: float = np.inf
    annual_drag: float = 0.0  # asset-level tax/fee sensitivity, not a tax calculation
    borrow_surcharge: float = 0.0

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
        return (rate + self.borrow_surcharge) * (1.0 - self.interest_tax_shield)


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


def simulate(returns: np.ndarray, benchmark: np.ndarray, account: Account,
             *, maintenance=None, withdrawals=0.0, position0=None) -> dict:
    """Run the account through a return path and report the equity curve."""
    returns = np.asarray(returns, dtype=float)
    benchmark = np.asarray(benchmark, dtype=float)
    n = len(returns)
    if returns.ndim != 1 or not n or not np.isfinite(returns).all() or (returns < -1).any():
        raise ValueError("returns must be a nonempty finite vector, with returns >= -1")
    benchmark = time_input(benchmark, (n,), "benchmark")
    if account.benchmark_override is not None:
        benchmark = time_input(account.benchmark_override, (n,), "benchmark override")
    maintenance = time_input(account.maintenance_margin if maintenance is None else maintenance, (n,), "maintenance")
    withdrawals = time_input(withdrawals, (n,), "withdrawals")
    if ((maintenance < 0) | (maintenance > 1)).any() or (withdrawals < 0).any():
        raise ValueError("maintenance must be in [0, 1]; withdrawals must be nonnegative")
    validate_account(account.leverage, account.equity, account.rebalance_cost,
                     account.liquidation_slippage, account.band, account.interest_tax_shield,
                     account.monthly_contribution, account.max_leverage, account.max_loan,
                     resuming=position0 is not None)
    if account.rebalance not in {*REBALANCE_PERIODS, "band", "never"}:
        raise ValueError("unknown rebalance schedule")
    if account.contribution_mode not in {"invest", "deleverage"}:
        raise ValueError("unknown contribution mode")
    if not np.isfinite([account.annual_drag, account.borrow_surcharge]).all() or min(account.annual_drag, account.borrow_surcharge) < 0:
        raise ValueError("drag and surcharge must be finite and nonnegative")

    equity_curve = np.empty(n + 1)
    equity_curve[0] = account.equity
    leverage_path = np.full(n, np.nan)

    position = account.equity * account.leverage if position0 is None else float(position0)
    if not np.isfinite(position) or position < 0:
        raise ValueError("position0 must be finite and nonnegative")
    debit = position - account.equity

    interest_paid = 0.0
    liquidation_cost = 0.0
    margin_calls = 0
    rebalances = 0
    traded_notional = 0.0
    rebalance_cost_paid = 0.0
    ruin_day = -1
    contributions = np.zeros(n)
    deposits = np.zeros(n)
    deficit = 0.0
    withdrawals_paid = 0.0
    withdrawal_failures = 0
    withdrawal_attempted = np.zeros(n, dtype=bool)
    final_position = position
    position_curve = np.zeros(n + 1)
    position_curve[0] = position

    for t in range(n):
        # 1. financing accrues on yesterday's balance
        if debit > 0:
            rate = account.borrow_rate(debit, benchmark[t])
            accrual = debit * rate / ACCRUAL_DIVISOR
            debit += accrual
            interest_paid += accrual
        elif debit < 0:
            cash = -debit
            debit -= cash * credit_rate(cash, benchmark[t], equity_curve[t]) / ACCRUAL_DIVISOR

        # 2. the market moves the position. A broker tests the requirement against
        # the intraday low, not the close, so the day is walked in two steps: down to
        # the low (where a liquidation would happen, at that price) and then on to
        # the close. Getting sold at the low and missing the rebound is the whipsaw
        # a close-only simulation cannot see. intraday_dip = 0 collapses this back to
        # a single close-to-close step.
        close_factor = max(1.0 + returns[t] - account.annual_drag / 252, 0.0)
        low_factor = max(close_factor + account.intraday_dip, 1e-9)
        position *= low_factor
        eq = position - debit

        if eq <= 0:
            deficit = max(-eq, 0.0)
            equity_curve[t + 1 :] = 0.0
            leverage_path[t] = np.nan
            ruin_day = t
            break

        # 3. maintenance margin check -> forced sale down to the requirement
        m = maintenance[t]
        if position > 0 and eq / position < m:
            # Solve E - s*x = m*(P-x); charge slippage on the ACTUAL sale.
            denominator = m - account.liquidation_slippage
            sold = min(position, (m * position - eq) / denominator) if denominator > 0 else position
            cost = sold * account.liquidation_slippage
            liquidation_cost += cost
            eq -= cost
            position -= sold
            debit = position - eq
            margin_calls += 1
            if eq <= 0:
                deficit = max(-eq, 0.0)
                equity_curve[t + 1 :] = 0.0
                ruin_day = t
                break

        # whatever position survived the low now rides to the close
        position *= close_factor / low_factor
        eq = position - debit
        if eq <= 0:
            deficit = max(-eq, 0.0)
            equity_curve[t + 1 :] = 0.0
            leverage_path[t] = np.nan
            ruin_day = t
            break

        leverage_path[t] = position / eq

        # 4. new cash arrives
        if account.monthly_contribution and t % CONTRIBUTION_PERIOD == 0:
            if account.contribution_mode == "invest":
                # Buy more of the asset without new principal borrowing. Interest
                # still capitalises into the outstanding loan.
                bought = account.monthly_contribution / (1 + account.rebalance_cost)
                fee = bought * account.rebalance_cost
                position += bought
                eq -= fee
                rebalance_cost_paid += fee
                traded_notional += bought
            elif account.contribution_mode == "deleverage":
                # cash pays down the loan first, the strictly safer default
                debit -= account.monthly_contribution
            else:
                raise ValueError(
                    f"unknown contribution_mode: {account.contribution_mode!r}"
                )
            eq += account.monthly_contribution
            contributions[t] = account.monthly_contribution
            deposits[t] = account.monthly_contribution

        # Withdraw existing cash first, then sell enough securities to pay the
        # requested amount plus transaction cost. Failed requests are not silently
        # financed or counted as market losses: record failure and leave them unpaid.
        requested = withdrawals[t]
        if requested:
            withdrawal_attempted[t] = True
            cash_used = min(requested, max(-debit, 0.0))
            sold = (requested - cash_used) / (1.0 - account.rebalance_cost)
            fee = sold * account.rebalance_cost
            if sold > position or requested + fee >= eq:
                withdrawal_failures += 1
            else:
                position -= sold
                debit += cash_used
                eq -= requested + fee
                contributions[t] -= requested
                withdrawals_paid += requested
                rebalance_cost_paid += fee

                # A withdrawal that leaves insufficient collateral also requires
                # debt repayment. Model that additional sale at the close.
                if position > 0 and eq / position < m:
                    denominator = m - account.liquidation_slippage
                    extra = min(position, (m * position - eq) / denominator) if denominator > 0 else position
                    loss = extra * account.liquidation_slippage
                    position -= extra
                    eq -= loss
                    debit = position - eq
                    liquidation_cost += loss
                    margin_calls += 1
                    if eq <= 0:
                        deficit = max(-eq, 0.0)
                        equity_curve[t + 1:] = 0.0
                        ruin_day = t
                        break

        # 5. scheduled rebalance puts the account back on target, at a cost
        if _rebalance_due(t, position / eq, account):
            ceiling = min(account.leverage, 1 / m if m else np.inf,
                          account.max_leverage if account.max_leverage is not None else np.inf)
            # Exact self-financing trade, with the target measured AFTER costs.
            direction = 1 if ceiling * eq >= position else -1
            c = account.rebalance_cost
            target = ceiling * (eq + direction * c * position) / (1 + direction * c * ceiling)
            direction = -1 if position - eq > account.max_loan else 1
            loan_cap_position = (eq + direction * c * position + account.max_loan) / (1 + direction * c)
            target = max(0.0, min(target, loan_cap_position))
            traded = abs(target - position)
            cost = traded * account.rebalance_cost
            eq -= cost
            rebalance_cost_paid += cost
            traded_notional += traded
            rebalances += 1
            position = target
            debit = position - eq

        equity_curve[t + 1] = eq
        position_curve[t + 1] = position
        final_position = position

    stats = summarise(equity_curve, n_days=n, contributions=contributions, gross_contributions=deposits)
    stats.update(
        leverage=account.leverage,
        rebalance=account.rebalance,
        interest_paid=interest_paid,
        interest_pct_of_start=interest_paid / account.equity,
        monthly_contribution=account.monthly_contribution,
        liquidation_cost=liquidation_cost,
        margin_calls=margin_calls,
        rebalances=rebalances,
        traded_notional=traded_notional,
        rebalance_cost_paid=rebalance_cost_paid,
        ruin_day=ruin_day,
        ruin_deficit=deficit,
        terminal_net_equity=equity_curve[-1] - deficit,
        withdrawals_paid=withdrawals_paid,
        withdrawal_failures=withdrawal_failures + int(np.count_nonzero((withdrawals > 0) & ~withdrawal_attempted)),
        final_leverage=final_position / equity_curve[-1] if equity_curve[-1] > 0 else 0.0,
        max_leverage_reached=(
            float(np.nanmax(leverage_path))
            if n and not np.all(np.isnan(leverage_path))
            else np.nan
        ),
    )
    return {"stats": stats, "equity": equity_curve, "leverage_path": leverage_path,
            "position": position_curve, "cashflows": contributions}


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
