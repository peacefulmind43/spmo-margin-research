"""Chronological diagnostics, not an untouched test or a trading approval.

The universe, grid and rule are declared before this runner inspects test outcomes.
They were designed after earlier work on the same history; no p-value here can
undo that history of research. ETF closures and revised factor vintages remain
separate data-quality requirements.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from . import bootstrap, data
from .backtest import Account, simulate


@dataclass(frozen=True)
class ValidationConfig:
    tickers: tuple[str, ...] = ("SPMO", "MTUM", "PDP", "QMOM", "MMTM")
    grid: tuple[float, ...] = (1., 1.25, 1.5, 1.75, 2.)
    first_test_year: int = 2019
    last_test_year: int = 2026
    min_live_days: int = 756
    paths: int = 128
    forecast_years: int = 3
    seed: int = 113
    equity: float = 50_000.
    annual_drag: float = .003
    mean_revision: float = .02
    maintenance: float = .25
    stress_maintenance: float = .50
    stress_drawdown: float = -.20
    monthly_withdrawal: float = 0.
    max_leverage: float = 2.
    financing: str = "asof_constant"


def select_targets(train, config, equity):
    """Use ONLY training returns/rates. Revision is a scenario, not a posterior."""
    h = config.forecast_years * 252
    idx = bootstrap.moving_block_paths(np.arange(len(train)), config.paths, h,
                                       seed=config.seed).astype(int)
    paths = train.ret.to_numpy()[idx]
    if config.financing == "asof_constant":
        benchmark = float(train.bm.iloc[-1])
    elif config.financing == "paired_historical":
        benchmark = train.bm.to_numpy()[idx]
    else:
        raise ValueError("unknown financing mode")
    rows = []
    for policy, revision in [("fitted_growth", 0.), ("mean_minus_2pp", config.mean_revision)]:
        for lev in config.grid:
            if lev > config.max_leverage:
                continue
            # Charge initial purchase cost, including the unlevered comparator.
            start = equity / (1 + .0002 * lev)
            out = bootstrap.simulate_paths(
                paths - revision / 252, lev, benchmark, equity0=start,
                rebalance="band", band=.10, annual_drag=config.annual_drag,
                maintenance_margin=config.maintenance, max_leverage=config.max_leverage,
            )
            wealth = out["terminal_equity"] / equity
            score = float(np.log(wealth).mean() / config.forecast_years) if (wealth > 0).all() else -np.inf
            rows.append({"policy": policy, "target": lev, "annual_log_score": score,
                         "revision": revision, "train_end": str(train.index.max().date())})
    table = pd.DataFrame(rows)
    selected = {}
    for policy, group in table.groupby("policy", sort=False):
        # Stable ties select lower borrowing. Do not interpolate false precision.
        best = group.sort_values(["annual_log_score", "target"], ascending=[False, True]).iloc[0]
        selected[policy] = float(best.target)
    return selected, table


def causal_maintenance(price, config):
    """Stress decision uses only the PREVIOUS close's observed asset drawdown."""
    prior_dd = (price / price.cummax() - 1).shift(1).fillna(0.)
    return pd.Series(np.where(prior_dd < config.stress_drawdown,
                             config.stress_maintenance, config.maintenance), index=price.index)


