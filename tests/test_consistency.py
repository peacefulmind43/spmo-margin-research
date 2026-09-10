"""Checks that the two simulators agree and that the margin maths is sane."""

from __future__ import annotations

import numpy as np
import pytest

from spmo_margin.backtest import Account, simulate
from spmo_margin.bootstrap import simulate_paths
from spmo_margin.kelly import gaussian_kelly
from spmo_margin.margin import (
    DAY_COUNT,
    IBKR_PRO_USD_TIERS,
    blended_margin_rate,
)


def test_blended_rate_first_tier():
    # $50k sits entirely in the top tier: benchmark + 1.50%
    assert blended_margin_rate(50_000, 0.0363) == pytest.approx(0.0363 + 0.0150)


def test_blended_rate_is_weighted_average_across_tiers():
    bm = 0.04
    rate = blended_margin_rate(200_000, bm)
    expected = (100_000 * (bm + 0.0150) + 100_000 * (bm + 0.0100)) / 200_000
    assert rate == pytest.approx(expected)


def test_blended_rate_falls_as_loan_grows():
    bm = 0.0363
    rates = [blended_margin_rate(x, bm) for x in (50_000, 200_000, 2_000_000)]
    assert rates[0] > rates[1] > rates[2]


def test_blended_rate_respects_floor():
    # benchmark of zero would give 0% in the deepest tier; the floor is 0.75%
    assert blended_margin_rate(100_000_000_000, 0.0) >= 0.0075


def test_unlevered_account_compounds_the_raw_return():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0004, 0.01, 500)
    out = simulate(rets, np.full(500, 0.04), Account(leverage=1.0, rebalance="monthly"))
    assert out["stats"]["terminal_multiple"] == pytest.approx(np.prod(1 + rets))


def test_leverage_costs_exactly_the_interest_on_a_flat_market():
    # zero return, 2x leverage: equity falls by the compounded borrow cost alone
    n = DAY_COUNT
    bm = 0.04
    equity0 = 10_000.0  # keeps the loan inside the first tier for the whole year
    account = Account(leverage=2.0, rebalance="never", equity=equity0)
    out = simulate(np.zeros(n), np.full(n, bm), account)

    rate = bm + 0.0150
    expected = equity0 * ((1 + rate / DAY_COUNT) ** DAY_COUNT - 1)
    assert out["stats"]["interest_paid"] == pytest.approx(expected, rel=1e-6)
    assert out["stats"]["terminal_multiple"] == pytest.approx(
        1 - expected / equity0, rel=1e-6
    )


def test_tier_crossing_lowers_the_effective_cost():
    # a loan large enough to grow into tier II pays less than pure tier-I compounding
    n = DAY_COUNT
    bm = 0.04
    account = Account(leverage=2.0, rebalance="never", equity=100_000.0)
    out = simulate(np.zeros(n), np.full(n, bm), account)

    tier1_only = 100_000 * ((1 + (bm + 0.0150) / DAY_COUNT) ** DAY_COUNT - 1)
    assert out["stats"]["interest_paid"] < tier1_only


@pytest.mark.parametrize("leverage", [1.0, 1.5, 2.0, 3.0])
@pytest.mark.parametrize("rebalance", ["daily", "monthly", "never"])
def test_vectorised_matches_scalar(leverage, rebalance):
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0003, 0.013, 1200)
    bm = 0.0363

    scalar = simulate(rets, np.full(len(rets), bm), Account(leverage=leverage, rebalance=rebalance))
    vector = simulate_paths(rets[None, :], leverage, bm, rebalance=rebalance)

    assert vector["cagr"][0] == pytest.approx(scalar["stats"]["cagr"], rel=1e-9)
    assert vector["max_drawdown"][0] == pytest.approx(
        scalar["stats"]["max_drawdown"], rel=1e-9
    )
    assert int(vector["margin_calls"][0]) == scalar["stats"]["margin_calls"]


def test_crash_wipes_out_high_leverage_but_not_low():
    # a single -40% day: 3x is gone, 1x is merely bruised
    rets = np.array([-0.40])
    bm = np.array([0.04])
    assert simulate(rets, bm, Account(leverage=3.0))["stats"]["wiped_out"]
    assert not simulate(rets, bm, Account(leverage=1.0))["stats"]["wiped_out"]


def test_maintenance_breach_triggers_liquidation():
    # 3x into a -20% day: equity/position falls under 25%, forcing a sale
    out = simulate(np.array([-0.20]), np.array([0.04]), Account(leverage=3.0))
    assert out["stats"]["margin_calls"] == 1
    assert out["stats"]["liquidation_cost"] > 0


def test_gaussian_kelly_matches_closed_form():
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0005, 0.011, 5000)
    out = gaussian_kelly(rets, borrow_rate=0.05)
    assert out["f_star"] == pytest.approx(
        (out["mu_arith"] - 0.05) / out["sigma"] ** 2, rel=1e-12
    )
