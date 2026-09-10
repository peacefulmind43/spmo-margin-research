"""Price and interest-rate data, cached to ``data/`` so results are reproducible."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parents[1] / "data"
FRED_DFF = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FRENCH_FACTORS = f"{FRENCH_BASE}/F-F_Research_Data_Factors_daily_CSV.zip"
FRENCH_MOMENTUM = f"{FRENCH_BASE}/F-F_Momentum_Factor_daily_CSV.zip"


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


def _read_french_zip(url: str, columns: list[str]) -> pd.DataFrame:
    """Parse one of Ken French's daily factor zips into decimal returns."""
    import io
    import urllib.request
    import zipfile

    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        raw = archive.read(archive.namelist()[0]).decode("latin-1")

    rows = []
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == len(columns) + 1 and re.fullmatch(r"\d{8}", parts[0]):
            rows.append(parts)
    frame = pd.DataFrame(rows, columns=["date", *columns])
    frame["date"] = pd.to_datetime(frame["date"], format="%Y%m%d")
    frame = frame.set_index("date").astype(float) / 100.0
    return frame.sort_index()


def load_french_factors(refresh: bool = False) -> pd.DataFrame:
    """Daily market excess return, risk-free rate and the momentum factor since 1926.

    This is the dataset the SPY-beta extension could not provide. Momentum's real
    tail risk is not market beta -- it is the momentum *crash*, when the losers a
    momentum book is short rip upward. Those episodes (August 2007, March-May 2009,
    January 2001, the 1932 and 1939 reversals) are invisible to a market-beta map
    and are exactly what kills a levered momentum position.
    """
    path = _cache_path("french_factors")
    if path.exists() and not refresh:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        market = _read_french_zip(FRENCH_FACTORS, ["mkt_rf", "smb", "hml", "rf"])
        momentum = _read_french_zip(FRENCH_MOMENTUM, ["mom"])
        frame = market[["mkt_rf", "rf"]].join(momentum, how="inner")
        frame.to_csv(path)
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    return frame


def fit_factor_model(
    ticker: str = "SPMO", refresh: bool = False
) -> tuple[pd.Series, dict[str, float]]:
    """Regress the ETF's excess return on the market and momentum factors.

    The point of the momentum loading is to explain away the "alpha". An ETF that
    tracks a momentum index should earn the momentum factor premium, and calling that
    alpha and then projecting it across history is how a backtest flatters leverage.
    Whatever intercept survives this regression is the part that is genuinely
    unexplained -- and it should be treated as noise until proven otherwise.
    """
    price = load_total_return(ticker, refresh=refresh)
    factors = load_french_factors(refresh=refresh)

    rets = price.pct_change().dropna()
    joined = pd.DataFrame({"ret": rets}).join(factors, how="inner").dropna()
    excess = (joined["ret"] - joined["rf"]).to_numpy()

    design = np.column_stack(
        [np.ones(len(joined)), joined["mkt_rf"].to_numpy(), joined["mom"].to_numpy()]
    )
    coef, *_ = np.linalg.lstsq(design, excess, rcond=None)
    resid = excess - design @ coef
    ss_tot = float(((excess - excess.mean()) ** 2).sum())

    # standard error on the intercept, to say whether the alpha is distinguishable
    dof = len(joined) - design.shape[1]
    sigma2 = float((resid**2).sum()) / dof
    cov = sigma2 * np.linalg.inv(design.T @ design)
    alpha_se = float(np.sqrt(cov[0, 0]))

    stats = {
        "alpha_daily": float(coef[0]),
        "alpha_annual": float(coef[0]) * 252,
        "alpha_se_annual": alpha_se * 252,
        "alpha_t_stat": float(coef[0]) / alpha_se,
        "beta_market": float(coef[1]),
        "beta_momentum": float(coef[2]),
        "r2": 1.0 - float((resid**2).sum()) / ss_tot,
        "resid_vol_daily": float(resid.std(ddof=3)),
        "n_obs": int(len(joined)),
        "window": [str(joined.index[0].date()), str(joined.index[-1].date())],
    }
    return pd.Series(resid, index=joined.index), stats


def extend_with_factors(
    ticker: str = "SPMO",
    include_alpha: bool = False,
    include_residual: bool = True,
    refresh: bool = False,
    seed: int = 20260910,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Synthetic history built from real factor returns back to 1926.

    ``include_alpha`` defaults to **False**: the in-sample intercept is not projected
    across a century of history. Turn it on only to see how much the conclusion
    depends on believing it.

    ``include_residual`` resamples the regression residuals so the synthetic series
    keeps the ETF's idiosyncratic volatility instead of being a smooth factor
    combination. Without it the tails are understated.
    """
    resid, stats = fit_factor_model(ticker, refresh=refresh)
    factors = load_french_factors(refresh=refresh)

    synthetic = (
        stats["beta_market"] * factors["mkt_rf"]
        + stats["beta_momentum"] * factors["mom"]
        + factors["rf"]
    )
    if include_alpha:
        synthetic = synthetic + stats["alpha_daily"]
    if include_residual:
        rng = np.random.default_rng(seed)
        draws = rng.choice(resid.to_numpy(), size=len(synthetic), replace=True)
        synthetic = synthetic + draws

    live = load_total_return(ticker, refresh=refresh).pct_change().dropna()
    combined = synthetic.copy()
    combined.loc[combined.index.intersection(live.index)] = live.reindex(
        combined.index.intersection(live.index)
    )

    frame = pd.DataFrame({"ret": combined.sort_index()})
    benchmark = load_benchmark_rate(refresh=refresh)
    frame["bm"] = benchmark.reindex(frame.index).ffill()
    # before the Fed Funds series begins, fall back to the contemporaneous T-bill
    frame["bm"] = frame["bm"].fillna(factors["rf"].reindex(frame.index) * 360)
    frame["bm"] = frame["bm"].clip(lower=0.0).bfill()
    frame["is_synthetic"] = ~frame.index.isin(live.index)
    return frame, stats


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
