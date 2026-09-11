# Adversarial review of spmo-margin-research

Reviewed 11 September 2026, commit `3b181bfab767f06a72805abd09cd521ed6a7d5da`.

**My sizing number is 1.0x: zero margin borrowing against this position on the evidence currently available.** This is a decision under unresolved model and account uncertainty, not a claim that 1.0x maximises the repository's fitted utility. It is also not a recommendation to put all investable wealth in SPMO. Conditional on a 40-year holding period, USD 100,000 equity, standard IBKR Pro USD financing, no contributions, and CRRA risk aversion of 1.5, my central model sensitivity is closer to **1.3x** after propagating plausible uncertainty about expected return. Under the Australian standard-facility surcharge plus withholding and that uncertainty, it is **1.0x**.

I requested horizon, account size/currency, tax residence and loss tolerance. None was supplied during the review, so these remain stated scenarios, not inferred personal circumstances. The difference from the README's 1.475x is a 32% reduction in gross exposure and elimination of its 47.5%-of-equity loan.

**What I actually ran.** I cloned the repository, installed `pip install -e ".[dev]"` into an isolated virtual environment, and ran pytest and all five scripts with their default settings; position_calculator requires an argument, for which I supplied `--equity 100000`. All five exited successfully. The original suite passed **117 tests**. I recorded a provisional assessment before opening README.md. Some source comments disclosed previous conclusions, so this was not a perfectly blind review; the note records that limitation.

I added a small local patch for the ruin-metrics error, support for paired time-varying financing paths, and the incorrect constrained objective. The resulting suite passes **175 tests**, retaining the 1e-9 agreement requirement and adding ruin and variable-rate cases. The remote repository was not changed.

**Experimental basis.** Main fine-grid results below use 3,000 common return paths, 40 years, the repository's 21-day block sampler and seed 11, USD 100,000 starting equity, monthly rebalancing, the original tier schedule, zero alpha and the original demeaned block residual construction. Fine grid: 0.025x. Peer and loading reconnaissance: 1,500 common paths and a 0.1x grid. Those coarser results are deliberately reported to one decimal. All figures are conditional simulations, not population risk estimates. Archived data in the repo were preserved; new peer histories were truncated to the factor-data endpoint, 31 July 2026, for fitting.

For speed I wrote a compiled audit implementation and checked it against **both** Python simulators over 120 non-ruin configurations: maximum scaled discrepancy was 2.45e-15. Another 48 configurations check variable financing paths at 1e-9, and deterministic cases check liquidation at 25–100% maintenance. Stress-dependent requirements and persistent drift are explicit extensions described below, not broker-calibrated forecasts.

**Changes exceeding 10%, with the cases that produce them.** Percentages in this table refer to gross leverage, not the much more sensitive loan amount.

| Finding | Controlled case | Change | Classification |
|---|---|---|---|
| Missing broker-entity surcharge | 40y, gamma 1.5; add applicable IBKR Australia 2% USD surcharge | 1.475x → 1.10x, −25% | Omitted financing cost; applicability depends on account |
| Expected-return uncertainty is not propagated | Same mean return; a persistent, zero-mean 2 percentage-point annual drift uncertainty, drawn once per path | 1.475x → 1.30x, −12%; at 3 points: 1.125x, −24% | Material model omission; scenarios, not a fitted posterior |
| Ticker dependence | Identical construction, gamma 1.5: SPMO versus PDP and QMOM | Lifetime fits: 1.5x → 1.2x / 1.0x; common-period SPMO 1.4x versus QMOM 1.0x | Measured failure of generalisation, not an estimated selection-bias correction |
| Horizon label changes the objective | Keep gamma 1.5 and run ten years | About 1.40x, versus README's 1.112x ten-year label, +26% | Documentation/conclusion error |
| Constrained optimiser maximises leverage, not growth | Set `--dd-threshold 1` on the original 40y/3,000-path grid | Original returns 2.80x; actual median-growth grid maximum is 2.05x, −27% | Plain code error; default one-third constraint happens to bind below the growth peak |

