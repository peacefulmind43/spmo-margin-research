# Live-use review: accounting improved, sizing remains unidentified

Reviewed 11 September 2026. Numerical source commit: `30b0c1c0eb72aeb632b4fd38c0535ea5ecbd1018`.
This report supersedes earlier personal sizing judgments. Assumptions here use
standard IBKR Pro USD financing with **zero Australian surcharge**. IBKR LLC is
the stated entity; the actual plan, instrument requirements and any broker-specific
surcharge have not been read from an account statement or trade preview.

**The present evidence does not identify a defensible single live leverage target.**
The baseline log-growth experiment picks 2x at its imposed grid ceiling. A declared
2pp expected-return reduction picks 1.5x; 4pp picks 1x. These are conditional model
answers, not three interchangeable recommendations. Low aversion to volatility
does not establish which expected return is justified. The prior 1x judgment was
not an estimate of the user's wealth-maximising leverage, and is retired as such.

## What was implemented and tested

The new chronological runner truncates raw prices, factors and funding observations
before fitting each training fold. A regression test corrupts every future series
and requires the earlier reconstruction and selected targets to remain unchanged.
Five funds use the same grid, account rules and selection procedure. Equity and
the existing position carry between years. No annual account reset creates free
rebalancing or erases borrowing history. This is a retrospective diagnostic:
these dates and tickers have already influenced research, and current-vintage
observations do not reproduce publication delays and subsequent revisions.

The two independent simulators now support daily/path-specific maintenance,
borrowing caps, asset-level drag, financing surcharges, withdrawals, and resuming
an existing position. Costs are charged on actual trades. Unpaid withdrawals,
remaining debt at ruin, and gross deposits are explicit outputs. Forecasting
parameters, source/data hashes and dependency versions accompany the results.

**233 tests passed. The scalar/vector agreement tolerance remains 1e-9.**
All seven scripts exited successfully on the final numerical source. The new
validation uses its default 128 paths and three-year training horizon; the new
stress run uses 512 paths and ten years. The four older Monte Carlo scripts were
rerun with 128 paths as regression smoke tests; `optimise_target.py` additionally
used `--horizon 10 --gamma 1`. These smoke runs do not establish the convergence
of their default high-resolution recommendations. The original five scripts had
already been run at their defaults in the first audit. Exact commands and output
logs for this round are in [the execution record](../results/review/execution.json).
GitHub CI now runs the test suite on pushes and pull requests.

## Material sensitivities, holding preferences constant

These experiments use expected log wealth, $50,000 initial equity, no deposits or
withdrawals, the same 512 sampled ten-year paths, a fixed 10% relative rebalance
band, standard USD financing, 30bp/year asset drag and a 2x opening/rebalance cap.
The forecast horizon is an explicit scenario, not the investor's inferred horizon.
The reported growth is `exp(mean(log(terminal wealth / initial wealth))/10) - 1`.
No grid point is refined into a spurious third decimal.

| Scenario | Best tested leverage | Growth at that leverage | Growth at 2x |
| --- | --- | --- | --- |
| constant_rate | 2.00x | 14.20% | 14.20% |
| mean_minus_2pp | 1.50x | 10.11% | 9.73% |
| mean_minus_4pp | 1.00x | 7.33% | 5.47% |

The 2pp scenario reduces the selected gross exposure by **25%**, and the 4pp
scenario by **50%**, relative to the 2x baseline. At $50,000 equity, 2x → 1.5x
also halves principal borrowing, from $50,000 to $25,000 before fees. This is a
failure of robustness to expected return, **not a demonstrated 2pp or 4pp bias**.
The deductions are declared adverse scenarios, not estimated posteriors or a
calibrated multiple-testing correction. They do not follow merely from being
risk averse. These calculations do not establish a >10% optimum shift attributable
solely to the new accounting bug fixes.

## What the actual ETF test says

The observation-date folds cover 2019-01-02 through 2026-07-31, approximately 7.56 trading
years. Each year's leverage is selected using earlier dated observations; test
returns are actual adjusted ETF returns. Training is still largely reconstructed
pre-inception history. Historical DFF financing, 30bp drag, transaction costs and
25% → 50% maintenance after a previous-close drawdown worse than 20% are included.

