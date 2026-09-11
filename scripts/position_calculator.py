#!/usr/bin/env python3
"""What a specific margin position actually costs and how far it sits from a call.

The rest of this repo answers "how much leverage". This answers "given that choice,
what am I holding" -- position size, the real blended financing bill, and the two
prices that matter: the decline that triggers a forced sale, and the decline that
takes the equity to zero.

    python scripts/position_calculator.py --equity 50000
    python scripts/position_calculator.py --equity 50000 --leverage 1.25 --benchmark 0.0363

The call and wipeout thresholds are exact, not simulated. With position ``P``, loan
``D`` and maintenance fraction ``m``, a price move of ``d`` leaves equity
``P(1+d) - D`` against position ``P(1+d)``, so:

    a call needs      d < D / (P(1 - m)) - 1
    wipeout needs     d <= D / P - 1   (which is -1/L)

Nothing here is advice, and the thresholds assume the broker acts on your closing
price with no gap. A real liquidation happens intraday, at a worse price, and can
sell more than the minimum.
"""

from __future__ import annotations

import argparse

from spmo_margin.margin import (
    ACCRUAL_DIVISOR,
    IBKR_PRO_USD_TIERS,
    TRADING_DAYS_PER_YEAR,
    blended_margin_rate,
)

DEFAULT_LEVERAGES = (1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)


def describe(
    equity: float,
    leverage: float,
    benchmark: float,
    maintenance: float,
    tax_shield: float = 0.0,
) -> dict[str, float]:
    position = equity * leverage
    loan = position - equity
    rate = blended_margin_rate(loan, benchmark, IBKR_PRO_USD_TIERS) if loan > 0 else 0.0
    effective = rate * (1.0 - tax_shield)

    # a full year of accrual, compounded the way the simulator charges it
    annual_cost = (
        loan * ((1 + effective / ACCRUAL_DIVISOR) ** TRADING_DAYS_PER_YEAR - 1)
        if loan > 0
        else 0.0
    )

    call_at = loan / (position * (1 - maintenance)) - 1 if loan > 0 else float("-inf")
    wipeout_at = loan / position - 1 if loan > 0 else float("-inf")

    return {
        "leverage": leverage,
        "position": position,
        "loan": loan,
        "gross_rate": rate,
        "effective_rate": effective,
        "annual_interest": annual_cost,
        "interest_pct_of_equity": annual_cost / equity,
        "call_at": call_at,
        "wipeout_at": wipeout_at,
        "breakeven_return": annual_cost / position if position else 0.0,
    }


def drift_to(leverage: float, target_leverage: float) -> float:
    """Cumulative market move that drifts ``leverage`` to ``target_leverage``.

    Leverage follows ``L' = L(1 + x) / (1 + Lx)`` for a cumulative move ``x``, which
    inverts in closed form. This is why a no-trade band is nearly moot at low
    leverage and urgent at high leverage: at 1.075x a 20% fall moves leverage by
    2%, while at 3x it doubles it.
    """
    numerator = target_leverage - leverage
    denominator = leverage * (1.0 - target_leverage)
    if denominator == 0:
        return float("nan")
    return numerator / denominator


def print_band(target: float, band: float) -> None:
    lower, upper = target * (1 - band), target * (1 + band)
    print(
        f"\nNo-trade band at {band:.0%} relative: rebalance only when leverage leaves"
        f"\n  [{lower:.3f}x, {upper:.3f}x]"
    )
    up = drift_to(target, upper)
    down = drift_to(target, lower)
    print(
        f"  upper bound {upper:.3f}x is reached after a cumulative move of {up:+.1%}"
        f"\n  lower bound {lower:.3f}x is reached after a cumulative move of {down:+.0%}"
    )
    print(
        "\nThe upper bound does all the work: it delevers you after a sustained"
        "\ndecline. The lower bound needs a move so large it never binds in practice,"
        "\nwhich means leverage is allowed to decay after gains and the loan is never"
        "\ntopped up. That asymmetry is deliberate."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--equity", type=float, required=True, help="account equity in USD")
    ap.add_argument(
        "--leverage",
        type=float,
        default=None,
        help="a single target; omit to print the whole ladder",
    )
    ap.add_argument(
        "--benchmark",
        type=float,
        default=0.0363,
        help="IBKR USD benchmark, i.e. Fed Funds effective (default 3.63%%)",
    )
    ap.add_argument(
        "--maintenance",
        type=float,
        default=0.25,
        help="maintenance margin fraction; Reg-T is 0.25, portfolio margin nearer 0.15",
    )
    ap.add_argument(
        "--band",
        type=float,
        default=0.05,
        help="no-trade band as a relative fraction of the target (default 5%%)",
    )
    ap.add_argument(
        "--tax-shield",
        type=float,
        default=0.0,
        help="marginal rate at which margin interest is deductible (0 if it is not)",
    )
    args = ap.parse_args()

    levels = [args.leverage] if args.leverage else list(DEFAULT_LEVERAGES)
    rows = [
        describe(args.equity, lev, args.benchmark, args.maintenance, args.tax_shield)
        for lev in levels
    ]

    print(
        f"\nEquity ${args.equity:,.0f}   benchmark {args.benchmark:.2%}   "
        f"maintenance {args.maintenance:.0%}"
        + (f"   interest deductible at {args.tax_shield:.0%}" if args.tax_shield else "")
    )
    print(
        "\n   lev     position        loan     rate    interest/yr   as % equity"
        "   margin call at   wiped out at"
    )
    print("  " + "-" * 96)
    for r in rows:
        call = "never" if r["call_at"] == float("-inf") else f"{r['call_at']:>7.1%}"
        gone = "never" if r["wipeout_at"] == float("-inf") else f"{r['wipeout_at']:>7.1%}"
        print(
            f"  {r['leverage']:>5.3f}x  ${r['position']:>9,.0f}  ${r['loan']:>9,.0f}  "
            f"{r['effective_rate']:>6.2%}   ${r['annual_interest']:>9,.0f}   "
            f"{r['interest_pct_of_equity']:>9.2%}   {call:>14}   {gone:>12}"
        )

    print(
        "\n'margin call at' is the price decline that breaches the maintenance"
        "\nrequirement; 'wiped out at' is the decline that takes equity to zero."
        "\nBoth assume a close-to-close move with no intraday gap and no rebalancing"
        "\non the way down -- a real liquidation is worse on all three counts."
    )
    if args.leverage:
        print_band(args.leverage, args.band)
    else:
        print(
            "\nFor context, this repo's conclusion is 1.0x, with half Kelly at 1.075x."
            "\nPass --leverage to also get the no-trade band for a target."
        )


if __name__ == "__main__":
    main()