The last row is not an endorsement of 2.05x. It is a failing test of whether the code solves its declared objective. At the default constraint the corrected piecewise-linear solution remains approximately 1.462x. The condition “largest feasible exposure also maximises growth” is not generally true.

**1. Ticker selection is testable, although this test cannot eliminate it.**

I ran `extend_with_factors(ticker)` with zero alpha and the same residual method, followed by the same financing/account simulation and utility grid, on MTUM, PDP, QMOM and MMTM. I also repeated the construction with all five surviving funds fitted over the same price window, 2 December 2015–31 July 2026; the first common return is 3 December.

| Fund | Actual CAGR, common return window | Gamma-1.5 optimum, own full fit | Optimum, common-window fit |
|---|---:|---:|---:|
| SPMO | 18.69% | 1.5x | 1.4x |
| MTUM | 15.40% | 1.5x | 1.4x |
| PDP | 11.69% | 1.2x | 1.3x |
| QMOM | 11.29% | 1.0x | 1.0x |
| MMTM | 13.48% | 1.4x | 1.4x |

SPY returned about 14.64% over that common window. Thus this includes actual underperformers. MTUM supports a similar conditional leverage choice; QMOM decisively does not. The result is not unique to the winning ticker, but it is not a general result for momentum funds either.

The construction also gives weaker funds an artificial rehabilitation: their negative fitted intercept is set to zero. QMOM's fitted intercept is about −4.55%/year, yet the reconstructed century has a 14.72% arithmetic mean return. Zero-alpha treatment is symmetric algebraically, but it removes both a winner's unexplained success and a loser's unexplained failure. Agreement between survivors after this operation cannot establish that selection has been corrected.

