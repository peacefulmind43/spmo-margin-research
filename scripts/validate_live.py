#!/usr/bin/env python3
"""Run chronological diagnostics; produce provenance and explicit evidence limits."""
import argparse
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess

from spmo_margin import data
from spmo_margin.validation import ValidationConfig, walk_forward

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", type=int, default=128)
    ap.add_argument("--forecast-years", type=int, default=3, help="explicit training forecast horizon")
    ap.add_argument("--first-year", type=int, default=2019)
    ap.add_argument("--last-year", type=int, default=2026)
    ap.add_argument("--equity", type=float, default=50000.)
    ap.add_argument("--monthly-withdrawal", type=float, default=0.)
    ap.add_argument("--financing", choices=["asof_constant", "paired_historical"], default="asof_constant")
    ap.add_argument("--output", type=Path, default=ROOT / "results" / "validation")
    args = ap.parse_args()
    if min(args.paths, args.forecast_years, args.equity) <= 0 or args.monthly_withdrawal < 0 or args.last_year < args.first_year:
        ap.error("positive paths/horizon/equity and a valid year range are required")
    config = replace(ValidationConfig(), paths=args.paths, forecast_years=args.forecast_years,
        first_test_year=args.first_year, last_test_year=args.last_year, equity=args.equity,
        monthly_withdrawal=args.monthly_withdrawal, financing=args.financing)
    args.output.mkdir(parents=True, exist_ok=True)
    print("Retrospective chronological diagnostic. This is NOT an untouched test or live sizing approval.", flush=True)
    folds, scores, summary, skips, curves = walk_forward(config)
    for name, table in [("folds", folds), ("training_scores", scores), ("summary", summary),
                        ("skipped_folds", skips), ("equity_curves", curves)]:
        table.to_csv(args.output / f"{name}.csv", index=False)
    names = ["french_factors.csv", "fed_funds.csv", *[f"px_{t}.csv" for t in config.tickers]]
    hashes = {name: hashlib.sha256((data.CACHE_DIR / name).read_bytes()).hexdigest() for name in names}
    report = {"validation_state": "retrospective_diagnostic", "live_sizing_approved": False,
        "config": asdict(config), "data_sha256": hashes,
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for folder in ["spmo_margin", "scripts"] for p in sorted((ROOT / folder).glob("*.py"))},
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ["numpy", "pandas", "scipy", "yfinance"]},
        "limitations": [
            "Universe chosen retrospectively; closed-fund total returns are not verified or included.",
            "Historical dates have been inspected before; no untouched or prospective holdout is claimed.",
            "Factor and adjusted-price caches are current vintages; observation-date cutoffs do not model publication delays or revisions.",
            "The 2pp mean revision is a declared sensitivity, not an estimated selection-bias correction.",
            "Historical DFF plus current Pro spreads is a funding proxy, not actual past IBKR contracts.",
            "25%/50% maintenance stress is illustrative; actual instrument/account requirements are unverified.",
            "30bp annual asset drag approximates withholding; no tax-residency determination or tax deduction.",
            "Real household funding/withdrawal needs and their correlation with market stress remain unspecified.",
            "Training uses a stated three-year default forecast; chronological results cover only the listed dates.",
        ]}
    (args.output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(summary.round(4).to_string(index=False), flush=True)
    print(f"\nEvidence saved to {args.output}; live_sizing_approved=false")


if __name__ == "__main__":
    main()
