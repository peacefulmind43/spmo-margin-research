"""Price and interest-rate data, cached to ``data/`` so results are reproducible."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parents[1] / "data"
FRED_DFF = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"


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

    This is IBKR's USD benchmark. Using the daily history rather than today's level
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


def fit_proxy(target: pd.Series, proxy: pd.Series) -> dict[str, float]:
    """OLS of target daily returns on proxy daily returns over their common window."""
    a, b = target.align(proxy, join="inner")
    x = b.to_numpy()
    y = a.to_numpy()
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ coef
    resid = y - fitted
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return {
        "alpha_daily": float(coef[0]),
        "beta": float(coef[1]),
        "r2": 1.0 - float((resid**2).sum()) / ss_tot,
        "resid_vol_daily": float(resid.std(ddof=2)),
        "n_obs": int(len(y)),
    }


def extend_with_proxy(
    ticker: str = "SPMO",
    proxy: str = "SPY",
    refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Synthetic pre-inception history for ``ticker`` mapped from ``proxy`` via beta.

    SPMO launched in October 2015, so its own record contains no 2000-02 and no 2008.
    Any leverage conclusion drawn from that window alone is drawn from a sample with
    the two events that actually kill leveraged accounts removed. This maps the ETF
    onto SPY's 1993-onward total return so those bear markets can be replayed.

    The mapping is deterministic (alpha + beta * proxy) and therefore strips out
    idiosyncratic risk, so it understates the tails rather than exaggerating them.
    """
    tgt = load_total_return(ticker, refresh=refresh).pct_change().dropna()
    prx = load_total_return(proxy, refresh=refresh).pct_change().dropna()
    fit = fit_proxy(tgt, prx)

    synth = fit["alpha_daily"] + fit["beta"] * prx
    combined = synth.copy()
    combined.loc[tgt.index] = tgt  # use the real ETF wherever it exists

    df = pd.DataFrame({"ret": combined.sort_index()})
    bm = load_benchmark_rate(refresh=refresh)
    df["bm"] = bm.reindex(df.index).ffill().bfill()
    df["is_synthetic"] = ~df.index.isin(tgt.index)
    return df, fit
