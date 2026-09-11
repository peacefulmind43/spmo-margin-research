# SPMO margin: validate the decision before sizing it

**No live leverage target has been validated by this repository.** Earlier
recommendations of 1.0x, 1.475x and approximately 2.0x mixed different objectives,
financing assumptions and standards of evidence. A conditional fitted optimum
is not a selection-adjusted position recommendation. Low aversion to volatility
does not make the estimate of future return more reliable.

This repository now provides chronological selection diagnostics and account
stress tests. It does not send orders. The previous conclusions are
[archived and explicitly retired](docs/historical-conclusions-2026-09-10.md).
The [first adversarial audit](audits/2026-09-11/adversarial-review.md) documents
earlier bugs and unresolved data problems; its personal sizing judgment is not
an empirically validated optimum either.

## Changes for live-use review

- Training truncates raw ETF prices, factors and financing at an explicit `as_of`
  date **before** estimating exposures/residuals or reconstructing prior history.
  Tests corrupt future data and require earlier fits and selections to stay unchanged.
- A chronological runner selects leverage using observations dated through the previous
  December, then evaluates the next year's actual ETF returns. Equity and position
  carry across folds; there is no annual account reset.
- Both independent simulators support changing maintenance, explicit withdrawals,
  opening/rebalance leverage caps and dollar borrowing caps. Rebalancing cannot
  restore a position above the maintenance ceiling.
- Cash-only accounts survive. Liquidation/rebalancing fees satisfy actual account
  cash conservation. Unfundable withdrawals are recorded as **unpaid**.
- Calculator output marks infeasible opening positions and no longer recommends
  a target or says unlevered stocks can never wipe out. Optimiser results are
  explicitly conditional research outputs, not rebalance instructions.
- Standard Pro USD tiers and credit-interest NAV scaling were checked against
  published terms on 2026-09-11. Regional surcharges are separate inputs.

The scalar/vector **1e-9 agreement requirement remains mandatory**. Numerical
agreement protects accounting; it does not validate the return model.

## Run

