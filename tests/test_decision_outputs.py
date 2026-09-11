import importlib.util
from pathlib import Path
import numpy as np
import pytest
from spmo_margin.optimal import _interpolate_argmax
from spmo_margin.margin import credit_rate, blended_margin_rate


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nonuniform_band_grid_interpolation():
    x = np.array([.08, .10, .125, .15])
    y = -(x - .112) ** 2
    assert _interpolate_argmax(x, y) == pytest.approx(.112, abs=1e-12)


def test_ruin_is_finite_for_risk_aversion_below_one():
    crra = script("optimise_target").crra
    assert crra(np.array([0., 4.]), .5) == 2.
    assert crra(np.array([0., 4.]), 0.) == 2.
    assert crra(np.array([0., 4.]), 1.) == -np.inf


def test_calculator_does_not_claim_unlevered_stock_cannot_wipe_out():
    describe = script("position_calculator").describe
    assert describe(50000., 1., .0363, .25)["wipeout_at"] == -1.
    assert not describe(50000., 2.05, .0363, .25)["opening_feasible"]
    assert not describe(50000., 1.5, .0363, .75)["opening_feasible"]
    assert describe(50000., 0., .0363, .25)["annual_interest"] == 0.


def test_credit_interest_is_scaled_by_nav_and_large_debt_has_no_fictitious_discount():
    assert credit_rate(50000., .04, 50000.) == pytest.approx(.035 * .8 * .5)
    assert blended_margin_rate(300_000_000., .0363) > blended_margin_rate(250_000_000., .0363)
