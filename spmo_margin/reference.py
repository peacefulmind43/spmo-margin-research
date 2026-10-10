"""Long-history momentum series kept **for reference only**.

Neither series here is SPMO or the S&P 500 Momentum Index, and nothing in this module
is spliced into, regressed onto, or substituted for the index history in
:mod:`spmo_margin.data`. They are other published momentum portfolios with decades of
record, used to show what the 1994-2016 gap -- and earlier bear markets -- looked like
for the same kind of strategy.

* **Ken French "BIG HiPRIOR"** -- daily since 1926. Value-weighted big stocks
  (above the NYSE median) in the top 30% by prior 12-2 month return, re-formed
  monthly. Broader than the index (several hundred stocks against 100), ranks on raw
  rather than risk-adjusted momentum, and pays no fee.
* **AQR U.S. Large Cap Momentum Index** -- *monthly* since 1980. Top third by 12-2
  month return of the 1,000 largest US stocks, cap weighted, rebalanced quarterly,
  calculated by S&P Custom Indices. Monthly data cannot drive the daily margin engine
  (no intramonth drawdowns, no intramonth margin calls), so it gets a cruder monthly
  treatment and is labelled as such.

Raw downloads are cached under ``data/reference/``, which is git-ignored: AQR's
terms forbid redistribution, and this repository is public.
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .data import CACHE_DIR, load_benchmark_rate
from .margin import TRADING_DAYS_PER_YEAR

REFERENCE_DIR = CACHE_DIR / "reference"

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FRENCH_FACTORS = f"{FRENCH_BASE}/F-F_Research_Data_Factors_daily_CSV.zip"
FRENCH_PORTFOLIOS = f"{FRENCH_BASE}/6_Portfolios_ME_Prior_12_2_Daily_CSV.zip"
AQR_MOMENTUM = (
    "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Momentum-Indices-Monthly.xlsx"
)


def _path(name: str) -> Path:
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    return REFERENCE_DIR / name


def _read_french_zip(url: str, columns: list[str], stop_at: str | None = None) -> pd.DataFrame:
    """Parse one of Ken French's daily zips into decimal returns.

    The portfolio files hold value-weighted returns followed by equal-weighted ones
    under identical date stamps, so the parse stops at ``stop_at`` and refuses
    duplicate dates rather than silently doubling every row.
    """
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
    return frame.set_index("date").astype(float).sort_index() / 100.0


def french_big_hiprior(refresh: bool = False) -> pd.DataFrame:
    """Daily BIG HiPRIOR returns since 1926, with a funding benchmark alongside.

    The benchmark is Fed Funds from July 1954 and French's daily T-bill rate before
    it. That rate compounds over trading days, so it annualises by 252.
    """
    path = _path("french_big_hiprior.csv")
    if path.exists() and not refresh:
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        portfolios = _read_french_zip(
            FRENCH_PORTFOLIOS,
            ["small_lo", "small_mid", "small_hi", "big_lo", "big_mid", "big_hi"],
            stop_at="Equal Weighted",
        )
        rf = _read_french_zip(FRENCH_FACTORS, ["mkt_rf", "smb", "hml", "rf"])["rf"]
        frame = pd.DataFrame({"ret": portfolios["big_hi"], "rf": rf}).dropna()
        frame.to_csv(path)
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    fed_funds = load_benchmark_rate(refresh=refresh)
    bm = fed_funds.reindex(frame.index, method="ffill")
    bm = bm.fillna(frame["rf"] * TRADING_DAYS_PER_YEAR).clip(lower=0.0)
    return pd.DataFrame({"ret": frame["ret"], "bm": bm})


def aqr_large_cap_momentum(refresh: bool = False) -> pd.DataFrame:
    """Monthly AQR U.S. Large Cap Momentum Index returns since 1980, with Fed Funds."""
    path = _path("aqr_momentum_monthly.xlsx")
    if not path.exists() or refresh:
        from curl_cffi import requests

        response = requests.get(AQR_MOMENTUM, impersonate="chrome", timeout=120)
        response.raise_for_status()
        path.write_bytes(response.content)
    raw = pd.read_excel(path, sheet_name="Returns", header=None)
    header = raw.index[raw.iloc[:, 0].astype(str).str.strip() == "Month"][0]
    column = list(raw.iloc[header]).index("U.S. Large Cap")
    body = raw.iloc[header + 1 :, [0, column]].dropna()
    series = pd.Series(
        body.iloc[:, 1].astype(float).to_numpy(),
        index=pd.DatetimeIndex(pd.to_datetime(body.iloc[:, 0])).normalize(),
    ).sort_index()
    if series.index.has_duplicates:
        raise ValueError("duplicate months in the AQR file")
    fed_funds = load_benchmark_rate(refresh=refresh)
    # average benchmark over each month, since that is what a month's interest pays
    monthly_bm = fed_funds.resample("ME").mean().reindex(series.index, method="ffill")
    return pd.DataFrame({"ret": series, "bm": monthly_bm})


def monthly_levered_path(
    frame: pd.DataFrame, leverage: float, spread: float = 0.015
) -> pd.Series:
    """Equity of an account reset to ``leverage`` at every month end.

    Deliberately crude, because monthly data allows nothing better: no intramonth
    drawdown, no margin call until a month closes, no tiering, a flat spread over
    the monthly-average benchmark. It *understates* risk relative to the daily
    engine and is only for comparing episodes across decades.
    """
    borrow = (frame["bm"] + spread) / 12.0
    step = 1.0 + leverage * frame["ret"] - (leverage - 1.0) * borrow
    equity = step.clip(lower=0.0).cumprod()
    return equity.where(equity.cummin() > 0, 0.0)


def monthly_kelly(frame: pd.DataFrame, spread: float = 0.015) -> float:
    """Leverage maximising mean monthly log growth on the observed months."""
    from scipy.optimize import minimize_scalar

    returns = frame["ret"].to_numpy()
    borrow = ((frame["bm"] + spread) / 12.0).to_numpy()

    def negative_growth(f: float) -> float:
        step = 1.0 + f * returns - (f - 1.0) * borrow
        return np.inf if np.any(step <= 0) else -float(np.mean(np.log(step)))

    return float(minimize_scalar(negative_growth, bounds=(0.0, 6.0), method="bounded").x)


def overlap_with_index(reference: pd.Series, index_returns: pd.Series) -> dict[str, object]:
    """How closely a reference series moved with the S&P 500 Momentum Index.

    Compared on monthly compounded returns, so a daily and a monthly reference are
    measured the same way. Descriptive only: nothing here adjusts either series.
    """
    def to_month(r: pd.Series) -> pd.Series:
        # compounding within each month is the identity on an already-monthly series
        return (1.0 + r).resample("ME").prod(min_count=1) - 1.0

    a, b = to_month(index_returns).align(to_month(reference), join="inner")
    a, b = a.iloc[1:-1], b.iloc[1:-1]  # drop partial first/last months
    beta = float(np.cov(b, a, ddof=1)[0, 1] / np.var(a, ddof=1))
    return {
        "window": [str(a.index[0].date()), str(a.index[-1].date())],
        "months": int(len(a)),
        "correlation": float(np.corrcoef(a, b)[0, 1]),
        "beta_to_index": beta,
        "index_cagr": float((1 + a).prod() ** (12 / len(a)) - 1),
        "reference_cagr": float((1 + b).prod() ** (12 / len(b)) - 1),
        "index_vol": float(a.std(ddof=1) * np.sqrt(12)),
        "reference_vol": float(b.std(ddof=1) * np.sqrt(12)),
    }
