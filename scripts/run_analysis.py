#!/usr/bin/env python3
"""Run the whole study and write every table and chart into ``results/``.

    python scripts/run_analysis.py [--refresh] [--paths 4000]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import backtest, bootstrap, data, kelly, margin, optimal, viz

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

LEVERAGES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]
BORROW_SPREAD = 0.0150  # IBKR Pro first tier, i.e. the retail-sized loan
CRISES = {
    "dot-com bust": ("2000-01-01", "2003-01-01"),
    "global financial crisis": ("2007-10-01", "2009-04-01"),
    "covid crash": ("2020-02-01", "2020-05-01"),
    "2022 rate shock": ("2022-01-01", "2023-01-01"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download source data")
    ap.add_argument("--paths", type=int, default=4000, help="bootstrap paths")
    args = ap.parse_args()

    RESULTS.mkdir(exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    facts: dict[str, object] = {}

    # ------------------------------------------------------------------ data
    live = data.build_dataset("SPMO", refresh=args.refresh)
    extended, fit = data.extend_with_proxy("SPMO", "SPY", refresh=args.refresh)
    no_alpha = extended.copy()
    no_alpha["ret"] = extended["ret"] - fit["alpha_daily"] * extended["is_synthetic"]

    bm_now = float(live["bm"].iloc[-1])
    facts["benchmark_rate_now"] = bm_now
    facts["proxy_fit"] = fit
    facts["live_window"] = [str(live.index[0].date()), str(live.index[-1].date())]
    facts["extended_window"] = [
        str(extended.index[0].date()),
        str(extended.index[-1].date()),
    ]
    facts["synthetic_share"] = float(extended["is_synthetic"].mean())
    facts["worst_day"] = float(live["ret"].min())

    rates = pd.DataFrame(
        margin.rate_table(bm_now), columns=["loan_usd", "blended_annual_rate"]
    )
    rates.to_csv(RESULTS / "ibkr_rate_table.csv", index=False)
    facts["rate_table"] = rates.to_dict("records")

    # ------------------------------------------------- historical leverage sweeps
    live_sweep, _ = backtest.sweep(live, LEVERAGES, rebalance="monthly")
    live_sweep.to_csv(RESULTS / "sweep_spmo_live.csv")

    ext_sweep, ext_curves = backtest.sweep(extended, LEVERAGES, rebalance="monthly")
    ext_sweep.to_csv(RESULTS / "sweep_spmo_extended.csv")

    noalpha_sweep, _ = backtest.sweep(no_alpha, LEVERAGES, rebalance="monthly")
    noalpha_sweep.to_csv(RESULTS / "sweep_spmo_extended_no_alpha.csv")

    schedules = []
    for schedule in ("daily", "weekly", "monthly", "quarterly", "band", "never"):
        table, _ = backtest.sweep(extended, LEVERAGES, rebalance=schedule)
        table = table.assign(schedule=schedule).reset_index()
        schedules.append(table)
    schedule_table = pd.concat(schedules, ignore_index=True)
    schedule_table.to_csv(RESULTS / "rebalance_schedules.csv", index=False)

    # Both schedules in every crisis window. The two fail in different regimes and
    # only the real episodes show it: rebalancing to target sells into a decline and
    # so delevers, while a static loan lets leverage ratchet up as equity falls.
    crisis_rows = []
    for name, (start, end) in CRISES.items():
        window = extended.loc[start:end]
        for schedule in ("monthly", "never"):
            table, _ = backtest.sweep(window, LEVERAGES, rebalance=schedule)
            crisis_rows.append(
                table.assign(
                    episode=name,
                    schedule=schedule,
                    start=str(window.index[0].date()),
                    end=str(window.index[-1].date()),
                ).reset_index()
            )
    crisis_table = pd.concat(crisis_rows, ignore_index=True)
    crisis_table.to_csv(RESULTS / "crisis_episodes.csv", index=False)

    # --------------------------------------------------------------- Kelly
    kelly_rows, growth_grids = [], {}
    samples = {
        "SPMO 2015-2026": live,
        "extended 1993-2026": extended,
        "extended, alpha stripped": no_alpha,
    }
    for label, frame in samples.items():
        rets = frame["ret"].to_numpy()
        gauss = kelly.gaussian_kelly(rets, borrow_rate=bm_now + BORROW_SPREAD)
        emp = kelly.empirical_kelly(
            rets, np.full(len(rets), bm_now), borrow_spread=BORROW_SPREAD
        )
        kelly_rows.append(
            {
                "sample": label,
                "mu_arith": gauss["mu_arith"],
                "sigma": gauss["sigma"],
                "borrow_rate": gauss["borrow_rate"],
                "kelly_gaussian": gauss["f_star"],
                "kelly_empirical": emp["f_star"],
                "half_kelly_empirical": optimal.half_kelly(emp["f_star"]),
            }
        )
        growth_grids[label] = kelly.growth_curve(
            rets, np.full(len(rets), bm_now), borrow_spread=BORROW_SPREAD
        )
    kelly_table = pd.DataFrame(kelly_rows).set_index("sample")
    kelly_table.to_csv(RESULTS / "kelly_estimates.csv")

    # ----------------------------------------------------------- bootstrap
    boot_live = bootstrap.bootstrap_sweep(
        live["ret"].to_numpy(), LEVERAGES, benchmark_level=bm_now, n_paths=args.paths
    )
    boot_live.to_csv(RESULTS / "bootstrap_spmo_live.csv")

    boot_ext = bootstrap.bootstrap_sweep(
        extended["ret"].to_numpy(), LEVERAGES, benchmark_level=bm_now, n_paths=args.paths
    )
    boot_ext.to_csv(RESULTS / "bootstrap_spmo_extended.csv")

    boot_stress = bootstrap.bootstrap_sweep(
        extended["ret"].to_numpy(),
        LEVERAGES,
        benchmark_level=0.06,  # a 6% benchmark, i.e. 7.5% financing at retail size
        n_paths=args.paths,
    )
    boot_stress.to_csv(RESULTS / "bootstrap_high_rates.csv")

    # ------------------------------------------------------------- answers
    answers = optimal.summarise_answers(
        boot_ext,
        kelly_estimates={
            row["sample"]: row["kelly_empirical"] for row in kelly_rows
        },
    )
    answers.to_csv(RESULTS / "optimal_leverage_answers.csv", index=False)

    facts["growth_optimal"] = optimal.growth_optimal(boot_ext)
    facts["robust_optimal_p05"] = optimal.robust_optimal(boot_ext, "cagr_p05")
    facts["robust_optimal_p25"] = optimal.robust_optimal(boot_ext, "cagr_p25")
    facts["drawdown_budgets"] = {
        f"{limit:.0%}": optimal.drawdown_budget(boot_ext, limit)
        for limit in (-0.25, -0.30, -0.35, -0.40, -0.50)
    }
    facts["robust_optimal_high_rates"] = optimal.robust_optimal(boot_stress, "cagr_p05")

    # How much of the p05 peak is signal and how much is the bootstrap draw? The
    # location moves with the seed, so the location is not the finding -- the decline
    # above it is. Reporting this keeps the headline claim honest.
    stability = []
    for seed in (20260910, 1, 7, 99, 12345):
        table = bootstrap.bootstrap_sweep(
            extended["ret"].to_numpy(),
            LEVERAGES,
            benchmark_level=bm_now,
            n_paths=args.paths,
            seed=seed,
        )
        stability.append(
            {
                "seed": seed,
                "p05_optimal_leverage": optimal.robust_optimal(table, "cagr_p05"),
                "p05_at_1x": float(table.loc[1.0, "cagr_p05"]),
                "p05_at_1_5x": float(table.loc[1.5, "cagr_p05"]),
                "p05_at_2x": float(table.loc[2.0, "cagr_p05"]),
                "p05_at_3x": float(table.loc[3.0, "cagr_p05"]),
            }
        )
    stability_table = pd.DataFrame(stability)
    stability_table.to_csv(RESULTS / "bootstrap_seed_stability.csv", index=False)
    facts["p05_optimal_range_across_seeds"] = [
        float(stability_table["p05_optimal_leverage"].min()),
        float(stability_table["p05_optimal_leverage"].max()),
    ]

    # -------------------------------------------------------------- figures
    figures = []
    figures += viz.plot_growth_and_downside(boot_ext, FIGURES / "growth_vs_downside.png")
    figures += viz.plot_equity_curves(
        extended.index,
        {lev: ext_curves[lev][1:] for lev in (1.0, 1.5, 2.0, 3.0)},
        FIGURES / "equity_curves.png",
    )
    figures += viz.plot_kelly_curves(growth_grids, FIGURES / "kelly_growth.png")
    facts["figures"] = [str(p.relative_to(ROOT)) for p in figures]

    (RESULTS / "key_facts.json").write_text(json.dumps(facts, indent=2, default=float))

    # --------------------------------------------------------------- console
    pd.set_option("display.width", 200, "display.max_columns", 40)
    print(f"\nIBKR USD benchmark (Fed Funds): {bm_now:.2%}")
    print(f"SPMO~SPY beta {fit['beta']:.3f}, alpha {fit['alpha_daily'] * 252:.2%}/yr, R2 {fit['r2']:.3f}")
    print("\n--- bootstrap, extended history ---")
    print(
        boot_ext[
            [
                "cagr_p05",
                "cagr_median",
                "cagr_p95",
                "median_max_drawdown",
                "prob_dd_over_50",
                "prob_beat_unlevered",
            ]
        ].round(3)
    )
    print("\n--- Kelly ---")
    print(kelly_table[["mu_arith", "sigma", "kelly_gaussian", "kelly_empirical"]].round(3))
    print("\n--- what 'optimal' means ---")
    print(answers.round(2).to_string(index=False))
    print("\n--- 5th-percentile peak, stability across bootstrap seeds ---")
    print(stability_table.round(4).to_string(index=False))
    print(f"\nwrote {len(list(RESULTS.rglob('*')))} files to {RESULTS.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