| Fund | Fixed 1x | Fixed 1.5x | Fixed 2x | Annual fitted selection | Selection with mean −2pp |
| --- | --- | --- | --- | --- | --- |
| SPMO | 22.13% | 29.25% | 36.18% | 32.17% | 26.65% |
| MTUM | 16.53% | 20.01% | 23.53% | 22.46% | 18.10% |
| PDP | 14.26% | 17.13% | 18.11% | 15.11% | 12.15% |
| QMOM | 15.61% | 17.95% | 18.63% | 16.30% | 13.05% |
| MMTM | 15.52% | 19.19% | 21.68% | 18.54% | 14.41% |

Fixed 2x beats the annually fitted selection on **all five funds** in this slice.
It also beats fixed 1x on all five. The 2pp-adjusted selection trails fixed 1x on
PDP, QMOM and MMTM. Thus it would be wrong to claim the test proves that leverage
fails, or that an arbitrary haircut improves realised performance. It supplies
no evidence that this annual optimisation procedure added value over fixed 2x
on these observations. It also supplies no untouched test of choosing 2x today.
The funds share market exposure; they are not five independent experiments.

The large SPMO advantage is still a warning about ticker selection. Delisted funds
and verified liquidation payouts are absent; the broader search history is unknown.
Old exploratory closed-fund numbers remain labelled unvalidated in the first audit.
Annual refitting allows estimated exposures to change between folds, but does not
propagate a calibrated future loading process or uncertainty in expected return
through the three-year training forecast. That model omission remains.

## Rates, maintenance and access to money

At 2x, jointly sampling historical return/rate blocks and rescaling the rates to
the same 3.63% mean changes annual geometric growth by **-0.84 bp**,
median CAGR by **+6.14 bp**, and fifth-percentile CAGR by **+12.23 bp**.
The best grid point remains 2x. This experiment does not support a large positive
effect from rate timing. The short blocks do not preserve whole monetary-policy
cycles or establish a causal policy response. The first audit's complete GFC,
COVID and 2022 replays remain relevant: easing helped in some crashes and
inflationary tightening hurt in another. A lower average rate must not be
mislabelled a crisis-timing benefit.

