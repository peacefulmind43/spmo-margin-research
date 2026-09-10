#!/usr/bin/env python3
"""What each modelling bias was worth, in turns of leverage.

The first version of this study concluded ~1.5x. Three separate biases were holding
it up, and -- as is almost always the case -- none of them pointed in a random
direction. Every one made leverage look better:

1. **An in-sample alpha projected across history.** SPMO's 4.65%/yr over SPY was
   measured over the ETF's entire short life and then applied to decades it never
   traded through. Regressed properly on the market *and momentum* factors, the
   loading on momentum is 0.32 and the residual alpha is 3.3%/yr with a t-statistic
   of 1.2 -- indistinguishable from zero. An ETF built to hold a momentum index
   earning the momentum premium is not alpha, and it is not free.
2. **Idiosyncratic risk discarded.** The SPY beta map has an R-squared of 0.71, so
   29% of SPMO's variance was thrown away when synthesising history. Kelly scales
   with 1/sigma**2, so deleting variance directly inflates the answer.
3. **Financing under-charged by 30%.** Interest accrued once per *trading* day on a
   360-day basis collects 252/360 of a year's cost. Real financing accrues every
   calendar day.

This script removes them one at a time so the cost of each is visible. Run it before
trusting any leverage number in this repo.

    python scripts/overfitting_audit.py [--paths 2500]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import bootstrap, data, kelly, optimal

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

LEVERAGES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]
BENCHMARK = 0.0363
SPREAD = 0.0150

# Abusing the tax shield to emulate the accrual bug: the old code multiplied the
# effective rate by 252/365, and the shield multiplies it by (1 - shield).
UNDERCHARGE_SHIELD = 1.0 - 252.0 / 365.0


def evaluate(
    returns: np.ndarray,
    label: str,
    paths: int,
    shield: float = 0.0,
) -> dict[str, object]:
    empirical = kelly.empirical_kelly(
        returns,
        np.full(len(returns), BENCHMARK),
        borrow_spread=SPREAD * (1.0 - shield),
    )
    table = bootstrap.bootstrap_sweep(
        returns,
        LEVERAGES,
        benchmark_level=BENCHMARK,
        n_paths=paths,
        interest_tax_shield=shield,
    )
    return {
        "build": label,
        "mu_arith": float(returns.mean() * 252),
        "sigma": float(returns.std(ddof=1) * np.sqrt(252)),
        "full_kelly": empirical["f_star"],
        "half_kelly": empirical["f_star"] / 2,
        "p05_optimal": optimal.robust_optimal(table, "cagr_p05"),
        "median_optimal": optimal.growth_optimal(table),
        "p05_cagr_at_1x": float(table.loc[1.0, "cagr_p05"]),
        "p05_cagr_at_1_5x": float(table.loc[1.5, "cagr_p05"]),
        "median_cagr_at_1_5x": float(table.loc[1.5, "cagr_median"]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=2500)
    args = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)

    spy_build, spy_fit = data.extend_with_proxy("SPMO", "SPY")
    factor_alpha, factor_fit = data.extend_with_factors(
        "SPMO", include_alpha=True, include_residual=True
    )
    factor_clean, _ = data.extend_with_factors(
        "SPMO", include_alpha=False, include_residual=True
    )
    factor_no_resid, _ = data.extend_with_factors(
        "SPMO", include_alpha=False, include_residual=False
    )

    spy_no_alpha = spy_build["ret"] - spy_fit["alpha_daily"] * spy_build["is_synthetic"]

    rows = [
        evaluate(
            spy_build["ret"].to_numpy(),
            "1. as originally shipped (SPY map, in-sample alpha, under-charged)",
            args.paths,
            shield=UNDERCHARGE_SHIELD,
        ),
        evaluate(
            spy_build["ret"].to_numpy(),
            "2. financing charged for calendar days",
            args.paths,
        ),
        evaluate(
            spy_no_alpha.to_numpy(),
            "3. in-sample alpha removed",
            args.paths,
        ),
        evaluate(
            factor_no_resid["ret"].to_numpy(),
            "4. factor-built history back to 1926, no residual risk",
            args.paths,
        ),
        evaluate(
            factor_clean["ret"].to_numpy(),
            "5. idiosyncratic risk restored (the honest build)",
            args.paths,
        ),
        evaluate(
            factor_alpha["ret"].to_numpy(),
            "for reference: honest build with the alpha believed",
            args.paths,
        ),
    ]
    audit = pd.DataFrame(rows).set_index("build")
    audit.to_csv(RESULTS / "overfitting_audit.csv")

    # start-date sensitivity: how much rests on including the Great Depression?
    windows = {
        "1926-2026 (all)": "1926-01-01",
        "1946-2026 (post-war)": "1946-01-01",
        "1970-2026": "1970-01-01",
        "1990-2026": "1990-01-01",
    }
    sens = [
        evaluate(factor_clean.loc[start:, "ret"].to_numpy(), label, args.paths)
        for label, start in windows.items()
    ]
    sensitivity = pd.DataFrame(sens).set_index("build")
    sensitivity.to_csv(RESULTS / "start_date_sensitivity.csv")

    # block length is a free parameter of the bootstrap; check it is not load-bearing
    blocks = []
    for block in (5, 10, 21, 42, 63):
        table = bootstrap.bootstrap_sweep(
            factor_clean["ret"].to_numpy(),
            LEVERAGES,
            benchmark_level=BENCHMARK,
            n_paths=args.paths,
            block=block,
        )
        blocks.append(
            {
                "block_days": block,
                "p05_optimal": optimal.robust_optimal(table, "cagr_p05"),
                "median_optimal": optimal.growth_optimal(table),
                "p05_cagr_at_1_5x": float(table.loc[1.5, "cagr_p05"]),
            }
        )
    block_table = pd.DataFrame(blocks).set_index("block_days")
    block_table.to_csv(RESULTS / "block_length_sensitivity.csv")

    pd.set_option("display.width", 240, "display.max_columns", 40)
    cols = ["mu_arith", "sigma", "full_kelly", "half_kelly", "p05_optimal", "median_optimal"]
    print("\n=== what each bias was worth ===")
    print(audit[cols].round(3).to_string())
    print("\n=== does the answer depend on including the Great Depression? ===")
    print(sensitivity[cols].round(3).to_string())
    print("\n=== bootstrap block length (a free parameter) ===")
    print(block_table.round(4).to_string())
    print(f"\nSPMO on market + momentum: {factor_fit}")


if __name__ == "__main__":
    main()
