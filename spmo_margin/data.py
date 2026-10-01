"""Price and interest-rate data, cached to ``data/`` so results are reproducible.

Every return series here is a published record. Nothing is constructed from factor
loadings, regressions or resampled residuals: an earlier version of this module did
that to stretch SPMO's history back to 1926, and the leverage conclusions it produced
are retired (see ``docs/historical-conclusions-2026-09-10.md``).

The long history is the **S&P 500 Momentum Index, gross total return** (SP500MUT),
the index SPMO tracks. S&P DJI calculates it from 1994-09-16; values before the
2014-11-18 launch are S&P's own back-test under the launch-date methodology. S&P's
public site serves only the most recent ten years of daily levels, so the cached
series currently starts in 2016. **The 1994-2016 portion is still to be added**:
export SP500MUT daily levels (e.g. Bloomberg ``SP500MUT Index HP``) to
``data/sp500_momentum_tr_full.csv`` with columns ``date,level`` and every loader
here splices it in automatically, after checking it against the S&P download.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .margin import TRADING_DAYS_PER_YEAR

CACHE_DIR = Path(__file__).resolve().parents[1] / "data"
FRED_DFF = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"

# S&P DJI's id for the S&P 500 Momentum Index (USD); returntype T- selects gross
# total return, published as SP500MUT. Dates from the S&P Momentum Indices
# methodology, "Base Dates and History Availability".
SPDJI_INDEX_ID = 92024474
SPDJI_PAGE = "https://www.spglobal.com/spdji/en/indices/dividends-factors/sp-500-momentum-index/"
SPDJI_LEVELS = (
    "https://www.spglobal.com/spdji/en/util/redesign/index-data/"
    "get-performance-data-for-datawidget-redesign.dot"
    f"?indexId={SPDJI_INDEX_ID}&getchildindex=true&returntype=T-"
    "&currencycode=USD&currencyChangeFlag=false&language_id=1"
)
INDEX_FIRST_VALUE_DATE = pd.Timestamp("1994-09-16")
INDEX_LAUNCH_DATE = pd.Timestamp("2014-11-18")
INDEX_RECENT_FILE = "sp500_momentum_tr"  # S&P DJI public download, rolling ten years
INDEX_FULL_FILE = "sp500_momentum_tr_full"  # user-supplied, from 1994-09-16

# SPMO's published gross expense ratio. The index is a gross total return, so the
# fund's fee is the one cost separating the two that is known in advance.
SPMO_EXPENSE_RATIO = 0.0013

PENDING_HISTORY_NOTE = (
    "PRELIMINARY: S&P 500 Momentum Index history currently starts {start}. "
    "The 1994-09-16 to {gap_end} portion (incl. 2000-02 and 2008) is still to be "
    "added via data/sp500_momentum_tr_full.csv; results will change when it is."
)


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{name}.csv"


def load_total_return(ticker: str, refresh: bool = False) -> pd.Series:
    """Dividend-adjusted close, i.e. a total-return price index for ``ticker``."""
    path = _cache_path(f"px_{ticker.replace('^', 'idx_')}")
    if path.exists() and not refresh:
        s = pd.read_csv(path, index_col=0, parse_dates=True)["close"]
    else:
        import yfinance as yf

        raw = yf.Ticker(ticker).history(period="max", auto_adjust=True)
        if raw.empty:
            raise RuntimeError(f"no price history returned for {ticker}")
        s = raw["Close"].copy()
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        s.name = "close"
        s.to_frame().to_csv(path)
    return s.astype(float).sort_index()


def load_benchmark_rate(refresh: bool = False) -> pd.Series:
    """Fed Funds Effective Rate as a decimal, forward-filled to every calendar day.

    This is a proxy for, not an exact history of, IBKR's USD reference benchmark.
    Using the daily history rather than today's level
    matters: the 2015-2021 stretch of near-zero rates made leverage look far cheaper
    than it has been since 2022.
    """
    path = _cache_path("fed_funds")
    if path.exists() and not refresh:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        df = pd.read_csv(FRED_DFF, parse_dates=["observation_date"]).set_index(
            "observation_date"
        )
        df.columns = ["rate"]
        df.to_csv(path)
    s = df["rate"].astype(float) / 100.0
    s.index = pd.DatetimeIndex(s.index).normalize()
    return s.sort_index().ffill()


def build_dataset(ticker: str = "SPMO", refresh: bool = False) -> pd.DataFrame:
    """Daily total return of ``ticker`` alongside the prevailing USD benchmark rate."""
    px = load_total_return(ticker, refresh=refresh)
    bm = load_benchmark_rate(refresh=refresh)
    df = pd.DataFrame({"ret": px.pct_change()}).dropna()
    df["bm"] = bm.reindex(df.index).ffill().bfill()
    return df


def _fetch_spdji_levels() -> pd.Series:
    """Daily SP500MUT levels from S&P DJI's public index page (about ten years).

    The site rejects plain HTTP clients, so this impersonates a browser's TLS
    handshake with ``curl_cffi`` -- already installed as a ``yfinance`` dependency.
    """
    from curl_cffi import requests

    session = requests.Session(impersonate="chrome")
    session.get(SPDJI_PAGE, timeout=60)
    response = session.get(
        SPDJI_LEVELS,
        headers={"Referer": SPDJI_PAGE, "X-Requested-With": "XMLHttpRequest"},
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    name = payload["indexDetailHolder"]["indexDetail"]["indexName"]
    if "Momentum" not in name or "Total Return" not in name:
        raise RuntimeError(f"S&P DJI returned an unexpected series: {name!r}")
    levels = payload["indexLevelsHolder"]["indexLevels"]
    series = pd.Series(
        [float(row["indexValue"]) for row in levels],
        index=pd.to_datetime([row["formattedEffectiveDate"] for row in levels], format="%d-%b-%Y"),
        name="level",
    )
    return series[~series.index.duplicated(keep="last")].sort_index()


def _read_levels(path: Path) -> pd.Series:
    frame = pd.read_csv(path)
    frame.columns = [c.strip().lower() for c in frame.columns]
    if not {"date", "level"} <= set(frame.columns):
        raise ValueError(f"{path.name} needs columns 'date,level'")
    series = pd.Series(
        frame["level"].astype(float).to_numpy(),
        index=pd.DatetimeIndex(pd.to_datetime(frame["date"])).normalize(),
        name="level",
    ).sort_index()
    if series.index.has_duplicates or not np.isfinite(series).all() or (series <= 0).any():
        raise ValueError(f"{path.name} has duplicate dates or non-positive levels")
    return series


def _splice(older: pd.Series, newer: pd.Series, label: str) -> pd.Series:
    """Chain ``older`` into ``newer`` by returns, refusing if the overlap disagrees.

    Splicing on returns rather than levels makes the join independent of base
    values. Two copies of the same published index should agree to rounding; a
    larger disagreement means one of them is a different series (price return
    instead of total return, net instead of gross) and must not be silently mixed.
    """
    overlap = older.index.intersection(newer.index)
    if len(overlap) < 20:
        raise ValueError(f"{label}: needs at least 20 overlapping days to verify the join")
    a = older.loc[overlap].pct_change().dropna()
    b = newer.loc[overlap].pct_change().dropna()
    gap = (a - b).abs()
    if gap.quantile(0.99) > 1e-4:
        raise ValueError(
            f"{label}: overlapping daily returns disagree (99th pct gap {gap.quantile(0.99):.2e}); "
            "check it is SP500MUT gross total return in USD"
        )
    before = older.loc[: overlap[0]]
    scaled = before * (newer.loc[overlap[0]] / before.iloc[-1])
    return pd.concat([scaled.iloc[:-1], newer]).sort_index()


def load_momentum_index(refresh: bool = False) -> pd.Series:
    """Daily levels of the S&P 500 Momentum Index, gross total return (SP500MUT).

    The S&P download only reaches back ten years, so a refresh is merged into the
    existing cache rather than replacing it -- otherwise each refresh would lose a
    day of history from the front. If ``data/sp500_momentum_tr_full.csv`` exists it
    supplies everything before the S&P download.
    """
    path = _cache_path(INDEX_RECENT_FILE)
    cached = _read_levels(path) if path.exists() else None
    if cached is None or refresh:
        fresh = _fetch_spdji_levels()
        cached = fresh if cached is None else _splice(cached, fresh, "S&P DJI refresh")
        cached.rename_axis("date").to_frame().to_csv(path)

    full_path = _cache_path(INDEX_FULL_FILE)
    if full_path.exists():
        cached = _splice(_read_levels(full_path), cached, full_path.name)
    return cached


def momentum_index_history(
    as_of: str | pd.Timestamp | None = None,
    expense_ratio: float = SPMO_EXPENSE_RATIO,
    refresh: bool = False,
) -> pd.DataFrame:
    """Daily index returns net of SPMO's fee, with the USD benchmark rate alongside.

    ``is_backtest`` marks days before the index launch, which S&P calculated after
    the fact. They are real index arithmetic on historical constituents, but the
    methodology itself was designed knowing how momentum had performed -- a
    selection effect no data source removes.

    ``as_of`` truncates the raw levels before any return is computed, so nothing
    dated after it can reach a training sample.
    """
    level = load_momentum_index(refresh=refresh)
    if as_of is not None:
        level = level.loc[:as_of]
    gross = level.pct_change().dropna()
    fee = (1.0 - expense_ratio) ** (1.0 / TRADING_DAYS_PER_YEAR)
    frame = pd.DataFrame({"ret": (1.0 + gross) * fee - 1.0})
    benchmark = load_benchmark_rate(refresh=refresh)
    frame["bm"] = benchmark.reindex(frame.index, method="ffill").clip(lower=0.0)
    if frame["bm"].isna().any():
        raise ValueError("benchmark rate missing for part of the index history")
    frame["is_backtest"] = frame.index < INDEX_LAUNCH_DATE
    return frame


def history_status(frame: pd.DataFrame) -> dict[str, object]:
    """What part of the index's 1994-onward history a frame actually contains."""
    start, end = frame.index[0], frame.index[-1]
    complete = start <= INDEX_FIRST_VALUE_DATE + pd.Timedelta(days=7)
    status: dict[str, object] = {
        "start": str(start.date()),
        "end": str(end.date()),
        "years": float(len(frame) / TRADING_DAYS_PER_YEAR),
        "full_history": bool(complete),
        "backtest_share": float(frame["is_backtest"].mean()) if "is_backtest" in frame else 0.0,
    }
    if not complete:
        gap_end = (start - pd.Timedelta(days=1)).date()
        status["missing"] = [str(INDEX_FIRST_VALUE_DATE.date()), str(gap_end)]
        status["note"] = PENDING_HISTORY_NOTE.format(start=status["start"], gap_end=gap_end)
    return status


def tracking_vs_etf(ticker: str = "SPMO", refresh: bool = False) -> dict[str, float]:
    """How closely the fee-adjusted index matches the ETF over their common days.

    A diagnostic, not a fit: nothing estimated here feeds back into the returns.
    """
    index = momentum_index_history(refresh=refresh)["ret"]
    etf = load_total_return(ticker, refresh=refresh).pct_change().dropna()
    a, b = index.align(etf, join="inner")
    diff = a - b
    return {
        "window": [str(a.index[0].date()), str(a.index[-1].date())],
        "n_obs": int(len(a)),
        "correlation": float(np.corrcoef(a, b)[0, 1]),
        "index_minus_etf_annual": float(diff.mean() * TRADING_DAYS_PER_YEAR),
        "tracking_error_annual": float(diff.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)),
    }
