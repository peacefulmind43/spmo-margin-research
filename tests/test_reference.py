"""The reference series must stay references: never feeding the main analysis."""
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spmo_margin import reference

ROOT = Path(__file__).resolve().parents[1]


def _imports(path):
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.name for a in node.names)
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


def test_only_the_reference_script_uses_reference_series():
    users = [p.name for p in [*(ROOT / "spmo_margin").glob("*.py"), *(ROOT / "scripts").glob("*.py")]
             if "reference" in _imports(p) or "spmo_margin.reference" in _imports(p)]
    assert users == ["reference_series.py"]


def test_monthly_levered_path_charges_financing_and_stops_at_zero():
    idx = pd.date_range("2000-01-31", periods=4, freq="ME")
    frame = pd.DataFrame({"ret": [0.0, -0.6, 0.5, 0.1], "bm": 0.03}, index=idx)
    path = reference.monthly_levered_path(frame, 2.0, spread=0.015)
    assert path.iloc[0] == pytest.approx(1 - 0.045 / 12)  # one month of interest on 1x debt
    assert (path.iloc[1:] == 0).all()  # -60% at 2x is a wipeout and stays one
    flat = reference.monthly_levered_path(frame, 1.0)
    np.testing.assert_allclose(flat, (1 + frame["ret"]).cumprod())


def test_overlap_compares_daily_and_monthly_on_the_same_footing():
    days = pd.bdate_range("2017-01-02", "2019-12-31")
    rets = pd.Series(np.random.default_rng(4).normal(0.0005, 0.01, len(days)), index=days)
    monthly = (1 + rets).resample("ME").prod() - 1
    same = reference.overlap_with_index(monthly, rets)
    assert same["correlation"] == pytest.approx(1.0)
    assert same["beta_to_index"] == pytest.approx(1.0)
