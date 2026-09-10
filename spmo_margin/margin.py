"""IBKR-style tiered margin financing and credit interest.

IBKR quotes margin loans as ``benchmark + spread``, where the benchmark tracks the
Fed Funds Effective Rate and the spread narrows as the debit balance grows. Interest
is blended across tiers (the first $100k of a loan is always charged at the most
expensive tier) and accrues on a 360-day year.

The tier *spreads* below are stable across time and across IBKR's regional entities
for USD borrowing; what moves is the benchmark. That is why the account's home
jurisdiction matters much less than people expect: a USD loan against a US-listed
ETF is priced off the USD benchmark whether the account is booked in Australia,
Hong Kong or the US.
"""

from __future__ import annotations

import numpy as np

# (inclusive upper bound of tier in USD, spread over benchmark)
IBKR_PRO_USD_TIERS: list[tuple[float, float]] = [
    (100_000.0, 0.0150),
    (1_000_000.0, 0.0100),
    (50_000_000.0, 0.0075),
    (200_000_000.0, 0.0050),
    (np.inf, 0.0030),
]

IBKR_LITE_USD_TIERS: list[tuple[float, float]] = [(np.inf, 0.0250)]

MARGIN_RATE_FLOOR = 0.0075  # IBKR charges at least 0.75% on a margin loan
CREDIT_SPREAD = -0.0050     # idle cash earns roughly benchmark - 0.5%
CREDIT_THRESHOLD = 10_000.0  # no interest paid on the first $10k of cash
DAY_COUNT = 360             # IBKR accrues financing on a 360-day year

# Financing accrues every *calendar* day, but the simulation steps once per *trading*
# day (~252 a year). Dividing by DAY_COUNT at each step would therefore collect only
# 252/360 -- about 70% -- of a year's interest, and understating the cost of borrowing
# is exactly the error that makes leverage look better than it is. This divisor makes
# one trading-day step carry the interest for the 365/252 calendar days it represents.
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365
ACCRUAL_DIVISOR = DAY_COUNT * TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR


def blended_margin_rate(
    loan: float,
    benchmark: float,
    tiers: list[tuple[float, float]] = IBKR_PRO_USD_TIERS,
) -> float:
    """Annualised rate on a margin loan of ``loan`` dollars.

    The rate *rises* as the loan is paid down, because the cheap upper tiers are
    repaid first and the expensive first $100k is the last to go.
    """
    if loan <= 0:
        return 0.0
    cost = 0.0
    lower = 0.0
    for upper, spread in tiers:
        amount = min(loan, upper) - lower
        if amount <= 0:
            break
        cost += amount * max(benchmark + spread, MARGIN_RATE_FLOOR)
        lower = upper
    return cost / loan


def credit_rate(cash: float, benchmark: float) -> float:
    """Annualised rate paid on an idle cash balance (only matters for leverage < 1)."""
    if cash <= CREDIT_THRESHOLD:
        return 0.0
    paid = max(benchmark + CREDIT_SPREAD, 0.0)
    return paid * (cash - CREDIT_THRESHOLD) / cash


def rate_table(
    benchmark: float,
    loans: tuple[float, ...] = (25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000),
) -> list[tuple[float, float]]:
    """Blended rate at a few representative loan sizes, for reporting."""
    return [(loan, blended_margin_rate(loan, benchmark)) for loan in loans]
