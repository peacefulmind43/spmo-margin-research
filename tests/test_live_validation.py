import numpy as np
import pandas as pd
import pytest

from spmo_margin.backtest import Account, simulate
from spmo_margin.bootstrap import simulate_paths
from spmo_margin import data
from spmo_margin.validation import ValidationConfig, causal_maintenance, select_targets


@pytest.mark.parametrize("leverage", [0., .5, 1., 1.5, 2.])
@pytest.mark.parametrize("schedule", ["never", "daily", "monthly", "band"])
@pytest.mark.parametrize("contribution", [0., 500.])
def test_cash_withdrawals_and_changing_requirements_keep_1e9_parity(leverage, schedule, contribution):
    rng = np.random.default_rng(527)
    paths = rng.normal(.0002, .025, (3, 180))
    rates = rng.uniform(-.02, .08, paths.shape)
    margin = np.full(paths.shape, .25)
    margin[:, 40:100] = .75
    margin[1, 130:] = 1.
    requests = np.zeros(paths.shape)
    requests[:, [35, 75, 165]] = [1000., 1e7, 500.]
    kwargs = dict(rebalance=schedule, max_leverage=2., equity0=50000.,
                  annual_drag=.003, borrow_surcharge=.002, max_loan=60000., monthly_contribution=contribution)
    v = simulate_paths(paths, leverage, rates, maintenance_margin=margin,
                       withdrawals=requests, **kwargs)
    for i in range(len(paths)):
        a = Account(leverage=leverage, rebalance=schedule, equity=50000., max_leverage=2.,
                    annual_drag=.003, borrow_surcharge=.002, max_loan=60000., monthly_contribution=contribution)
        s = simulate(paths[i], rates[i], a, maintenance=margin[i], withdrawals=requests[i])
        for key in ["cagr", "max_drawdown", "interest_paid", "margin_calls", "rebalances",
                    "rebalance_cost_paid", "withdrawals_paid", "withdrawal_failures", "final_leverage"]:
            assert s["stats"][key] == pytest.approx(v[key][i], rel=1e-9, abs=1e-9), key
        assert s["equity"][-1] == pytest.approx(v["terminal_equity"][i], rel=1e-9, abs=1e-9)
        assert s["position"][-1] == pytest.approx(v["terminal_position"][i], rel=1e-9, abs=1e-9)
        assert s["stats"]["total_contributed"] == pytest.approx(v["total_contributed"][i], rel=1e-9, abs=1e-9)
        assert s["stats"]["worst_vs_contributed"] == pytest.approx(v["worst_vs_contributed"][i], rel=1e-9, abs=1e-9)


def test_zero_stock_account_survives_and_withdrawal_is_not_a_loss():
    s = simulate(np.zeros(3), np.zeros(3), Account(leverage=0., equity=5000.),
                 withdrawals=[1000., 0., 500.])
    assert s["equity"][-1] == 3500.
    assert not s["stats"]["wiped_out"]
    assert s["stats"]["cagr"] == 0.
    assert s["stats"]["withdrawals_paid"] == 1500.


def test_infeasible_withdrawal_is_unpaid_and_explicit():
    s = simulate(np.zeros(2), np.zeros(2), Account(leverage=1., equity=5000.),
                 withdrawals=[6000., 0.])
    assert s["stats"]["withdrawal_failures"] == 1
    assert s["stats"]["withdrawals_paid"] == 0.
    assert s["equity"][-1] == 5000.


def test_same_day_deposit_and_withdrawal_keep_gross_funding():
    s = simulate(np.zeros(2), 0., Account(leverage=0., equity=5000., monthly_contribution=500.),
                 withdrawals=[500., 0.])
    assert s["stats"]["cagr"] == 0.
    assert s["stats"]["total_contributed"] == 5500.
    assert s["equity"][-1] == 5000.


