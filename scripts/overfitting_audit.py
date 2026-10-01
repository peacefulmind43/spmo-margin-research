#!/usr/bin/env python3
"""How much the answer moves with each choice nobody can justify from the data.

An earlier version of this script itemised the biases in a *synthetic* history built
from Ken French factor loadings back to 1926. That history has been removed: every
number now comes from the published S&P 500 Momentum Index (net of SPMO's fee) and
SPMO's own prices. The record of the old audit is kept in
``docs/historical-conclusions-2026-09-10.md``.

What remains worth auditing is sensitivity, because a conclusion that moves with a
free parameter is not established:

1. **Sample.** SPMO alone, the index, the index gross of fee, and -- for reference --
   the index with financing under-charged the way an old accrual bug did.
2. **Start date.** Which decades are in the sample. Until the 1994-2016 index history
   is added this can only compare recent windows, and says so.
3. **Expected return.** Momentum is the most published anomaly there is, and
   published anomalies decay. Subtracting 1-4pp a year from every daily return
   keeps the volatility and crash risk while removing part of the payment.
4. **Bootstrap block length**, a free parameter of the resampling.

    python scripts/overfitting_audit.py [--paths 2500]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import bootstrap, data, kelly, optimal

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("SPMO_RESULTS_DIR", str(ROOT / "results")))

LEVERAGES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]
BENCHMARK = 0.0363
SPREAD = 0.0150

START_CANDIDATES = ("1994-09-16", "2000-01-01", "2008-01-01", "2016-09-01", "2020-01-01")

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
    RESULTS.mkdir(parents=True, exist_ok=True)

    history = data.momentum_index_history()
    gross = data.momentum_index_history(expense_ratio=0.0)
    live = data.build_dataset("SPMO")
    status = data.history_status(history)
    if "note" in status:
        print(f"\n*** {status['note']} ***")

    rows = [
        evaluate(live["ret"].to_numpy(), f"SPMO ETF only, {status_years(live)}", args.paths),
        evaluate(history["ret"].to_numpy(), f"index net of fee, {status_years(history)}", args.paths),
        evaluate(gross["ret"].to_numpy(), "index gross of fee", args.paths),
        evaluate(
            history["ret"].to_numpy(),
            "for reference: index, financing under-charged (old accrual bug)",
            args.paths,
            shield=UNDERCHARGE_SHIELD,
        ),
    ]
    audit = pd.DataFrame(rows).set_index("build")
    audit.to_csv(RESULTS / "overfitting_audit.csv")

    # start-date sensitivity, over whatever the published history covers
    sens = []
    for start in START_CANDIDATES:
        window = history.loc[start:]
        if history.index[0] > pd.Timestamp(start) + pd.Timedelta(days=7) or len(window) < 5 * 252:
            continue
        sens.append(evaluate(window["ret"].to_numpy(), status_years(window), args.paths))
    sensitivity = pd.DataFrame(sens).set_index("build")
    sensitivity.to_csv(RESULTS / "start_date_sensitivity.csv")

    # keep the risk, vary how much of the expected return you credit
    haircuts = []
    for cut in (0.0, 0.01, 0.02, 0.03, 0.04):
        row = evaluate(
            history["ret"].to_numpy() - cut / 252, f"expected return -{cut:.0%}/yr", args.paths
        )
        row["haircut"] = cut
        haircuts.append(row)
    haircut_table = pd.DataFrame(haircuts).set_index("haircut")
    haircut_table.to_csv(RESULTS / "return_haircut_sensitivity.csv")

    # block length is a free parameter of the bootstrap; check it is not load-bearing
    blocks = []
    for block in (5, 10, 21, 42, 63):
        table = bootstrap.bootstrap_sweep(
            history["ret"].to_numpy(),
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
    print("\n=== sample ===")
    print(audit[cols].round(3).to_string())
    print("\n=== start date ===")
    print(sensitivity[cols].round(3).to_string())
    print("\n=== expected return haircut (risk kept, payment reduced) ===")
    print(haircut_table[cols].round(3).to_string())
    print("\n=== bootstrap block length (a free parameter) ===")
    print(block_table.round(4).to_string())


def status_years(frame: pd.DataFrame) -> str:
    return f"{frame.index[0].date()} to {frame.index[-1].date()}"


if __name__ == "__main__":
    main()
