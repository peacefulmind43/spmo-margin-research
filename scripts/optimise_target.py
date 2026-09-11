#!/usr/bin/env python3
"""Conditional in-sample leverage and band optimisation, not a live sizing rule.

"Optimal" is not a property of the data, it is a property of an objective. This
script states two objectives precisely and solves each on the simulated 40-year
paths, so the number that comes out is an argmax rather than a round figure read off
a table:

**CRRA expected utility.** Maximise ``E[W^(1-gamma) / (1-gamma)]`` on terminal
wealth, with ``gamma = 1`` being log utility (identical to Kelly) and higher values
more risk averse. Run on the simulated paths rather than the closed form, so fat
tails, tiered financing, forced liquidation and the path-dependence of rebalancing
are all priced in.

**Drawdown-constrained growth.** Maximise median CAGR subject to
``P(max drawdown worse than -70%) <= threshold``. This is a separate declared
preference and must not silently replace the user's growth objective.

The band is then optimised against the *same* objective, because choosing a target
on one criterion and a band on another is how you end up with a number nobody can
defend.

    python scripts/optimise_target.py [--paths 3000] [--horizon 40] [--gamma 1.5]

Interpolation precision is not estimation precision. This script does not compute
a confidence interval or correct for ticker selection and repeated research.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import bootstrap, data, optimal

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("SPMO_RESULTS_DIR", str(ROOT / "results")))

BENCHMARK = 0.0363
DRAWDOWN_LIMIT = -0.70


def crra(wealth: np.ndarray, gamma: float) -> float:
    """Expected CRRA utility of terminal wealth, in multiples of starting equity."""
    if gamma < 0 or not np.isfinite(gamma) or not np.isfinite(wealth).all() or np.any(wealth < 0):
        raise ValueError("nonnegative finite wealth and risk aversion required")
    if gamma >= 1 and np.any(wealth == 0):
        return -np.inf
    if gamma == 1.0:
        return float(np.mean(np.log(wealth)))
    return float(np.mean(wealth ** (1.0 - gamma)) / (1.0 - gamma))


def _refine(grid: np.ndarray, values: np.ndarray) -> float:
    """Parabolic interpolation through the best grid point and its neighbours."""
    return optimal._interpolate_argmax(grid, values)


def evaluate_grid(
    paths: np.ndarray,
    grid: np.ndarray,
    equity0: float = 100_000.0,
    **sim_kwargs,
) -> pd.DataFrame:
    rows = []
    for lev in grid:
        out = bootstrap.simulate_paths(paths, float(lev), BENCHMARK, equity0=equity0, **sim_kwargs)
        rows.append(
            {
                "leverage": float(lev),
                "wealth": out["terminal_equity"] / equity0,
                "median_cagr": float(np.median(out["cagr"])),
                "p05_cagr": float(np.percentile(out["cagr"], 5)),
                "prob_deep_drawdown": float((out["max_drawdown"] < DRAWDOWN_LIMIT).mean()),
                "prob_ruin": float((out["terminal_equity"] <= 0).mean()),
                "mean_leverage": float(np.median(out["mean_leverage"])),
            }
        )
    return pd.DataFrame(rows).set_index("leverage")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=3000)
    ap.add_argument("--horizon", type=int, default=40, help="holding period in years")
    ap.add_argument("--gamma", type=float, default=1.5, help="relative risk aversion")
    ap.add_argument("--dd-threshold", type=float, default=1 / 3)
    ap.add_argument(
        "--history",
        choices=("factors", "measured"),
        default="factors",
        help="'factors' builds pre-2015 returns from estimated loadings; 'measured' "
        "uses the real returns of a long-only large-cap momentum portfolio instead",
    )
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    if args.history == "measured":
        frame, fit = data.long_only_momentum_history("SPMO")
        print(
            f"\nhistory: measured -- real long-only large-cap momentum returns."
            f"\nSPMO vs proxy over {fit['n_obs']} overlapping days: beta "
            f"{fit['beta_proxy']:.3f}, alpha {fit['alpha_annual']:+.2%}/yr "
            f"(t = {fit['alpha_t_stat']:.2f}), R2 {fit['r2']:.4f}"
        )
    else:
        frame, _ = data.extend_with_factors("SPMO")
        print("\nhistory: factors -- pre-2015 returns constructed from loadings")
    horizon = args.horizon * 252
    paths = bootstrap.moving_block_paths(
        frame["ret"].to_numpy(), args.paths, horizon, seed=11
    )

    # coarse pass, then a fine pass around the winner -- a 0.001 grid over the whole
    # range would be thousands of full simulations for no extra information
    coarse = evaluate_grid(paths, np.arange(1.0, 2.81, 0.05))
    coarse.drop(columns="wealth").to_csv(RESULTS / "target_objective_coarse.csv")

    gammas = (1.0, 1.25, args.gamma, 2.0)
    answers = []
    for gamma in sorted(set(gammas)):
        utilities = np.array([crra(w, gamma) for w in coarse["wealth"]])
        peak = _refine(coarse.index.to_numpy(), utilities)
        fine_grid = np.arange(max(1.0, peak - 0.08), peak + 0.081, 0.005)
        fine = evaluate_grid(paths, fine_grid)
        fine_utilities = np.array([crra(w, gamma) for w in fine["wealth"]])
        answers.append(
            {
                "objective": f"CRRA expected utility, gamma = {gamma:g}",
                "target": _refine(fine.index.to_numpy(), fine_utilities),
            }
        )

    constrained = optimal.constrained_growth_optimal(coarse, args.dd_threshold)
    answers.append(
        {
            "objective": f"max median CAGR s.t. P(drawdown < {DRAWDOWN_LIMIT:.0%}) <= {args.dd_threshold:.1%}",
            "target": constrained,
        }
    )

    table = pd.DataFrame(answers)
    table.to_csv(RESULTS / "optimal_target.csv", index=False)

    # ---- band, optimised on the same objective at the chosen target
    target = float(
        next(a["target"] for a in answers if f"gamma = {args.gamma:g}" in a["objective"])
    )
    band_rows = []
    for band in (0.02, 0.04, 0.06, 0.08, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30):
        out = bootstrap.simulate_paths(
            paths, target, BENCHMARK, rebalance="band", band=band
        )
        band_rows.append(
            {
                "band": band,
                "lower": target * (1 - band),
                "upper": target * (1 + band),
                "utility": crra(out["terminal_equity"] / 100_000.0, args.gamma),
                "median_cagr": float(np.median(out["cagr"])),
                "p05_cagr": float(np.percentile(out["cagr"], 5)),
                "mean_leverage": float(np.median(out["mean_leverage"])),
                "trades": float(np.median(out["rebalances"])),
            }
        )
    bands = pd.DataFrame(band_rows).set_index("band")
    bands.to_csv(RESULTS / "optimal_band.csv")
    best_band = _refine(bands.index.to_numpy(), bands["utility"].to_numpy())

    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(f"\n{args.horizon}-year horizon, {args.paths} paths, financing {BENCHMARK:.2%} + 1.50%\n")
    print(table.to_string(index=False, float_format=lambda v: f"{v:.3f}x"))
    print(f"\n--- band swept at the gamma = {args.gamma:g} target of {target:.3f}x ---")
    print(bands.round(4).to_string())
    print(f"\nutility-maximising band: {best_band:.1%}")
    print(f"\nConditional fitted optimum: {target:.3f}x; fitted band {best_band:.1%}.")
    print("NOT A LIVE INSTRUCTION: no independent selection-adjusted validation; opening limits are not imposed in this research sweep.")
    print(
        "\nThe third decimal is not real. This run does not estimate a selection-adjusted"
        "\nconfidence interval for the optimum. Read the mean_leverage"
        "\ncolumn before preferring a wide band -- a wide band wins by holding less."
    )


if __name__ == "__main__":
    main()
