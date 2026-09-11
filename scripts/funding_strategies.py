#!/usr/bin/env python3
"""Does an account that keeps being funded want more leverage, or less?

This script compares funding assumptions conditional on a return model. Deposits
arrive after the intraday maintenance check, so an expected future contribution
cannot prevent an earlier liquidation in this model. Three things get measured:

1. **Contribution level against leverage.** Whether the optimal leverage moves when
   an account is being funded rather than left alone.
2. **Median against 5th percentile.** Whether the answer survives being asked about
   bad decades instead of typical ones.
3. **Funding strategy.** Deploying new cash at target leverage (which re-levers it)
   against holding the loan at a fixed number of dollars (which lets leverage decay).

    python scripts/funding_strategies.py [--paths 3000]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import bootstrap, data, viz
from spmo_margin.metrics import TRADING_DAYS

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("SPMO_RESULTS_DIR", str(ROOT / "results")))
FIGURES = RESULTS / "figures"

EQUITY0 = 100_000.0
LEVERAGES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
# Contributions are relative to initial equity; tiered financing is NOT scale-free.
CONTRIBUTION_RATES = [0.0, 0.2, 0.5, 0.8]
BENCHMARK = 0.0363
HORIZON_YEARS = 10


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=3000)
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    extended, _ = data.extend_with_factors(
        "SPMO", include_alpha=False, include_residual=True
    )
    horizon = HORIZON_YEARS * TRADING_DAYS
    paths = bootstrap.moving_block_paths(
        extended["ret"].to_numpy(), args.paths, horizon, seed=7
    )

    # ---- contribution level against leverage, at the median and the 5th percentile
    records = {}
    for rate in CONTRIBUTION_RATES:
        monthly = EQUITY0 * rate / 12
        for lev in LEVERAGES:
            out = bootstrap.simulate_paths(
                paths,
                lev,
                BENCHMARK,
                equity0=EQUITY0,
                monthly_contribution=monthly,
            )
            terminal = out["terminal_equity"]
            records.setdefault(("median", rate), {})[lev] = float(np.median(terminal))
            records.setdefault(("p05", rate), {})[lev] = float(
                np.percentile(terminal, 5)
            )
    wealth = pd.DataFrame(records).T
    wealth.index.names = ["statistic", "contribution_rate"]
    wealth.to_csv(RESULTS / "funding_leverage_vs_saving.csv")

    # ---- deploying new cash at target leverage vs holding the loan fixed
    strategies = {
        "constant leverage": ("deleverage", "monthly"),
        "no new borrowing (interest capitalised)": ("invest", "never"),
    }
    rows = []
    for name, (mode, schedule) in strategies.items():
        for lev in LEVERAGES:
            out = bootstrap.simulate_paths(
                paths,
                lev,
                BENCHMARK,
                equity0=EQUITY0,
                monthly_contribution=EQUITY0 * 0.5 / 12,
                contribution_mode=mode,
                rebalance=schedule,
            )
            rows.append(
                {
                    "strategy": name,
                    "initial_leverage": lev,
                    "cagr_p05": float(np.percentile(out["cagr"], 5)),
                    "cagr_median": float(np.median(out["cagr"])),
                    "median_max_drawdown": float(np.median(out["max_drawdown"])),
                    "prob_dd_over_50": float((out["max_drawdown"] < -0.50).mean()),
                    "p05_worst_vs_contributed": float(
                        np.percentile(out["worst_vs_contributed"], 5)
                    ),
                    "median_margin_calls": float(np.median(out["margin_calls"])),
                    # a fixed dollar loan is not the same risk with better numbers:
                    # leverage decays as the account grows, so report what was held
                    "median_mean_leverage": float(np.median(out["mean_leverage"])),
                    "median_final_leverage": float(np.median(out["final_leverage"])),
                }
            )
    funding = pd.DataFrame(rows)
    funding.to_csv(RESULTS / "funding_strategy_comparison.csv", index=False)

    figures = viz.plot_leverage_vs_saving(wealth, FIGURES / "leverage_vs_saving.png")

    pd.set_option("display.width", 200, "display.max_columns", 40)
    print(f"\n{HORIZON_YEARS}y terminal equity, ${EQUITY0:,.0f} start, {args.paths} paths\n")
    print((wealth / 1000).round(0).to_string())
    print("\n--- shape, indexed to each row's own unlevered outcome ---")
    print(wealth.div(wealth[1.0], axis=0).round(3).to_string())
    print("\n--- target leverage vs no new borrowing (interest still capitalises) ---")
    print(funding.round(3).to_string(index=False))
    print(f"\nwrote {[os.path.relpath(p.resolve(), ROOT) for p in figures]}")


if __name__ == "__main__":
    main()
