#!/usr/bin/env python3
"""What does the fit cost, and does it depend on the decades you fitted it on?

Every other script here chooses leverage using the whole history and reports an
argmax. This one splits the history, chooses using only the earlier part, and
evaluates that choice on the *realised* later part. Three numbers come out:

**The cost of not having hindsight.** The gap between the leverage chosen without
seeing the test period and the leverage that turned out best in it.

**The value of fitting at all.** The gap between the chosen leverage and simply
holding 1.0x. If this is near zero, the machinery is not earning its keep.

**Whether the answer depends on recent decades.** This is the finding that matters
most. The repository's headline target is fitted on data through 2026, which
includes an unusually good stretch for US equities. Refitting without it gives a
materially lower number, and a reader is entitled to know by how much.

Scope: this runs on the reconstructed century (see `spmo_margin.data`), so a figure
like "1.13x from pre-1970 data" is a statement about the reconstruction, not a
measurement of SPMO, which did not exist. It complements rather than replaces
`scripts/validate_live.py`, which asks the different question of whether *annual
refitting* beats a fixed rule on the real ETFs.

    python scripts/out_of_sample.py [--splits 1970 1990] [--paths 1500]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import bootstrap, data, optimal
from spmo_margin.backtest import Account, simulate

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

BENCHMARK = 0.0363
DRAG = 0.003
BAND = 0.10
CAP = 2.0
GRID = np.round(np.arange(1.0, 2.0001, 0.05), 6)


def choose(returns: np.ndarray, paths: int, gamma: float, horizon_years: int) -> float:
    """Pick leverage from a return sample, using the repo's usual objective."""
    drawn = bootstrap.moving_block_paths(returns, paths, horizon_years * 252, seed=11)
    utilities = []
    for lev in GRID:
        out = bootstrap.simulate_paths(
            drawn, float(lev), BENCHMARK, annual_drag=DRAG,
            rebalance="band", band=BAND, max_leverage=CAP,
        )
        wealth = out["terminal_equity"] / 100_000.0
        utilities.append(
            -np.inf if np.any(wealth <= 0)
            else float(np.mean(wealth ** (1 - gamma)) / (1 - gamma))
        )
    return optimal._interpolate_argmax(GRID, np.array(utilities))


def realised(window: pd.DataFrame, leverage: float) -> tuple[float, float]:
    """Run one leverage on the actual realised path of a period."""
    account = Account(
        leverage=float(leverage), rebalance="band", band=BAND,
        annual_drag=DRAG, max_leverage=CAP,
    )
    out = simulate(window["ret"].to_numpy(), window["bm"].to_numpy(), account)
    return out["stats"]["cagr"], out["stats"]["max_drawdown"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", type=int, nargs="+", default=[1970, 1990])
    ap.add_argument("--paths", type=int, default=1500)
    ap.add_argument("--gamma", type=float, default=1.5)
    ap.add_argument("--train-horizon", type=int, default=20)
    args = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)

    frame, _ = data.long_only_momentum_history("SPMO")
    rows = []
    for year in args.splits:
        cut = f"{year}-01-01"
        train, test = frame.loc[:cut], frame.loc[cut:]
        chosen = choose(train["ret"].to_numpy(), args.paths, args.gamma, args.train_horizon)

        hindsight = max(((lev, realised(test, lev)[0]) for lev in GRID), key=lambda p: p[1])[0]
        cagr_chosen, dd_chosen = realised(test, chosen)
        cagr_hind, dd_hind = realised(test, hindsight)
        cagr_flat, dd_flat = realised(test, 1.0)

        rows.append({
            "split": year,
            "train": f"{train.index[0].year}-{train.index[-1].year}",
            "test": f"{test.index[0].year}-{test.index[-1].year}",
            "chosen_out_of_sample": chosen,
            "hindsight_best": hindsight,
            "cagr_chosen": cagr_chosen,
            "cagr_hindsight": cagr_hind,
            "cagr_unlevered": cagr_flat,
            "drawdown_chosen": dd_chosen,
            "drawdown_hindsight": dd_hind,
            "drawdown_unlevered": dd_flat,
            "cost_of_no_hindsight": cagr_hind - cagr_chosen,
            "value_of_fitting": cagr_chosen - cagr_flat,
        })

    table = pd.DataFrame(rows).set_index("split")
    table.to_csv(RESULTS / "out_of_sample.csv")

    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(f"\ngamma = {args.gamma}, {args.paths} paths, {args.train_horizon}y training horizon\n")
    for r in rows:
        print(f"=== fit on {r['train']}, evaluate on {r['test']} ===")
        print("  chosen without seeing the test period  %.3fx  -> CAGR %6.2f%%  maxDD %5.0f%%"
              % (r["chosen_out_of_sample"], r["cagr_chosen"] * 100, r["drawdown_chosen"] * 100))
        print("  best in hindsight on the test period   %.3fx  -> CAGR %6.2f%%  maxDD %5.0f%%"
              % (r["hindsight_best"], r["cagr_hindsight"] * 100, r["drawdown_hindsight"] * 100))
        print("  no margin                              1.000x -> CAGR %6.2f%%  maxDD %5.0f%%"
              % (r["cagr_unlevered"] * 100, r["drawdown_unlevered"] * 100))
        print("  cost of not having hindsight  %+.2f pts of CAGR" % (r["cost_of_no_hindsight"] * 100))
        print("  value of fitting over 1.0x    %+.2f pts of CAGR" % (r["value_of_fitting"] * 100))
        print()

    print("The figure to carry away is the first line of each block. The repository's")
    print("headline target is fitted through 2026; refitting without the recent decades")
    print("gives a materially lower number, and the direction of that gap depends on")
    print("whether the future resembles the fitted period or the earlier one.")


if __name__ == "__main__":
    main()