def test_gap_deficit_is_reported_instead_of_forgiving_the_remaining_debt():
    r = np.array([-.8, 0.])
    s = simulate(r, 0., Account(leverage=2., equity=5000., interest_tax_shield=1.))
    v = simulate_paths(r[None, :], 2., 0., equity0=5000., interest_tax_shield=1.)
    for result in [s["stats"], {k: a[0] for k, a in v.items()}]:
        assert result["ruin_deficit"] == pytest.approx(3000., abs=1e-9)
        assert result["terminal_net_equity"] == pytest.approx(-3000., abs=1e-9)


def test_investing_contributions_pays_actual_purchase_cost():
    a = Account(leverage=1., equity=5000., monthly_contribution=1000.,
                contribution_mode="invest", rebalance="never", rebalance_cost=.01)
    s = simulate(np.zeros(1), 0., a)
    v = simulate_paths(np.zeros((1, 1)), 1., 0., equity0=5000., monthly_contribution=1000.,
                       contribution_mode="invest", rebalance="never", rebalance_cost=.01)
    assert s["equity"][-1] == pytest.approx(5000. + 1000. / 1.01, abs=1e-9)
    assert s["equity"][-1] == pytest.approx(v["terminal_equity"][0], abs=1e-9)
    assert s["stats"]["total_contributed"] == 6000.


def test_block_sampler_includes_last_observation_and_whole_sample_block():
    from spmo_margin.bootstrap import moving_block_paths
    sample = np.array([1., 2., 3., 9.])
    paths = moving_block_paths(sample, 100, 2, block=2, seed=1)
    assert 9. in paths
    np.testing.assert_array_equal(moving_block_paths(sample, 1, 4, block=4)[0], sample)


def test_withdrawal_on_and_after_ruin_is_not_ignored():
    r = np.array([-.8, .1])
    a = Account(leverage=2., equity=5000.)
    s = simulate(r, np.zeros(2), a, withdrawals=10.)
    v = simulate_paths(r[None, :], 2., 0., equity0=5000., withdrawals=10.)
    assert s["stats"]["withdrawal_failures"] == v["withdrawal_failures"][0] == 2


def test_rebalance_cannot_repurchase_an_illegal_position_after_requirement_increase():
    s = simulate(np.zeros(2), np.zeros(2), Account(leverage=1.5, rebalance="daily"),
                 maintenance=[.25, .75])
    assert s["stats"]["margin_calls"] > 0
    assert s["position"][-1] <= s["equity"][-1] / .75 + 1e-9


def test_forced_sale_is_self_financing_including_slippage():
    s = simulate(np.array([-.2]), np.array([0.]),
                 Account(leverage=3., equity=100000., spread_override=0., rebalance="never"))
    sold = 240000. - s["position"][-1]
    assert s["equity"][-1] == pytest.approx(40000. - sold * .001, abs=1e-9)
    assert s["equity"][-1] / s["position"][-1] == pytest.approx(.25, abs=1e-9)


def test_opening_limit_is_enforced_and_loan_limit_survives_rebalances():
    with pytest.raises(ValueError, match="opening limit"):
        simulate(np.zeros(3), np.zeros(3), Account(leverage=2.05, max_leverage=2.))
    for impl in ["scalar", "vector"]:
        if impl == "scalar":
            o = simulate(np.full(30, .02), np.zeros(30),
                         Account(leverage=2., equity=50000., max_loan=50000., rebalance="daily"))
            debit = o["position"][-1] - o["equity"][-1]
        else:
            o = simulate_paths(np.full((1, 30), .02), 2., 0., equity0=50000.,
                               max_loan=50000., rebalance="daily")
            debit = o["terminal_position"][0] - o["terminal_equity"][0]
        assert debit <= 50000. + 1e-9


def test_continuing_an_account_does_not_reset_its_loan_or_leverage():
    r = np.random.default_rng(9).normal(.0002, .015, 400)
    settings = dict(leverage=1.75, rebalance="band", band=.1, max_leverage=2.)
    whole = simulate(r, .0363, Account(**settings))
    first = simulate(r[:173], .0363, Account(**settings))
    second = simulate(r[173:], .0363, Account(**settings, equity=first["equity"][-1]),
                      position0=first["position"][-1])
    assert whole["equity"][-1] == pytest.approx(second["equity"][-1], rel=1e-9, abs=1e-9)
    v = simulate_paths(r[None, 173:], 1.75, .0363, rebalance="band", band=.1,
                       equity0=first["equity"][-1], position0=first["position"][-1], max_leverage=2.)
    assert second["equity"][-1] == pytest.approx(v["terminal_equity"][0], rel=1e-9, abs=1e-9)


