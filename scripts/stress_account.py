#!/usr/bin/env python3
"""Joint funding, maintenance, return and spending sensitivities; no recommendation."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from spmo_margin import bootstrap, data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", type=int, default=512)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--equity", type=float, default=50000.)
    ap.add_argument("--benchmark", type=float, default=.0363)
    ap.add_argument("--monthly-contribution", type=float, default=0.)
    ap.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "results" / "stress")
    args = ap.parse_args()
    if min(args.paths, args.years, args.equity) <= 0 or args.monthly_contribution < 0:
        ap.error("positive paths/years/equity and nonnegative contribution required")
    frame, _ = data.extend_with_factors()
    horizon = args.years * 252
    idx = bootstrap.moving_block_paths(np.arange(len(frame)), args.paths, horizon, seed=907).astype(int)
    paths = frame.ret.to_numpy()[idx]
    paired = frame.bm.to_numpy()[idx]
    # Align the mean to isolate timing from the average cost of financing.
    paired = paired * args.benchmark / paired.mean() if paired.mean() else paired
    peak = np.maximum.accumulate(np.maximum(1., np.cumprod(1 + paths, axis=1)), axis=1)
    drawdown = np.cumprod(1 + paths, axis=1) / peak - 1
    prior_dd = np.concatenate([np.zeros((args.paths, 1)), drawdown[:, :-1]], axis=1)
    m50 = np.where(prior_dd < -.20, .50, .25)
    m75 = np.where(prior_dd < -.20, .75, .25)
    withdrawals = np.zeros(horizon)
    withdrawals[np.arange(horizon) % 21 == 0] = 1000.
    cases = [
        ("constant_rate", paths, args.benchmark, .25, 0.),
        ("paired_rate_equal_mean", paths, paired, .25, 0.),
        ("paired_rate_stress50", paths, paired, m50, 0.),
        ("paired_rate_stress75", paths, paired, m75, 0.),
        ("mean_minus_2pp", paths - .02 / 252, args.benchmark, .25, 0.),
        ("mean_minus_4pp", paths - .04 / 252, args.benchmark, .25, 0.),
        ("withdraw_1000_monthly", paths, paired, m50, withdrawals),
    ]
    rows = []
    for case, r, bm, m, w in cases:
        for lev in (1., 1.25, 1.5, 1.75, 2.):
            result = bootstrap.simulate_paths(r, lev, bm, equity0=args.equity / (1 + .0002 * lev),
                annual_drag=.003, max_leverage=2., rebalance="band", band=.10,
                maintenance_margin=m, withdrawals=w, monthly_contribution=args.monthly_contribution)
            cagr = (1 + result["cagr"]) * (1 / (1 + .0002 * lev)) ** (1 / args.years) - 1
            rows.append({"case": case, "leverage": lev, "median_twr_cagr": np.median(cagr),
                "p05_twr_cagr": np.percentile(cagr, 5), "median_terminal_equity": np.median(result["terminal_equity"]),
                "median_withdrawn": np.median(result["withdrawals_paid"]),
                "p_unpaid_withdrawal": np.mean(result["withdrawal_failures"] > 0),
                "p_liquidation": np.mean(result["margin_calls"] > 0), "p_ruin": np.mean(result["wiped_out"]),
                "worst_ruin_deficit": result["ruin_deficit"].max(),
                "median_max_drawdown": np.median(result["max_drawdown"]),
                "geometric_twr_cagr": np.expm1(np.log1p(cagr).mean()) if (cagr > -1).all() else -1.})
    args.output.mkdir(parents=True, exist_ok=True)
    table = pd.DataFrame(rows)
    table.to_csv(args.output / "scenarios.csv", index=False)
    settings = vars(args).copy()
    settings["output"] = str(settings["output"])
    settings.update(seed=907, annual_drag=.003, band=.10, max_leverage=2.,
        status="sensitivity_only", live_sizing_approved=False,
        assumptions="Factor reconstruction; stress sizes are not calibrated probabilities. Equal-mean paired rates are rescaled historical blocks, not a policy forecast.")
    (args.output / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    print(table.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