Under the illustrative 75% maintenance stress, 2x's geometric growth is
13.73%, versus
14.19% at fixed 25%; the best
grid point is still 2x. At 50% stress maintenance, at least one forced sale occurs
on 96.88% of the 2x paths. This high
frequency includes repeated small sales because 2x sits exactly on the 50%
maintenance boundary; it is not a calibrated probability of a real IBKR margin call.
The model has no extra liquidation buffer or complete Reg-T/SMA ledger. Actual
broker requirements can be higher than regulatory minima, and brokers can sell
without first obtaining consent. [FINRA margin account guidance](https://www.finra.org/investors/investing/investment-accounts/brokerage-accounts).

In a separate **$1,000 monthly spending, zero new income, ten-year** scenario,
the fraction with at least one unpaid request is 94.73%
at 1x and 73.05% at 2x, while the corresponding
simulated ruin fractions are 0.00% and 0.98%.
This is not a forecast of household spending. It demonstrates that an account can
stay above zero and still fail to provide needed money. More leverage helps in
this particular spending scenario but does not make its funding plan viable.
TWR excludes paid withdrawals, so it cannot by itself measure household success.
`ruin_deficit` records debt at failure, not a complete post-default settlement or
future debt-interest calculation. Deposits do not resurrect a ruined account.

## Concrete bugs and comment/output disagreements repaired

| Failing case | Previous error | Corrected result and regression |
| --- | --- | --- |
| Cash-only $5,000 account, flat returns, zero rates | Zero stock position was treated as bankruptcy | Cash survives; withdrawals are cashflows, not losses. `test_zero_stock_account_survives_and_withdrawal_is_not_a_loss` |
| Target 1.5x, maintenance rises to 75%, daily rebalance | After forced liquidation, rebalance could buy back an impermissible 1.5x position | Holding is capped at 1/0.75 = 1.333x, 11.1% below target; a feasibility correction, not a newly estimated utility optimum. `test_rebalance_cannot_repurchase_an_illegal_position_after_requirement_increase` |
| $5,000 equity, 2x exposure, an 80% gap loss, financing disabled | A zero floor could be read as forgiving the debt | Active account zero and remaining debt $3,000 are both reported; net equity −$3,000. `test_gap_deficit_is_reported_instead_of_forgiving_the_remaining_debt` |
| Forced sale/rebalance with nonzero costs | Fee and resulting holding did not correspond to the same actual trade | Exact self-financing equations and independent parity checks; direct contribution purchases also pay fees |
| Cash deposit and withdrawal on the same day | Net cashflow could erase the gross amount funded | Gross deposits and net external cashflows are tracked separately |
| Withdrawal after ruin, including later annual folds | Household funding needs could disappear from reporting | Each unpaid scheduled request remains a failure; no account resurrection |
| Nonuniform band grid `[.08, .10, .125, .15]`, quadratic peak `.112` | Equal-spacing interpolation was applied to unequal spacing | Actual coordinates recover `.112`; interpolation is not estimation confidence |
| CRRA gamma below 1 with zero terminal wealth | Zero wealth was universally assigned negative infinite utility | Finite CRRA when gamma < 1; log and gamma >= 1 retain negative infinity |
| Block of full sample length; final possible block start | Equality was rejected and the last observation was unreachable | Whole-sample block is accepted and all valid starts are included |
| Negative benchmark and very large balances | Universal 75bp total-rate floor and obsolete large-loan tiers | Zero floor on benchmark before adding spread; published tier boundaries/surcharge. Small positive-rate first-tier borrowing is unchanged |
| Calculator at 1x / above a configured opening cap | Said unlevered stocks could never wipe out; showed no opening infeasibility | Full asset loss is a 100% equity loss; infeasible openings are marked |

The old optimiser also quoted an uncomputed 90% interval and described precision
to three decimals as a solution. Those claims are removed. The README's prior
recommendations are explicitly retired, not silently replaced by another point
estimate. Median CAGR is no longer described as identical to expected-log Kelly.
The rebalance band stays a declared 10% policy for these comparisons; its optimum
has not become statistically identified. Published tier/benchmark-floor and
cash-interest NAV rules are linked at the source: [IBKR margin terms](https://www.interactivebrokers.com/en/trading/margin-rates.php)
and [IBKR credit interest](https://www.interactivebrokers.com/en/accounts/fees/pricing-interest-rates.php).

## Highest-value remaining work

1. **Estimate the prospective net premium after ticker and research selection.**
   Build a dated universe including failed/closed funds, reconcile distributions
   and liquidation proceeds, and obtain daily S&P 500 Momentum total-return index
   data with explicit pre-launch backtest status. Compare against fixed policies
   using a frozen protocol. The measured 25–50% leverage shifts above explain why
   this ranks first. More bootstrap paths cannot recover missing independent data.
2. **Specify spending and income during market stress.** The relevant objective
   involves accessible wealth and spending, not an unstated ten- or forty-year
   terminal account alone. Model deposits, emergency withdrawals and income loss
   jointly with market conditions; retain unpaid-request and deficit outputs.
   The illustrated funding failures can dominate a small difference in CAGR.
3. **Reconcile execution constraints with the actual IBKR account.** Obtain dated
   initial/maintenance requirements, SMA/buying power and the applied financing
   plan, then test household cash outflows and requirement shocks together.
   A 75% requirement permits at most 1.333x at the boundary, materially below a 2x
   opening target. Current scenarios do not predict when that requirement occurs.

An S&P index proxy and exposure-regime model belong in the first item; neither
is fixed by agreeing reconstructions or by refitting betas annually. Actual
withholding, FX needs and distribution timing also remain separate from the
30bp sensitivity. There is no statistical basis here for claiming that either
1x or 2x is the unique live answer for indefinite holding with unspecified cashflows.
