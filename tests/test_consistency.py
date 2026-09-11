"""Checks that the two simulators agree and that the margin maths is sane."""

from __future__ import annotations

import numpy as np
import pytest

from spmo_margin.backtest import Account, simulate
from spmo_margin.bootstrap import simulate_paths
from spmo_margin.kelly import gaussian_kelly
from spmo_margin.margin import (
    ACCRUAL_DIVISOR,
    TRADING_DAYS_PER_YEAR,
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
    # zero return, 2x leverage: equity falls by the compounded borrow cost alone.
    # One year is TRADING_DAYS_PER_YEAR steps, and each step must carry the interest
    # for the calendar days it stands for -- so a year costs rate * 365/360, not
    # rate * 252/360.
    n = TRADING_DAYS_PER_YEAR
    bm = 0.04
    equity0 = 10_000.0  # keeps the loan inside the first tier for the whole year
    account = Account(leverage=2.0, rebalance="never", equity=equity0)
    out = simulate(np.zeros(n), np.full(n, bm), account)

    rate = bm + 0.0150
    expected = equity0 * ((1 + rate / ACCRUAL_DIVISOR) ** n - 1)
    assert out["stats"]["interest_paid"] == pytest.approx(expected, rel=1e-6)
    assert out["stats"]["terminal_multiple"] == pytest.approx(
        1 - expected / equity0, rel=1e-6
    )


def test_tier_crossing_lowers_the_effective_cost():
    # a loan large enough to grow into tier II pays less than pure tier-I compounding
    n = TRADING_DAYS_PER_YEAR
    bm = 0.04
    account = Account(leverage=2.0, rebalance="never", equity=100_000.0)
    out = simulate(np.zeros(n), np.full(n, bm), account)

    tier1_only = 100_000 * ((1 + (bm + 0.0150) / ACCRUAL_DIVISOR) ** n - 1)
    assert out["stats"]["interest_paid"] < tier1_only


@pytest.mark.parametrize("leverage", [1.0, 1.5, 2.0, 3.0])
@pytest.mark.parametrize("rebalance", ["daily", "monthly", "never", "band"])
@pytest.mark.parametrize(
    "contribution,mode",
    [(0.0, "deleverage"), (1_000.0, "deleverage"), (1_000.0, "invest")],
)
@pytest.mark.parametrize("dip", [0.0, -0.005])
def test_vectorised_matches_scalar(leverage, rebalance, contribution, mode, dip):
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0003, 0.013, 1200)
    bm = 0.0363

    scalar = simulate(
        rets,
        np.full(len(rets), bm),
        Account(
            leverage=leverage,
            rebalance=rebalance,
            monthly_contribution=contribution,
            contribution_mode=mode,
            intraday_dip=dip,
        ),
    )
    vector = simulate_paths(
        rets[None, :],
        leverage,
        bm,
        rebalance=rebalance,
        monthly_contribution=contribution,
        contribution_mode=mode,
        intraday_dip=dip,
    )

    assert vector["cagr"][0] == pytest.approx(scalar["stats"]["cagr"], rel=1e-9)
    assert vector["max_drawdown"][0] == pytest.approx(
        scalar["stats"]["max_drawdown"], rel=1e-9
    )
    assert int(vector["margin_calls"][0]) == scalar["stats"]["margin_calls"]
    assert int(vector["rebalances"][0]) == scalar["stats"]["rebalances"]
    assert vector["terminal_equity"][0] == pytest.approx(
        scalar["equity"][-1], rel=1e-9
    )
    if contribution:
        assert vector["worst_vs_contributed"][0] == pytest.approx(
            scalar["stats"]["worst_vs_contributed"], rel=1e-9
        )


def test_contributions_are_not_counted_as_return():
    # a dead-flat market, no borrowing, and a zero benchmark so idle cash earns
    # nothing: every dollar of growth is deposits, so the time-weighted return
    # must be exactly zero even though equity triples
    n = 252
    account = Account(
        leverage=1.0, rebalance="never", equity=12_000.0, monthly_contribution=2_000.0
    )
    out = simulate(np.zeros(n), np.zeros(n), account)
    assert out["stats"]["cagr"] == pytest.approx(0.0, abs=1e-12)
    assert out["stats"]["total_contributed"] == pytest.approx(36_000.0)
    assert out["equity"][-1] == pytest.approx(36_000.0)
    assert out["stats"]["money_weighted_return"] == pytest.approx(0.0, abs=1e-6)