def walk_forward(config):
    folds, scores, skips, curves = [], [], [], []
    for ticker in config.tickers:
        px = data.load_total_return(ticker)
        if px.index.has_duplicates or not np.isfinite(px).all() or (px <= 0).any():
            raise ValueError(f"invalid prices for {ticker}")
        live = px.pct_change().dropna()
        bm = data.load_benchmark_rate().reindex(live.index, method="ffill")
        end = min(live.index.max(), data.load_french_factors().index.max())
        margin = causal_maintenance(px, config).reindex(live.index)
        states = {}
        for year in range(config.first_test_year, config.last_test_year + 1):
            cutoff = pd.Timestamp(year, 1, 1) - pd.Timedelta(days=1)
            test = live.loc[pd.Timestamp(year, 1, 1):min(pd.Timestamp(year, 12, 31), end)]
            if len(live.loc[:cutoff]) < config.min_live_days or test.empty:
                skips.append({"ticker": ticker, "year": year, "reason": "insufficient training or no test observations"})
                continue
            if bm.reindex(test.index).isna().any():
                raise ValueError(f"missing historical funding for {ticker} {year}")
            train, fit = data.extend_with_factors(ticker, as_of=cutoff)
            assert train.index.max() <= cutoff < test.index.min()
            assert pd.Timestamp(fit["window"][1]) <= cutoff
            # Same nominal training equity for both forecast rules isolates rule
            # selection from subsequent account wealth differences.
            targets, diagnostics = select_targets(train, config, config.equity)
            diagnostics["ticker"], diagnostics["year"] = ticker, year
            diagnostics["fit_end"] = fit["window"][1]
            scores.extend(diagnostics.to_dict("records"))
            targets.update({"fixed_1x": 1., "fixed_1_5x": 1.5, "fixed_2x": 2.})
            for policy, target in targets.items():
                if target > config.max_leverage:
                    continue
                state = states.get(policy)
                opening = config.equity if state is None else state[0]
                requests = np.zeros(len(test))
                month_starts = ~test.index.to_period("M").duplicated()
                requests[month_starts] = config.monthly_withdrawal
                if opening <= 0:
                    folds.append({"ticker": ticker, "year": year, "policy": policy,
                                  "target": target, "test_days": len(test), "growth": 0.,
                                  "terminal_equity": 0., "wiped_out": True,
                                  "ruin_deficit": 0.,
                                  "margin_calls": 0, "withdrawals_paid": 0.,
                                  "withdrawal_failures": int(np.count_nonzero(requests))})
                    for date in test.index:
                        curves.append({"ticker": ticker, "policy": policy, "date": date,
                                       "equity": 0., "cashflow": 0., "maintenance": margin.loc[date]})
                    continue
                starting = opening / (1 + .0002 * target) if state is None else opening
                initial_position = starting * target if state is None else state[1]
                # Band decisions can change once per year; the account, loan and
                # costs carry forward. No annual reset or retrospective best rule.
                out = simulate(test.to_numpy(), bm.reindex(test.index).to_numpy(),
                    Account(leverage=target, equity=starting, rebalance="band", band=.10,
                            annual_drag=config.annual_drag, max_leverage=config.max_leverage),
                    maintenance=margin.reindex(test.index).to_numpy(),
                    withdrawals=requests, position0=initial_position)
                states[policy] = (out["equity"][-1], out["position"][-1])
                growth = (1 + out["stats"]["cagr"]) ** (len(test) / 252) * (starting / opening)
                folds.append({"ticker": ticker, "year": year, "policy": policy,
                    "target": target, "train_end": str(train.index.max().date()),
                    "fit_end": fit["window"][1], "test_start": str(test.index.min().date()),
                    "test_end": str(test.index.max().date()), "test_days": len(test),
                    "growth": growth, "terminal_equity": out["equity"][-1],
                    "ruin_deficit": out["stats"]["ruin_deficit"],
                    "margin_calls": out["stats"]["margin_calls"],
                    "withdrawal_failures": out["stats"]["withdrawal_failures"],
                    "withdrawals_paid": out["stats"]["withdrawals_paid"],
                    "wiped_out": out["stats"]["wiped_out"]})
                for i, date in enumerate(test.index):
                    curves.append({"ticker": ticker, "policy": policy, "date": date,
                                   "equity": out["equity"][i + 1], "cashflow": out["cashflows"][i],
                                   "maintenance": margin.loc[date]})
    fold_table = pd.DataFrame(folds)
    if fold_table.empty:
        raise ValueError("no eligible folds")
    summary = []
    for (ticker, policy), group in fold_table.groupby(["ticker", "policy"]):
        duration = group.test_days.sum() / 252
        product = group.growth.prod()
        summary.append({"ticker": ticker, "policy": policy,
            "years_observed": duration, "cagr": product ** (1 / duration) - 1,
            "terminal_equity": group.terminal_equity.iloc[-1],
            "terminal_net_equity": group.terminal_equity.iloc[-1] - group.ruin_deficit.sum(),
            "ruin_deficit": group.ruin_deficit.sum(),
            "margin_calls": group.margin_calls.sum(),
            "withdrawal_failures": group.withdrawal_failures.sum(),
            "withdrawals_paid": group.withdrawals_paid.sum()})
    summary = pd.DataFrame(summary)
    baseline = summary[summary.policy == "fixed_1x"].set_index("ticker").cagr
    summary["cagr_minus_1x"] = summary.cagr - summary.ticker.map(baseline)
    return fold_table, pd.DataFrame(scores), summary, pd.DataFrame(skips, columns=["ticker", "year", "reason"]), pd.DataFrame(curves)
