"""Price and interest-rate data, cached to ``data/`` so results are reproducible."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .margin import TRADING_DAYS_PER_YEAR

CACHE_DIR = Path(__file__).resolve().parents[1] / "data"
FRED_DFF = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FRENCH_FACTORS = f"{FRENCH_BASE}/F-F_Research_Data_Factors_daily_CSV.zip"
FRENCH_MOMENTUM = f"{FRENCH_BASE}/F-F_Momentum_Factor_daily_CSV.zip"
FRENCH_PORTFOLIOS = f"{FRENCH_BASE}/6_Portfolios_ME_Prior_12_2_Daily_CSV.zip"


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


def _read_french_zip(
    url: str, columns: list[str], stop_at: str | None = None
) -> pd.DataFrame:
    """Parse one of Ken French's daily zips into decimal returns.

    ``stop_at`` truncates at a section header. Several of these files contain more
    than one table -- the portfolio files carry value-weighted returns followed by
    equal-weighted ones, under identical date stamps -- so a naive parse silently
    doubles every row. Duplicated rows leave OLS coefficients unchanged while
    inflating every t-statistic by sqrt(2), which is the kind of error that makes an
    insignificant alpha look significant.
    """
    import io
    import urllib.request
    import zipfile

    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        raw = archive.read(archive.namelist()[0]).decode("latin-1")

    lines = raw.splitlines()
    if stop_at is not None:
        for i, line in enumerate(lines):
            if stop_at in line:
                lines = lines[:i]
                break

    rows = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == len(columns) + 1 and re.fullmatch(r"\d{8}", parts[0]):
            rows.append(parts)
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError(f"duplicate dates parsed from {url} -- check section headers")
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


def load_long_only_momentum(refresh: bool = False) -> pd.Series:
    """Daily total return of large-cap, high-prior-return US stocks since 1926.

    This is Ken French's "BIG HiPRIOR" bucket: the value-weighted return of big
    stocks in the top third by prior 12-2 month return, rebalanced daily. It is the
    closest thing to SPMO that has a real hundred-year record -- large cap, momentum
    screened, long only, value weighted, no leverage.

    It matters that it is long only. The academic momentum factor UMD is
    winners *minus* losers, and a momentum crash is precisely the event where the
    losers rip upward: UMD lost 27% in April 2009. A long-only fund holds no shorts,
    so it merely underperforms in that event rather than being destroyed by it.
    Proxying SPMO with a loading on UMD therefore models its crash behaviour with an
    instrument that does not share its structure, however well the regression fits.
    """
    path = _cache_path("big_hiprior")
    if path.exists() and not refresh:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        frame = _read_french_zip(
            FRENCH_PORTFOLIOS,
            ["small_lo", "small_mid", "small_hi", "big_lo", "big_mid", "big_hi"],
            stop_at="Equal Weighted",
        )
        frame = frame[["big_hi"]]
        frame.to_csv(path)
    series = frame["big_hi"].astype(float)
    series.index = pd.DatetimeIndex(series.index).normalize()
    return series.sort_index()


def long_only_momentum_history(
    ticker: str = "SPMO",
    splice_live: bool = True,
    refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """A century of momentum returns that are measured rather than constructed.

    :func:`extend_with_factors` *builds* a pre-2015 history from factor loadings
    estimated on ten years of data. This does not build anything: it uses the actual
    daily returns of a real long-only large-cap momentum portfolio, optionally with
    the live ETF spliced over its own period. No regression, no synthesis, no
    resampled residuals, and therefore nothing that can be tuned.

    The price is that it is not SPMO. The fit statistics returned say how close the
    two are over the overlap; SPMO's beta to it is below one and a positive intercept
    survives, so using this series unadjusted is the conservative reading of both.
    """
    proxy = load_long_only_momentum(refresh=refresh)
    live = load_total_return(ticker, refresh=refresh).pct_change().dropna()
    factors = load_french_factors(refresh=refresh)

    joined = pd.DataFrame({"live": live}).join(
        pd.DataFrame({"proxy": proxy}), how="inner"
    ).join(factors[["rf"]], how="inner").dropna()
    y = (joined["live"] - joined["rf"]).to_numpy()
    x = (joined["proxy"] - joined["rf"]).to_numpy()
    design = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ coef
    dof = len(y) - 2
    se = np.sqrt(np.diag(float((resid**2).sum()) / dof * np.linalg.inv(design.T @ design)))
    stats = {
        "alpha_annual": float(coef[0]) * 252,
        "alpha_t_stat": float(coef[0] / se[0]),
        "beta_proxy": float(coef[1]),
        "r2": 1.0 - float((resid**2).sum()) / float(((y - y.mean()) ** 2).sum()),
        "n_obs": int(len(y)),
        "overlap": [str(joined.index[0].date()), str(joined.index[-1].date())],
    }

    combined = proxy.copy()
    if splice_live:
        overlap = combined.index.intersection(live.index)
        combined.loc[overlap] = live.reindex(overlap)

    frame = pd.DataFrame({"ret": combined.sort_index()})
    benchmark = load_benchmark_rate(refresh=refresh)
    frame["bm"] = benchmark.reindex(frame.index).ffill()
    frame["bm"] = frame["bm"].fillna(
        factors["rf"].reindex(frame.index) * TRADING_DAYS_PER_YEAR
    )
    frame["bm"] = frame["bm"].clip(lower=0.0).bfill()
    frame["is_synthetic"] = ~frame.index.isin(live.index) if splice_live else True
    return frame, stats


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
    residual_block: int = 21,
    momentum_premium_haircut: float = 0.0,
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

    The residuals are drawn in ``residual_block``-day blocks rather than one day at a
    time. They are not iid: the autocorrelation of their absolute value is 0.29 at
    lag 1 and still 0.21 at lag 5, their kurtosis is 11, and 21-day rolling
    idiosyncratic vol ranges from 2% to 28% annualised. Sampling them independently
    would smooth all of that away and make a clustered idiosyncratic drawdown look
    far less likely than it is.
    """
    # reuses the bootstrap module's block sampler rather than reimplementing it; the
    # dependency runs data -> bootstrap only, so there is no import cycle
    from .bootstrap import moving_block_paths

    resid, stats = fit_factor_model(ticker, refresh=refresh)
    factors = load_french_factors(refresh=refresh)

    # Zeroing the ETF's own alpha still leaves the momentum factor premium in, worth
    # about 2.1%/yr here at a 0.32 loading. That premium has a century of evidence
    # behind it, far more than any single fund's record -- but momentum is also the
    # most heavily published anomaly there is, and published anomalies decay. The
    # haircut removes a fraction of the premium while keeping momentum's volatility
    # and crash risk, which is the pessimistic case worth pricing: you carry the
    # factor's downside without being paid for it.
    momentum = factors["mom"] - momentum_premium_haircut * factors["mom"].mean()

    synthetic = (
        stats["beta_market"] * factors["mkt_rf"]
        + stats["beta_momentum"] * momentum
        + factors["rf"]
    )
    if include_alpha:
        synthetic = synthetic + stats["alpha_daily"]
    live = load_total_return(ticker, refresh=refresh).pct_change().dropna()
    overlap = synthetic.index.intersection(live.index)
    synthetic_only = synthetic.index.difference(overlap)

    if include_residual:
        draws = moving_block_paths(
            resid.to_numpy(),
            n_paths=1,
            horizon=len(synthetic_only),
            block=residual_block,
            seed=seed,
        )[0]
        # OLS residuals are mean-zero by construction, but any single resampled draw
        # is not: its sample mean is noise worth roughly 1%/yr at this length. Left
        # in, that noise lands straight in the drift estimate and so in Kelly, which
        # is drift/variance -- an earlier version of this code shifted mu by 2.3%/yr
        # on the luck of one draw. Residuals are here to supply idiosyncratic
        # variance, not drift, so the draw is demeaned. It is demeaned over exactly
        # the days it is used on, since the live period below overwrites the rest.
        synthetic.loc[synthetic_only] += draws - draws.mean()

    combined = synthetic.copy()
    combined.loc[overlap] = live.reindex(overlap)

    frame = pd.DataFrame({"ret": combined.sort_index()})
    benchmark = load_benchmark_rate(refresh=refresh)
    frame["bm"] = benchmark.reindex(frame.index).ffill()
    # Fed Funds only starts in July 1954; before that fall back to the contemporaneous
    # T-bill. French's rf is a daily rate over *trading* days that compounds to the
    # monthly bill rate, so it annualises by 252, not by the 360-day interest basis.
    # (Checked against known levels: 2024 gives 5.0%, 1981 gives 13.6%.)
    frame["bm"] = frame["bm"].fillna(
        factors["rf"].reindex(frame.index) * TRADING_DAYS_PER_YEAR
    )
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