def test_tax_shield_reduces_financing_cost_proportionally():
    n = TRADING_DAYS_PER_YEAR
    bm = 0.04
    base = simulate(
        np.zeros(n), np.full(n, bm), Account(leverage=2.0, rebalance="never", equity=10_000.0)
    )
    shielded = simulate(
        np.zeros(n),
        np.full(n, bm),
        Account(
            leverage=2.0, rebalance="never", equity=10_000.0, interest_tax_shield=0.37
        ),
    )
    # the shield scales the rate, and the rate compounds, so the ratio of interest
    # paid is the ratio of the compounded amounts rather than a flat 0.63
    rate = bm + 0.0150
    gross = (1 + rate / ACCRUAL_DIVISOR) ** n - 1
    net = (1 + rate * 0.63 / ACCRUAL_DIVISOR) ** n - 1
    ratio = shielded["stats"]["interest_paid"] / base["stats"]["interest_paid"]
    assert ratio == pytest.approx(net / gross, rel=1e-6)
    assert ratio < 0.63  # compounding makes the shield worth slightly more


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


def test_one_year_of_financing_covers_calendar_days_not_trading_days():
    # The regression this guards: accruing rate/360 once per trading day collects
    # only 252/360 of a year's interest, understating the cost of leverage by ~30%
    # and biasing every conclusion toward more of it.
    bm, spread = 0.04, 0.0150
    equity0 = 10_000.0
    out = simulate(
        np.zeros(TRADING_DAYS_PER_YEAR),
        np.full(TRADING_DAYS_PER_YEAR, bm),
        Account(leverage=2.0, rebalance="never", equity=equity0),
    )
    simple_annual = equity0 * (bm + spread) * 365 / 360
    assert out["stats"]["interest_paid"] == pytest.approx(simple_annual, rel=0.03)

    naive = equity0 * ((1 + (bm + spread) / 360) ** TRADING_DAYS_PER_YEAR - 1)
    assert out["stats"]["interest_paid"] / naive == pytest.approx(365 / 252, rel=0.02)


def test_zero_intraday_dip_is_a_pure_close_to_close_step():
    # the two-step low-then-close walk must collapse exactly to the old behaviour
    rng = np.random.default_rng(11)
    rets = rng.normal(0.0002, 0.02, 800)
    bm = np.full(len(rets), 0.0363)
    base = simulate(rets, bm, Account(leverage=2.0, rebalance="monthly"))
    explicit = simulate(
        rets, bm, Account(leverage=2.0, rebalance="monthly", intraday_dip=0.0)
    )
    assert explicit["stats"]["cagr"] == pytest.approx(base["stats"]["cagr"], rel=1e-12)


def test_intraday_dip_creates_the_whipsaw_it_is_meant_to_model():
    # A day that dips then closes flat. At 3x, breaching a 25% requirement needs the
    # low to be worse than -1/9: equity/position = (1 + 3d)/(3(1 + d)) < 0.25 solves
    # to d < -0.111. So -15% forces a sale at the low, and the position that rides
    # back to the close is permanently smaller -- the whipsaw a close-only
    # simulation cannot see. Unlevered is untouched by the same day.
    rets = np.zeros(3)
    bm = np.full(3, 0.0363)
    flat = simulate(rets, bm, Account(leverage=3.0, rebalance="never", intraday_dip=0.0))
    whipsawed = simulate(
        rets, bm, Account(leverage=3.0, rebalance="never", intraday_dip=-0.15)
    )
    assert flat["stats"]["margin_calls"] == 0
    assert whipsawed["stats"]["margin_calls"] >= 1
    assert whipsawed["equity"][-1] < flat["equity"][-1]

    shallow = simulate(
        rets, bm, Account(leverage=3.0, rebalance="never", intraday_dip=-0.10)
    )
    assert shallow["stats"]["margin_calls"] == 0  # -10% is inside the requirement

    unlevered = simulate(
        rets, bm, Account(leverage=1.0, rebalance="never", intraday_dip=-0.15)
    )
    assert unlevered["stats"]["margin_calls"] == 0
    assert unlevered["equity"][-1] == pytest.approx(unlevered["equity"][0])


def test_synthetic_drift_does_not_depend_on_the_residual_draw():
    # Residuals supply idiosyncratic variance, not drift. If a draw's sample mean
    # leaks into the series it leaks into Kelly, which is drift/variance -- an
    # earlier version of this code moved mu by 2.3%/yr on the luck of one seed.
    from spmo_margin.data import extend_with_factors

    means, vols = [], []
    for seed in (20260910, 1, 7, 99):
        frame, _ = extend_with_factors("SPMO", include_residual=True, seed=seed)
        means.append(frame["ret"].mean())
        vols.append(frame["ret"].std())

    assert means == pytest.approx([means[0]] * len(means), rel=1e-12)
    assert np.std(vols) > 0  # the draw must still change the risk, just not the drift