I obtained and ran exploratory, date-truncated histories for liquidated **DWAQ, DUDE and LETB**, producing gamma-1.5 optima of approximately 1.1x, 1.3x and 1.0x respectively. Those are diagnostics of the reconstruction, which extrapolates exposures beyond closure, not implementable strategies in those dead funds. Closure is corroborated by [Invesco's DWAQ notice](https://www.invesco.com/us-rest/contentdetail?contentId=bcc53c5611e6f610VgnVCM1000006e36b50aRCRD), [DUDE's SEC filing](https://www.sec.gov/Archives/edgar/data/1592900/000159290023000914/dude_497xliquidation.htm), and [LETB's SEC filing](https://www.sec.gov/Archives/edgar/data/1408970/000182912623006263/advisorshares_497.htm).

**These closed-fund numbers are not validated total-return evidence.** Yahoo supplied zero distributions for all three and prices after documented wind-down dates for some. I removed post-life observations and restricted DWAQ to its later momentum period, but did not independently reconstruct final distributions or liquidation proceeds. DWLV returned only one observation and was excluded. AMOM/FMTM downloads were not promoted into the comparison because their lifecycle information was unresolved. Closing an ETF also does not imply its NAV went to zero; none was treated as a total loss merely because it closed. The bundle retains the downloads and exclusions. A complete inception-to-liquidation fund universe with validated NAV/distribution histories remains missing.

**2. Falling rates help in some crashes, but I do not find a large omitted timing benefit at 1.475x.**

The original historical simulator already accepts daily rates. The Monte Carlo takes a scalar benchmark. I extended it to take a common time series or a full rate-path matrix, with scalar/vector agreement tested.

I sampled return/rate blocks together, then permuted entire rate paths across the same return paths. That preserves the realised rate distribution and its within-path persistence while removing return/rate dependence. A constant rate equal to the sampled mean separates rate timing from simply assuming cheaper money.

| Financing assumption | Benchmark mean | Gamma-1.5 optimum | 5th-percentile CAGR at 1.475x |
|---|---:|---:|---:|
| Repository constant | 3.630% | 1.475x | 5.630% |
| Constant historical sampled mean | 3.387% | 1.525x | 5.756% |
| Joint historical return/rate blocks | 3.387% | 1.525x | 5.767% |
| Same rate paths, unpaired | 3.387% | 1.525x | 5.768% |

The increase is about **3.4% in leverage**, almost entirely associated with the lower mean benchmark. The paired-versus-unpaired timing difference at 1.475x is about −0.12 basis points/year in fifth-percentile CAGR and −0.18 basis points/year in certainty-equivalent return. It is economically negligible in this experiment and does not establish a reliable sign.

To avoid relying entirely on short blocks, I replayed complete historical episodes at 1.475x, using the repo's return reconstruction. In the GFC window (October 2007–April 2009), actual rates leave **$47,849** from $100,000 versus **$46,808** if the entry benchmark stays frozen. That is $1,041, or 2.22% more terminal equity; maximum drawdown improves from 62.48% to 61.88%. In the COVID window, actual cuts add only about **$96** versus freezing the entry rate. In 2022, rising rates instead cost about **$642** versus freezing its low entry rate.

Your intuition is directionally right for GFC/COVID. It is not a sufficient reason to increase leverage materially. Rates can rise during inflationary drawdowns. The 21-day paired bootstrap still fails to preserve multi-year monetary-policy regimes and lagged responses; this is a partial quantification, not a calibrated forward rate model. A proper joint regime model remains desirable.

There is a much larger concrete financing issue: [IBKR Australia's published schedule](https://www.interactivebrokers.com.au/en/trading/margin-rates-au.php) adds **2% to non-AUD borrowing** for retail clients and specified natural-person standard facilities. That makes the first USD tier 7.13% at the repo's benchmark, rather than 5.13%, and moves this utility optimum to 1.10x. I have not assumed that account category applies to you. Also, [IBKR describes its reference benchmark as a combination of market/reference rates](https://brokerage.ibkr.com/en/pricing/reference-benchmark-rates-int.php), so “Fed Funds equals the exact IBKR benchmark” is an approximation.

**3. Variable factor loadings did not move the central utility answer by more than 10% in my direct tests; parameter uncertainty did.**

The rolling 250-day estimates reproduce the reported ranges: market 0.026–1.199, momentum −0.014–0.612. Treating the extreme coefficients as known permanent regimes would confound estimation noise with genuine changes in exposure. Equally, adding coefficient randomness on top of the full fixed-model residual would double-count part of the instability.

I therefore estimated each day's coefficients using only the preceding 250 observations, calculated the subsequent residual against that model, and sampled coefficient/residual pairs together. I substituted these for the fixed-model residual construction on pre-live dates and held the synthetic mean return exactly unchanged, isolating risk/exposure changes. With 21-day and 252-day coefficient regimes, the gamma-1.5 grid optima were **1.4x and 1.5x**, versus 1.5x in the baseline. Fitting the fixed model to the first versus second half of SPMO's overlap yielded 1.5x and 1.4x; their drawdown-constrained grid limits differed more, 1.5x versus 1.3x.

This is evidence of some sensitivity, not evidence that the extreme rolling range automatically invalidates the point estimate. These models still do not establish how future SPMO holdings, beta and residual tails co-move with market stress. In particular, they do not use an observed century of changing SPMO exposures.

The more consequential omission is **uncertainty about the true expected return**. The repo's Monte Carlo repeatedly samples around one estimated mean, so uncertainty narrows with horizon as if the mean were known. I instead added an annual drift perturbation drawn once for each investor's entire path, with mean zero and standard deviation 1%, 2% or 3%. This preserves the central expected return while allowing it to be persistently wrong. Annual arithmetic-return sums in the reconstructed dataset imply a descriptive standard error of about **1.94 percentage points** across 99 complete calendar years; 2 points is therefore a relevant sensitivity size, not a posterior calibrated to SPMO.

With 2 points the fine-grid optimum falls **1.475x → 1.30x**; with 3 points, **1.125x**. The median at 1.475x barely changes, but its fifth-percentile 40-year CAGR falls from **5.63% to 4.07% / 2.41%**. That is the failure mode a fixed-mean bootstrap hides. I did not re-derive the previously audited residual-demeaning, alpha-significance or ordinary block-length checks.

**4. Use the actual index methodology as a proxy, and stop calling the two reconstructions independent confirmation.**

The two return reconstructions correlate **0.873** across their common full history. They share US equities, momentum exposures and the same live SPMO segment. They are different constructions, not independent evidence about the unknown future return premium. The 89.64% pre-live share is reproduced.

S&P publishes the index's first value date as September 1994 and launch as November 2014. Its pre-launch history is backtested. The index is a better methodological proxy, but still carries hindsight risk. [S&P index methodology](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-momentum-indices.pdf?force_download=true).

The published index study reports a technology-bubble drawdown of **58.61%**, compared with **49.70%** and **41.16%** for the repo's factor and measured reconstructions over its 2000–02 window. Its published GFC drawdown is **46.70%**; the repo's comparable episode figures are **46.34%** and **49.95%**. Different episode definitions and observation frequencies mean these are diagnostics, not exact like-for-like validation. [S&P's published study, exhibits 2 and its performance disclosure](https://www.spglobal.com/spdji/en/documents/education/education-momentum-a-practioners-guide.pdf).

I could retrieve the published statistics but **not the full daily total-return index series**: the direct page request returned HTTP 403, and the public Yahoo index symbol did not expose history. I have not invented an index-based leverage optimum from drawdown summaries. The next implementation should use licensed/publicly accessible daily index total returns where available, subtract ETF expenses before inception, splice live ETF data, and reserve the older French histories as stress scenarios rather than pretend they identify a century of SPMO.

The measured French portfolio also omits fund implementation expenses. Charging a 13 bp/year expense scenario on its pre-live portion did not move the coarse 1.5x utility optimum. It still removes the justification for calling the unadjusted proxy automatically conservative.

**5. Withholding matters, but 15–30 bp/year alone does not meet your 10% threshold.**

At a 1% distribution yield, 15–30% withholding implies 15–30 bp of unlevered asset-return drag. I applied that drag to each day's position return, so it scales with exposure rather than merely account equity. The fitted utility optimum moves **1.475x → 1.450x / 1.425x**, decreases of 1.7% / 3.4%. At 1.475x, fifth-percentile 40-year CAGR falls from **5.63% to 5.39% / 5.16%**.

Those runs are yield/tax sensitivities, not a reconstruction of actual distribution dates and taxes. US withholding is generally 30% or a lower qualifying treaty rate; treaty rates are not universally 15%. Residence-country tax credits may offset some withholding, while domestic distribution or realised-gain taxes may add other costs. Treating withholding as necessarily a permanent extra 15–30 bp in every non-US account is too broad. [IRS withholding guidance](https://www.irs.gov/individuals/international-taxpayers/withholding-on-specific-income).

**6. A band can be selected with an explicit economic criterion; its true optimum is not identified by these histories.**

The repo first optimises a monthly-rebalanced target, then chooses a band at that target. This is not joint optimisation of the target and band. A joint sweep at 10% bandwidth gives about **1.525x**, a small change from 1.475x, below your materiality threshold.

The claim that all narrow bands are indistinguishable on every return measure is too strong. On the constructed history at 1.475x, a 10% band loses about **2.39 bp/year of certainty-equivalent return** relative to 6%; a paired simulation-only 95% interval is approximately −3.55 to −1.23 bp. The 6% benchmark was selected using these same paths, so this interval is not an out-of-sample or selection-adjusted confidence statement. On the measured history, 2% is best and 10% loses **4.23 bp/year**.

Here is a rule that actually chooses a width: **take the widest tested band whose annual certainty-equivalent loss is at most 5 bp relative to each history's best band, then minimise trading frequency.** At fixed 1.475x this selects **10%** on the tested grid: 12.5% misses the measured-history tolerance, at 5.07 bp. The 10% band trades about **28–30 times in 40 years**, versus 524–536 at 2%. The 5 bp tolerance is an explicit preference, not a statistical discovery. Small changes in that tolerance can choose another band. Near zero borrowing there is no margin band to optimise.

**7. Maintenance margin is too simple; the quantified central effect is smaller than the implementation risk.**

I tested a causal stress rule: when the unlevered asset's previous-close drawdown exceeds 20%, maintenance increases from 25% to the scenario level; it reverts when that drawdown recovers. The audit engine liquidates when required and caps subsequent target rebalancing at 99% of the maximum permitted leverage. This is an illustrative house-rule shock, not an estimate of IBKR's future SPMO requirement. All these runs retain the repo's 10 bp liquidation slippage and close-based default; I did not re-audit the intraday model.

| Stress maintenance | Paths with a liquidation at target 1.475x | P(drawdown worse than 70%) | Median CAGR |
|---|---:|---:|---:|
| 25% | 0% observed | 35.0% | 13.86% |
| 30% | 0% observed | 35.0% | 13.86% |
| 40% | 0% observed | 35.0% | 13.86% |
| 50% | 11.3% | 35.0% | 13.86% |
| 75% | 100% | 24.5% | 13.59% |
| 100% | 100% | 8.9% | 13.16% |

Forced deleveraging can improve the eventual drawdown statistic by reducing future exposure; that is not evidence a surprise liquidation is harmless. At 75% maintenance, the fine-grid gamma-1.5 target remains 1.475x, but the strategy holds less exposure during stress. A permanently 75%-marginable asset cannot support that actual exposure: its legal leverage ceiling is 1/0.75 = 1.333x, regardless of the nominal target.

The original code contains no such rebalance cap. A two-day flat-return path with `Account(leverage=1.475, maintenance_margin=.75, rebalance="daily")` generates a liquidation each day, then restores leverage to 1.475x, leaving equity/position at 67.8%, below the required 75%. Both original simulators can agree on this invalid behaviour. This broker-compliance issue remains outside the small patch; the audit stress engine handles it explicitly.

The 25% maintenance minimum is also distinct from Reg T's usual **50% initial margin**. An ordinary cash-funded Reg T account cannot open the repo's 2.5x–3x exposures solely on a 25% maintenance assumption. [FINRA margin explanation](https://www.finra.org/investors/investing/investment-accounts/brokerage-accounts). IBKR can impose higher house requirements and increase them without advance notice. [IBKR margin disclosure](https://www.interactivebrokers.co.uk/Universal/Application?action=formSampleView&formdb=1005&preferredFormat=html). The account's actual instrument and concentration requirements must determine the admissible strategy.

**Additional code/documentation failures.**

| Location at reviewed commit | Disagreement or defect | Effect |
|---|---|---|
| `metrics.py:92–96` | A return is recorded only when both starting and ending equity are positive. A wipeout day's loss is skipped. | `[−40%, 0%]` at 3x gives scalar CAGR 0%, max drawdown 0%, while vector gives −100%, −100%. Patched and regression-tested. No demonstrated change to the default bootstrap optimum, which already uses the correct vector metrics. |
| `optimise_target.py:144–157` | Chooses largest feasible leverage while labelling it maximum feasible median growth. | 2.8x versus 2.05x in the loose-constraint failing case. Patched. |
| `README.md:16, 129–132` | 1.112x is labelled a ten-year answer, but appears in the 40-year gamma-2 table. | A fixed-gamma test gives about 1.40x at ten years versus 1.475x at forty, not the headline jump. |
| `margin.py:8`, README financing discussion | Claims regional tier spreads are stable/mostly irrelevant. | Applicable Australian USD surcharge is 200 bp and materially changes the answer. |
| README financing stress table | Shows 5th-percentile CAGR near +6.1% at 1x and +5.2% at 1.5x/high rates. | The freshly run ten-year script produces **+1.68% at 1x and −2.94% at 1.5x/high rates**. At 3x/high rates: −22.58%, not −4.2%. The table is not the current script's result; no reproducible horizon/run is attached to it. |
| `position_calculator.py` default console output | Still says the conclusion is 1.0x with half Kelly 1.075x. | Contradicts the README's current 1.475x recommendation. |
| README limitations | Says commissions and bid/ask costs are absent and liquidation slippage is the only transaction cost. | `rebalance_cost=.0002` already charges traded notional. Live ETF adjusted returns also include fund-level expense/tracking outcomes. |
| `backtest.py:159–160`, funding-strategy labels | “Fixed dollar loan” accrues interest into the debit. | It is a loan that is not replenished, not a fixed-dollar principal balance. Funding experiments are also not exactly scale-free because tiers and the $10k cash-interest threshold are in dollars. |
| `optimal.py`/optimiser grids | Lower-bound 1.0x optima are described without stating the restricted universe. | With original cash-credit conventions, a 0.5x allocation has a ten-year p05 CAGR of 2.44%, versus 1.24% at 1x on the same 3,000 paths. This only establishes a boundary restriction, not a validated cash-allocation optimum. |
| Both account simulators at leverage zero | Treat `position <= 0` as account ruin, even with all equity held as cash. | A zero-stock, positive-cash account is falsely wiped out. Remains to fix if the search is extended to cash. Cash-credit NAV proration below $100k is also omitted. |
| `_refine` in optimiser / `optimal.py` | Equal-spacing parabolic formula can be used on nonuniform grids. | Band grid and some leverage grids are nonuniform. No demonstrated >10% effect here; reported third decimals should not be trusted. |

“No bear market” is also literally too strong for SPMO's live record: it includes the COVID crash and 2022. The valid concern is that it excludes the dot-com bust and GFC and represents a short, selected window.

I disagree with averaging two utility optima and two drawdown-budget limits and presenting the mean as an optimal target. A risk aversion of 1.5 and a one-in-three tolerance for a 70% drawdown are user preferences. Their numerical agreement is not independent evidence that those preferences, or the assumed return distribution, are correct.

**The three highest-value missing pieces, ranked by demonstrated/plausible movement.**

1. **A fund universe and persistent uncertainty model.** Validate live and closed fund distributions, estimate selection/shrinkage without dropping only the inconvenient parts of fund performance, propagate expected-return and exposure uncertainty into investor utility. Observed differences range from about 1.5x to 1.0x across funds; a 2–3 point drift uncertainty lowers the SPMO target by 12–24% by itself. This matters more than optimising a band.
2. **The actual account's borrowing contract and after-tax economics.** Broker entity/facility, admissible leverage, currency, concentrated-position requirements, domestic taxes and usable deductions. The confirmed Australian USD surcharge alone is worth roughly 25% of the fitted leverage. Withholding alone is smaller. A favourable tax deduction must not be included while excluding the taxes it exists to offset.
3. **Daily S&P index returns and a joint stress model.** Compare its actual methodology through the technology bust with the French proxies, then model rate changes and requirement increases jointly. The proxy drawdown discrepancies are material, but I cannot honestly attach a leverage-point estimate until the daily index series is obtained. The modest 30–50% maintenance and historical-rate-timing tests here do not independently justify a large reduction or increase in the 1.5x utility optimum.

**Deliverables and limits.** `audit.patch` contains the three scoped changes and their new tests; it is not a complete production trading engine. The evidence bundle includes source scripts, frozen inputs, downloaded peer data, all experiment tables, original/fixed test logs and all original script logs. The original results and cached data are retained separately. Fine-grid summary columns for objectives other than gamma 1.5 can hit their intentionally narrow search boundary; use the broad-grid tables for full-Kelly or median-growth optima. There is no claimed closed-fund survivorship correction or full daily S&P-index backtest in this review.

Several tested concerns barely move the answer, and rate cuts sometimes help. **The numerical precision and the long-horizon justification still outrun what the model has established.**
