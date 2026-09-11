"""Pins the owner's chosen operating rule from docs/operating-rule.md.

This is not a claim that 1.500x is validated -- the README is right that it is not.
It guards against the rule's stated numbers and the engine drifting apart silently,
which is the failure mode that matters once a rule is being operated: the document
says one thing and the code does another, and nobody notices.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from spmo_margin.bootstrap import simulate_paths
from spmo_margin.margin import IBKR_PRO_USD_TIERS, blended_margin_rate

TARGET = 1.500
LOWER, UPPER = 1.300, 1.700
BAND = (UPPER - LOWER) / 2 / TARGET  # the band as a relative fraction

DOC = Path(__file__).resolve().parents[1] / "docs" / "operating-rule.md"


def test_document_states_the_same_rule_as_this_test():
    text = DOC.read_text()
    assert re.search(r"target\s+1\.500x", text)
    assert re.search(r"rebalance band\s+\(1\.300x, 1\.700x\)", text)


def test_band_lies_inside_the_one_standard_error_confidence_set():
    """The band's justification is that it matches the target's confidence set.

    If the band were ever widened past the set, it would stop tracking the target;
    if narrowed far inside it, it would be paying to defend precision that does not
    exist. The documented set is 1.250x-1.725x.
    """
    assert 1.250 <= LOWER < TARGET < UPPER <= 1.725


def test_financing_assumption_matches_the_documented_rate():
    # 3.63% benchmark plus the 1.50% first tier, no entity surcharge
    assert blended_margin_rate(25_000, 0.0363, IBKR_PRO_USD_TIERS) == pytest.approx(0.0513)


def test_rule_runs_and_stays_within_its_stated_risk():
    """A cheap smoke run: the rule must remain feasible and not silently get riskier.

    Bounds are loose on purpose -- this catches an engine change that alters the
    rule's character, not Monte Carlo wobble.
    """
    rng = np.random.default_rng(3)
    # 12% drift, 19% vol -- near the reconstructed history, without loading data
    paths = rng.normal(0.12 / 252, 0.19 / np.sqrt(252), size=(400, 10 * 252))
    out = simulate_paths(
        paths,
        TARGET,
        0.0363,
        equity0=50_000.0,
        annual_drag=0.003,
        rebalance="band",
        band=BAND,
        max_leverage=2.0,
    )
    assert out["wiped_out"].mean() == 0.0
    held = np.median(out["mean_leverage"])
    assert LOWER < held < UPPER, "mean leverage held must sit inside the band"
    assert np.median(out["rebalances"]) < 10 * 252 / 21, "band should trade less than monthly"


def test_out_of_sample_split_is_honest_about_direction():
    """The split test must report both sides of the hindsight gap.

    Its finding cuts against this repository's own headline: fitting without the
    recent decades gives a lower target. A version of the script that only reported
    the value of fitting, and not the cost of lacking hindsight, would be the
    flattering half of the result.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import out_of_sample as oos

    # the grid must span the whole decision range, or an argmax can hide at an edge
    assert oos.GRID.min() == pytest.approx(1.0)
    assert oos.GRID.max() == pytest.approx(2.0)
    # and the cost of lacking hindsight must be derived, not assumed away
    src = (Path(oos.__file__)).read_text()
    assert "cost_of_no_hindsight" in src
    assert "value_of_fitting" in src


def test_split_test_reproduces_its_published_direction():
    """Fitting on the earlier century must choose below the headline 1.500x.

    This is the substantive claim the script exists to support. It is checked with
    few paths, so only the direction is asserted, not the figure.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import out_of_sample as oos
    from spmo_margin import data

    frame, _ = data.long_only_momentum_history("SPMO")
    chosen = oos.choose(frame.loc[:"1990-01-01"]["ret"].to_numpy(), 200, 1.5, 20)
    assert 1.0 <= chosen < TARGET, "pre-1990 data should choose below the headline target"