def test_momentum_haircut_removes_premium_but_keeps_the_risk():
    from spmo_margin.data import extend_with_factors

    full, _ = extend_with_factors("SPMO", momentum_premium_haircut=0.0)
    stripped, _ = extend_with_factors("SPMO", momentum_premium_haircut=1.0)

    assert stripped["ret"].mean() < full["ret"].mean()
    # volatility and the left tail must survive the haircut
    assert stripped["ret"].std() == pytest.approx(full["ret"].std(), rel=0.02)
    assert stripped["ret"].min() == pytest.approx(full["ret"].min(), abs=0.01)


def test_rebalancing_is_not_free():
    # Without a cost on the notional traded, the optimal no-trade band is trivially
    # zero and any band comparison is meaningless.
    rng = np.random.default_rng(3)
    rets = rng.normal(0.0003, 0.015, 2520)
    bm = np.full(len(rets), 0.0363)

    free = simulate(
        rets, bm, Account(leverage=1.5, rebalance="daily", rebalance_cost=0.0)
    )
    costed = simulate(
        rets, bm, Account(leverage=1.5, rebalance="daily", rebalance_cost=0.0002)
    )
    assert free["stats"]["rebalance_cost_paid"] == 0.0
    assert costed["stats"]["rebalance_cost_paid"] > 0.0
    assert costed["stats"]["cagr"] < free["stats"]["cagr"]

    # a wide band trades far less often than a daily schedule
    banded = simulate(
        rets, bm, Account(leverage=1.5, rebalance="band", band=0.15)
    )
    assert banded["stats"]["rebalances"] < costed["stats"]["rebalances"]


def test_leverage_drift_formula_inverts_the_simulator():
    # drift_to() is the closed-form inverse of how leverage moves with the market.
    # Check it against the simulator rather than against itself.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from position_calculator import drift_to

    for target, bound in [(1.075, 1.129), (1.25, 1.4), (2.0, 3.0)]:
        move = drift_to(target, bound)
        # One day, that cumulative move, and financing switched off entirely --
        # spread_override is needed because the tiered rate has a 0.75% floor that
        # would otherwise accrue and shift the result in the sixth decimal.
        out = simulate(
            np.array([move]),
            np.array([0.0]),
            Account(
                leverage=target,
                rebalance="never",
                maintenance_margin=0.0,
                spread_override=0.0,
            ),
        )
        reached = out["leverage_path"][0]
        assert reached == pytest.approx(bound, rel=1e-9)


def test_crra_utility_and_refinement():
    """The optimiser's two pieces of new maths, checked against known answers."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from optimise_target import _refine, crra

    # gamma = 1 is log utility
    wealth = np.array([1.0, 2.0, 4.0])
    assert crra(wealth, 1.0) == pytest.approx(np.mean(np.log(wealth)))

    # ruin is infinitely bad under CRRA, which is the point of using it here
    assert crra(np.array([1.0, 0.0]), 2.0) == -np.inf
    assert crra(np.array([1.0, 0.0]), 1.0) == -np.inf

    # more risk aversion must prefer a certain outcome to a fair gamble on it
    certain = np.array([2.0, 2.0])
    gamble = np.array([1.0, 3.0])
    for gamma in (1.0, 1.5, 2.0):
        assert crra(certain, gamma) > crra(gamble, gamma)

    # parabolic refinement recovers the vertex of an exact parabola
    grid = np.array([1.0, 2.0, 3.0])
    peak = 2.25
    values = -((grid - peak) ** 2)
    assert _refine(grid, values) == pytest.approx(peak)

    # and falls back to the grid point when the maximum is on the boundary
    assert _refine(grid, np.array([3.0, 2.0, 1.0])) == pytest.approx(1.0)


def test_french_parser_rejects_duplicated_sections():
    """The portfolio files hold two tables under the same date stamps.

    Parsing both doubles every row, which leaves OLS coefficients untouched while
    inflating every t-statistic by sqrt(2) -- exactly the error that turns an
    insignificant alpha into a significant one. The loader must refuse.
    """
    from spmo_margin.data import load_french_factors, load_long_only_momentum

    for series in (load_french_factors(), load_long_only_momentum()):
        index = series.index
        assert index.is_unique, "duplicate dates reached a loaded series"
        assert index.is_monotonic_increasing
