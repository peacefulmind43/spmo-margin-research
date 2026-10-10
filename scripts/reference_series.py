#!/usr/bin/env python3
"""The same questions asked of two long-history momentum series, for reference only.

The S&P 500 Momentum Index history in this repository starts in 2016 until the
1994-2016 portion is added. Two other published momentum portfolios have decades of
record and are shown here so the missing bear markets are not simply invisible:

* Ken French BIG HiPRIOR, daily since 1926 -- runs through the daily margin engine.
* AQR U.S. Large Cap Momentum Index, monthly since 1980 -- monthly treatment only.

**Neither is SPMO or its index.** Over 2016-2026 both moved closely with the index
(monthly correlation about 0.92-0.93) but compounded about 4pp a year less, so any
leverage figure here describes those portfolios, not the fund. Nothing computed here
feeds any other script. Both are charged SPMO's 0.13% fee so the comparison with the
index (also net of fee) is like for like.

    python scripts/reference_series.py [--paths 2000]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from spmo_margin import backtest, bootstrap, data, kelly, optimal, reference

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path(os.environ.get("SPMO_RESULTS_DIR", str(ROOT / "results"))) / "reference"

LEVERAGES = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
SPREAD = 0.015
EPISODES = {
    "1929-32 crash": ("1929-09-01", "1932-07-31"),
    "1937-38": ("1937-03-01", "1938-03-31"),
    "1973-74": ("1973-01-01", "1974-10-31"),
    "1987 crash": ("1987-08-01", "1987-12-31"),
    "2000-02 dot-com": ("2000-03-01", "2002-10-31"),
    "2007-09 GFC": ("2007-10-01", "2009-03-31"),
    "2009 momentum crash": ("2009-03-01", "2009-05-31"),
    "2020 covid": ("2020-02-01", "2020-04-30"),
    "2022": ("2022-01-01", "2022-10-31"),
}


def net_of_fee(frame: pd.DataFrame, periods_per_year: int) -> pd.DataFrame:
    fee = (1.0 - data.SPMO_EXPENSE_RATIO) ** (1.0 / periods_per_year)
    return frame.assign(ret=(1.0 + frame["ret"]) * fee - 1.0)


def summary(ret: pd.Series, periods_per_year: int, label: str) -> dict[str, object]:
    wealth = (1.0 + ret).cumprod()
    yearly = (1.0 + ret).groupby(ret.index.year).prod() - 1.0
    years = len(ret) / periods_per_year
    return {
        "series": label,
        "start": str(ret.index[0].date()),
        "end": str(ret.index[-1].date()),
        "years": years,
        "cagr": float(wealth.iloc[-1] ** (1 / years) - 1),
        "vol": float(ret.std(ddof=1) * np.sqrt(periods_per_year)),
        "max_drawdown": float((wealth / wealth.cummax() - 1).min()),
        "worst_year": int(yearly.idxmin()),
        "worst_year_return": float(yearly.min()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=2000)
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)

    index = data.momentum_index_history()
    french = net_of_fee(reference.french_big_hiprior(), 252)
    aqr = net_of_fee(reference.aqr_large_cap_momentum(), 12)
    bm_now = float(data.load_benchmark_rate().iloc[-1])
    facts: dict[str, object] = {"benchmark_now": bm_now}

    # ---------------------------------------------- how close to the real index
    facts["overlap_with_sp500_momentum"] = {
        "french_big_hiprior": reference.overlap_with_index(french["ret"], index["ret"]),
        "aqr_large_cap_momentum": reference.overlap_with_index(aqr["ret"], index["ret"]),
    }

    # ---------------------------------------------- whole-history description
    stats = pd.DataFrame([
        summary(index["ret"], 252, "S&P 500 Momentum TR (the real index, partial)"),
        summary(french["ret"], 252, "French BIG HiPRIOR 1926-"),
        summary(french.loc["1994-09-16":, "ret"], 252, "French BIG HiPRIOR from 1994-09-16"),
        summary(aqr["ret"], 12, "AQR US Large Cap Momentum 1980-"),
        summary(aqr.loc["1994-10-01":, "ret"], 12, "AQR US Large Cap Momentum from 1994-10"),
    ]).set_index("series")
    stats.to_csv(RESULTS / "summary.csv")

    # ---------------------------------------------- the episodes
    rows = []
    for name, (start, end) in EPISODES.items():
        window = french.loc[start:end]
        if len(window) > 20:
            table, _ = backtest.sweep(window, LEVERAGES, rebalance="monthly")
            for lev, row in table.iterrows():
                rows.append({"episode": name, "series": "French daily (margin engine)",
                             "leverage": lev, "max_drawdown": row["max_drawdown"],
                             "period_return": (1 + row["cagr"]) ** (len(window) / 252) - 1,
                             "margin_calls": row["margin_calls"], "wiped_out": row["wiped_out"]})
        monthly = aqr.loc[start:end]
        if len(monthly) >= 2:
            for lev in LEVERAGES:
                path = reference.monthly_levered_path(monthly, lev, SPREAD)
                rows.append({"episode": name, "series": "AQR monthly (month-end only)",
                             "leverage": lev,
                             "max_drawdown": float((path / path.cummax().clip(lower=1.0) - 1).min()),
                             "period_return": float(path.iloc[-1] - 1),
                             "margin_calls": np.nan, "wiped_out": bool(path.iloc[-1] <= 0)})
        live = index.loc[start:end]
        if len(live) > 20 and index.index[0] <= pd.Timestamp(start):
            table, _ = backtest.sweep(live, LEVERAGES, rebalance="monthly")
            for lev, row in table.iterrows():
                rows.append({"episode": name, "series": "S&P 500 Momentum (real index)",
                             "leverage": lev, "max_drawdown": row["max_drawdown"],
                             "period_return": (1 + row["cagr"]) ** (len(live) / 252) - 1,
                             "margin_calls": row["margin_calls"], "wiped_out": row["wiped_out"]})
    episodes = pd.DataFrame(rows)
    episodes.to_csv(RESULTS / "episodes.csv", index=False)

    # ---------------------------------------------- leverage answers
    answers = []
    samples = {
        "S&P 500 Momentum (real index, 2016-)": index,
        "French BIG HiPRIOR 1926-": french,
        "French BIG HiPRIOR 1994-": french.loc["1994-09-16":],
    }
    for label, frame in samples.items():
        rets = frame["ret"].to_numpy()
        boot = bootstrap.bootstrap_sweep(rets, LEVERAGES, benchmark_level=bm_now, n_paths=args.paths)
        long_paths = bootstrap.moving_block_paths(rets, args.paths, 40 * 252, seed=11)
        dd70 = {}
        for lev in (1.5, 2.0):
            out = bootstrap.simulate_paths(long_paths, lev, bm_now)
            dd70[lev] = float((out["max_drawdown"] < -0.70).mean())
        emp = kelly.empirical_kelly(rets, np.full(len(rets), bm_now), borrow_spread=SPREAD)
        answers.append({
            "sample": label, "frequency": "daily",
            "mu_arith": float(rets.mean() * 252), "sigma": float(rets.std(ddof=1) * np.sqrt(252)),
            "full_kelly": emp["f_star"], "half_kelly": emp["f_star"] / 2,
            "p05_optimal_10y": optimal.robust_optimal(boot, "cagr_p05"),
            "p05_cagr_10y_at_1x": float(boot.loc[1.0, "cagr_p05"]),
            "p05_cagr_10y_at_1_5x": float(boot.loc[1.5, "cagr_p05"]),
            "p_dd_over_70_40y_at_1_5x": dd70[1.5],
            "p_dd_over_70_40y_at_2x": dd70[2.0],
        })
    for label, frame in {"AQR US Large Cap Momentum 1980-": aqr,
                         "AQR US Large Cap Momentum 1994-": aqr.loc["1994-10-01":]}.items():
        f_star = reference.monthly_kelly(frame.assign(bm=bm_now), SPREAD)
        answers.append({
            "sample": label, "frequency": "monthly",
            "mu_arith": float(frame["ret"].mean() * 12),
            "sigma": float(frame["ret"].std(ddof=1) * np.sqrt(12)),
            "full_kelly": f_star, "half_kelly": f_star / 2,
        })
    answer_table = pd.DataFrame(answers).set_index("sample")
    answer_table.to_csv(RESULTS / "leverage_answers.csv")
    (RESULTS / "key_facts.json").write_text(json.dumps(facts, indent=2, default=float) + "\n")

    pd.set_option("display.width", 220, "display.max_columns", 30)
    print("\nREFERENCE ONLY -- neither series is SPMO or the S&P 500 Momentum Index.\n")
    for name, o in facts["overlap_with_sp500_momentum"].items():
        print(f"{name} vs S&P 500 Momentum, {o['window'][0]} to {o['window'][1]}: corr "
              f"{o['correlation']:.3f}, beta {o['beta_to_index']:.2f}, CAGR "
              f"{o['reference_cagr']:.1%} vs index {o['index_cagr']:.1%}")
    print("\n--- whole history ---")
    print(stats.round(3).to_string())
    print("\n--- episodes, max drawdown by leverage (monthly rebalance) ---")
    pivot = episodes.pivot_table(index=["episode", "series"], columns="leverage",
                                 values="max_drawdown", sort=False)
    print(pivot.round(2).to_string())
    print("\n--- leverage answers (10y bootstrap at today's benchmark; 40y for drawdown odds) ---")
    print(answer_table.round(3).to_string())


if __name__ == "__main__":
    main()