def test_future_data_cannot_change_training_fit_or_selected_target(monkeypatch):
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2008-01-01", periods=3400)
    f = pd.DataFrame({"mkt_rf": rng.normal(.0002, .01, len(dates)),
                      "mom": rng.normal(.0001, .005, len(dates)), "rf": .00005}, index=dates)
    p = pd.Series(100 * np.cumprod(1 + .9 * f.mkt_rf.iloc[800:] + .3 * f.mom.iloc[800:]
                                 + rng.normal(0, .003, len(dates) - 800)))
    b = pd.Series(.03, index=dates)
    monkeypatch.setattr(data, "load_total_return", lambda *a, **k: p)
    monkeypatch.setattr(data, "load_french_factors", lambda *a, **k: f)
    monkeypatch.setattr(data, "load_benchmark_rate", lambda *a, **k: b)
    cutoff = dates[2300]
    before, fit_before = data.extend_with_factors(as_of=cutoff)
    config = ValidationConfig(paths=4, forecast_years=1, grid=(1., 2.))
    selected_before, _ = select_targets(before, config, 50000.)
    p.loc[p.index > cutoff] *= 10_000.
    f.loc[f.index > cutoff, ["mkt_rf", "mom"]] = .5
    b.loc[b.index > cutoff] = .99
    after, fit_after = data.extend_with_factors(as_of=cutoff)
    pd.testing.assert_frame_equal(before, after, check_exact=True)
    assert fit_before == fit_after
    assert after.index.max() <= cutoff
    assert select_targets(after, config, 50000.)[0] == selected_before


def test_maintenance_stress_uses_previous_close():
    px = pd.Series([100., 60., 80.], index=pd.bdate_range("2020-01-01", periods=3))
    m = causal_maintenance(px, ValidationConfig())
    assert list(m) == [.25, .25, .50]


def test_walk_forward_counts_spending_failures_in_years_after_ruin(monkeypatch):
    from spmo_margin import validation
    dates = pd.to_datetime(["2018-11-01", "2018-12-01", "2019-01-02", "2019-02-01",
                            "2020-01-02", "2020-02-03"])
    px = pd.Series([100., 100., 20., 20., 20., 20.], index=dates)
    monkeypatch.setattr(data, "load_total_return", lambda *a, **k: px)
    monkeypatch.setattr(data, "load_benchmark_rate", lambda *a, **k: pd.Series(0., index=dates))
    monkeypatch.setattr(data, "load_french_factors", lambda *a, **k: pd.DataFrame(index=dates))

    def training(*args, as_of=None):
        return pd.DataFrame({"ret": 0., "bm": 0.}, index=dates[dates <= as_of]), {
            "window": ("2018-11-01", str(as_of.date()))}

    monkeypatch.setattr(data, "extend_with_factors", training)
    monkeypatch.setattr(validation, "select_targets", lambda *a: ({}, pd.DataFrame()))
    cfg = ValidationConfig(tickers=("SPMO",), first_test_year=2019, last_test_year=2020,
                           min_live_days=1, monthly_withdrawal=10.)
    folds, _, summary, _, curves = validation.walk_forward(cfg)
    ruined = summary[summary.policy == "fixed_2x"].iloc[0]
    assert ruined.withdrawal_failures == 4
    assert ruined.withdrawals_paid == 0.
    assert ruined.ruin_deficit > 0.
    assert ruined.terminal_net_equity == -ruined.ruin_deficit
    assert folds[(folds.policy == "fixed_2x") & (folds.year == 2020)].iloc[0].withdrawal_failures == 2
    account = curves[curves.policy == "fixed_2x"]
    assert len(account) == 4
    assert (account.equity == 0).all()