Python 3.11 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python scripts/validate_live.py
python scripts/stress_account.py --equity 50000 --years 10
python scripts/position_calculator.py --equity 50000 --leverage 1.5 --maintenance 0.50
```

These are example inputs, not instructions to trade 1.5x or hold for ten years.

`validate_live.py` defaults to SPMO, MTUM, PDP, QMOM and MMTM, a retrospectively
chosen universe of survivors. It uses 2019–2026 annual test folds, at least 756
prior live observations, a **three-year training forecast**, 128 bootstrap paths,
a fixed `[1, 1.25, 1.5, 1.75, 2]` grid and expected log wealth. The training
horizon is an explicit forecasting choice, not an inferred investor holding period.
Training financing defaults to the last known DFF proxy plus standard Pro spreads;
test financing follows the actual historical DFF proxy.

Two forecast rules are tested: the fitted growth estimate and a declared
2-percentage-point downward revision to expected asset return. The latter is a
sensitivity, **not a calibrated overfitting correction**. Fixed 1x, 1.5x and 2x
policies are retained as benchmarks. No winner is selected from test results
and relabelled a live recommendation.

```bash
python scripts/validate_live.py --financing paired_historical --output results/validation-paired
python scripts/validate_live.py --monthly-withdrawal 1000 --output results/validation-spending
```

The first alternative samples return/rate blocks jointly in training; the second
is an explicit spending scenario, not a forecast of household expenses.

The runner writes per-year selections, scores, outcomes, continuous equity curves,
omitted folds and a manifest of settings, source/input hashes and limitations.
`live_sizing_approved` is **false**: this runner cannot issue trading approval.
Read [`summary.csv`](results/validation/summary.csv),
[`folds.csv`](results/validation/folds.csv) and
[`manifest.json`](results/validation/manifest.json) together.

`stress_account.py` compares constant financing against jointly sampled return/rate
blocks rescaled to the same average benchmark, 50%/75% stress maintenance,
2pp/4pp lower mean returns and monthly withdrawals. Stress sizes have no asserted
real-world probability. Read [`scenarios.csv`](results/stress/scenarios.csv) and
[`settings.json`](results/stress/settings.json).

## Account mechanics and boundaries

The account holds asset value `P`, debt `D` (negative means cash) and equity
`E = P - D`. Daily steps accrue financing, apply the low/close return scenario,
enforce maintenance, add contributions, attempt withdrawals, then rebalance.
Withdrawals use cash before selling assets; further debt repayment is modelled
if collateral is insufficient. Failed requests are unpaid and unexecuted.
`withdrawal_failures > 0` is a household funding failure even if equity remains
positive. Ruined accounts are not resurrected by deposits. Full voluntary account
closure is not modelled: withdrawals exhausting equity are rejected and recorded.
After a gap through zero equity, `ruin_deficit` preserves the remaining debt and
`terminal_net_equity` can be negative. Legacy `terminal_equity` and return metrics
floor the active trading account at zero; they do not imply debt forgiveness.

`Account.max_leverage=2` and `simulate_paths(..., max_leverage=2)` impose a supplied
opening/rebalance cap. Low-level default `None` retains research experiments above
2x. Existing positions can drift above an opening limit; borrowing to open a new
position is a different action. This is not a complete Reg-T/SMA or portfolio-margin
implementation. `max_loan` caps initial debt and rebalancing targets; interest can
temporarily exceed that cap before rebalancing.

Maintenance accepts a scalar, daily series or (vector simulator) one path per return
path. Validation raises it from 25% to 50% when the **previous close's** asset
drawdown exceeds 20%. This is causal scenario construction, not IBKR's house-margin
algorithm. Liquidating to the requirement has no additional buffer and can cause
repeated small sales in stress.

`annual_drag=.003` deducts 30bp/year from asset returns as a withholding sensitivity.
It does not model treaty eligibility, distribution dates, capital-gains taxes, FX
effects or interest deductibility. `interest_tax_shield=0` is the default.

## Evidence still missing

1. **Ticker selection and survivorship.** SPMO was selected after doing well.
   Peer comparisons cannot reconstruct all funds/rules considered before that
   choice. DWAQ, DUDE and LETB appeared in the earlier exploratory audit, but their
   distribution/closure data remain insufficiently verified for this validation
   set. Their omission is a limitation, not a passing check.
2. **Independent long-run SPMO observations.** Most pre-2015 history is a factor
   reconstruction. The S&P 500 Momentum Index is a closer methodological proxy,
   but its pre-launch history is backtested and a validated daily total-return
   series is still missing here. Two reconstructions agreeing is not independent
   confirmation.
3. **Untouched observations and household cashflows.** These dates have already
   been inspected. Causally refitted walk-forward diagnostics cannot turn them into
   pristine prospective evidence. Current data vintages can include revisions;
   observation-date cutoffs do not model publication delays.
   Real withdrawals, contributions and their correlation with market stress remain
   unspecified.

The question is whether additional borrowing retains an adequate net growth
advantage after these uncertainties. Choosing a smaller number by eye, or halving
fitted Kelly, does not answer that question statistically.

## Older experiments

These remain conditional research. Files directly under `results/` are historical
snapshots; new chronological results are under `results/validation/`.

```bash
SPMO_RESULTS_DIR=results/research python scripts/run_analysis.py
SPMO_RESULTS_DIR=results/research python scripts/overfitting_audit.py
SPMO_RESULTS_DIR=results/research python scripts/funding_strategies.py
SPMO_RESULTS_DIR=results/research python scripts/optimise_target.py --horizon 40 --gamma 1
```

The audited 365/252 conversion for calendar-day financing on a 360-day basis is
retained. Intraday dips are scenarios, not reconstructed intraday prices. A band
is a declared policy choice, not a reliably identified optimum.

## Data and primary references

Cached adjusted ETF prices originate from Yahoo Finance via `yfinance`; factors
from Ken French; DFF from FRED. Checksums pin run inputs. These are not reconciled
custody records or historical publication vintages.

- [IBKR rates and tier surcharges](https://www.interactivebrokers.com/en/trading/margin-rates.php)
- [IBKR benchmark methodology](https://brokerage.ibkr.com/en/pricing/reference-benchmark-rates-int.php)
- [IBKR credit interest](https://www.interactivebrokers.com/en/accounts/fees/pricing-interest-rates.php)
- [Australian surcharges when applicable](https://www.interactivebrokers.com.au/en/trading/margin-rates-au.php)
- [FINRA margin requirements](https://www.finra.org/investors/investing/investment-accounts/brokerage-accounts)
- [Bailey et al., Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
