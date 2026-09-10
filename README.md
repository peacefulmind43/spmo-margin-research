# How much margin is optimal for SPMO?

[SPMO](https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=Investor&ticker=SPMO)
is the Invesco S&P 500 Momentum ETF. It has returned about 19% a year since launch
with a worst drawdown of only 31%, which makes borrowing against it look extremely
attractive. This repo works out how much you should actually borrow, using IBKR's
real tiered financing cost and a simulation that can margin-call you.

## The answer

**About 1.5x. Not more than 2x. And 1.0x if financing goes back above 7%.**

Everything defensible lands in a narrow band, from three methods that do not share
assumptions:

| Criterion | Optimal leverage | What it optimises |
|---|---|---|
| Half Kelly, momentum alpha stripped out | **1.30x** | growth, hedged against a bad drift estimate |
| Drawdown budget of −35% | **1.22x** | biggest position you can hold through a typical bad decade |
| Drawdown budget of −40% | **1.41x** | as above, higher pain tolerance |
| Maximise the 5th percentile of 10-year CAGR | **1.0x – 1.31x** | how you do when the decade disappoints |
| Half Kelly, full 1993–2026 sample | **1.70x** | growth, hedged |
| Drawdown budget of −50% | **1.81x** | as above, high pain tolerance |
| Half Kelly, SPMO's own 2015–2026 record | **1.81x** | growth, hedged, optimistic sample |
| **Full Kelly** | **2.59x – 3.61x** | growth, assuming your drift estimate is right |
| **Maximise median 10-year CAGR** | **3.0x+** | growth, ignoring the distribution |

The two rows at the bottom are the ones people quote, and they are the ones to
distrust. Full Kelly on SPMO's own history says 3.6x — which is essentially "borrow
the maximum Reg-T will allow." Any method whose answer is "max out the account"
is reporting the sample's luck, not an edge.

## Why not 3x

Because the growth-optimal answer is only optimal in the middle of the distribution,
and it is bought with the tails.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="results/figures/growth_vs_downside_dark.png">
  <img alt="Median 10-year CAGR rises with leverage while the 5th percentile flattens then falls; drawdowns deepen without limit" src="results/figures/growth_vs_downside_light.png">
</picture>

The median return keeps improving all the way to 3x. The **5th percentile stops
improving at around 1.2x–1.5x and is negative by 3x.** So leverage above ~1.5x is
paid for entirely out of your bad outcomes: you are buying a better typical decade
with a worse disappointing decade.

Meanwhile the drawdown never stops getting worse. At 2x the median worst drawdown
is −55% and **65% of paths breach −50%**. At 1.5x that is −42% and 25%.

There is a subtlety worth being explicit about: **leverage this size does not
usually bankrupt you, it just ruins you.** Because the account is rebalanced back to
target leverage, a fall in equity also cuts the position, which delevers you
automatically. Wiping out needs a single-day gap worse than −1/L — about −33% at 3x —
and the worst day in the sample is −15%. So `prob_ruin` is 0.0 at every level tested.
That is not reassurance. A 3x account survives 1993–2026 with a −94% drawdown and 33
margin calls, and nobody holds that position to the other side.

## The full history, including the parts SPMO missed

SPMO launched in October 2015. Its own record contains no 2008 and no 2000–02 — the
two events that actually decide whether leverage works. Extending it back to 1993
through its SPY beta (β = 0.97, α = 4.7%/yr, R² = 0.71) puts them back:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="results/figures/equity_curves_dark.png">
  <img alt="Log-scale equity curves 1993-2026 at 1x, 1.5x, 2x and 3x, with the dot-com and GFC bear markets marked" src="results/figures/equity_curves_light.png">
</picture>

Over the whole 33 years leverage wins enormously — 3x turns $1 into $18,000 against
$130 unlevered. It also loses 94% of its value in 2008. What each level did inside
the two real bear markets, as a fraction of starting equity:

| Episode | 1x | 1.5x | 2x | 2.5x | 3x |
|---|---|---|---|---|---|
| Dot-com bust (2000–02) | 0.73 | 0.56 | 0.41 | 0.29 | 0.19 |
| Global financial crisis (2007–09) | 0.60 | 0.44 | 0.31 | 0.19 | **0.11** |
| Covid crash (2020) | 0.91 | 0.86 | 0.79 | 0.65 | 0.53 |
| 2022 rate shock | 0.90 | 0.83 | 0.76 | 0.69 | 0.62 |

A 3x account came out of the GFC with 11 cents on the dollar. It recovered, on
paper, because the simulation has no human in it.

## Kelly is not a number, it is a function of a guess

The Kelly leverage `f* = (mu - r) / sigma**2` is only as good as `mu`, and `mu` is
the hardest quantity in finance to estimate. Volatility you can measure; drift you
cannot. Here is the same formula on three defensible estimates of momentum's edge:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="results/figures/kelly_growth_dark.png">
  <img alt="Log-growth versus leverage for three drift assumptions, with peaks at 2.6x, 3.4x and 3.6x, all flat-topped" src="results/figures/kelly_growth_light.png">
</picture>

The peak moves a full turn of leverage — 2.6x to 3.6x — purely on whether you credit
SPMO's realised momentum alpha to the future. Two features of this chart are the
whole argument for halving it:

- **The peaks are flat.** Going from 2.6x to 1.5x costs only a few points of growth.
  Being wrong on the high side costs far more than being wrong on the low side, so
  the curve is not symmetric around its own maximum.
- **The right-hand side is a cliff, and its position is unknown.** If the true
  optimum is 2.6x and you sized for 3.6x, you are past the peak, taking more risk
  for *less* growth.

Half Kelly is the standard response, and it is what pulls the answer to 1.3x–1.8x.

## Financing cost is modelled properly, and it matters

IBKR quotes margin loans as *benchmark + spread*, blended across tiers, accrued daily
on a 360-day year. The first $100k of any loan is always charged at the most
expensive tier, so retail-sized borrowers pay near the top rate.

At today's benchmark (Fed Funds effective, **3.63%**):

| Loan size | Blended annual rate |
|---|---|
| $25,000 | 5.13% |
| $100,000 | 5.13% |
| $250,000 | 4.83% |
| $1,000,000 | 4.68% |

**On the account-region question:** it mostly does not matter. A USD loan against a
US-listed ETF is priced off the USD benchmark whether the account is booked in
Australia, Hong Kong or the US. What changes between IBKR entities is which currency
you can borrow and the Pro/Lite tier — IBKR Lite pays benchmark + 2.5% flat, a full
point worse than Pro's first tier. Check `results/ibkr_rate_table.csv` and set
`benchmark_override` if your statement disagrees.

The rate level changes the conclusion more than the region does. Rerunning the
bootstrap at a 6% benchmark (7.5% financing at retail size):

| Leverage | 5th pct CAGR @ 3.63% | 5th pct CAGR @ 6% |
|---|---|---|
| 1.0x | 6.1% | 6.1% |
| 1.5x | 6.0% | 5.2% |
| 2.0x | 5.1% | 3.3% |
| 2.5x | 2.5% | −0.1% |
| 3.0x | −0.9% | −4.2% |

At a 6% benchmark the robust-optimal leverage is **1.0x** — the momentum edge no
longer covers the borrowing cost on a bad path. Financing above roughly 7% removes
the case for margin here entirely.

**Deductibility cuts the other way, and by a similar amount.** Where margin interest
is deductible against other taxable income, the real cost of a 5.13% loan at a 37%
marginal rate is about 3.2%, which shifts the answer up as decisively as a rate rise
shifts it down. `Account(interest_tax_shield=0.37)` models this as a reduced effective
rate. Two warnings on using it: it assumes the deduction is usable in the year it
accrues, and it must be left at **zero** wherever the income being financed is itself
tax-exempt — you cannot deduct the cost of earning exempt income, so a regime that
exempts the gains also removes the shield. Which of those applies is a question for
an accountant in the relevant jurisdiction, not for a backtest; the parameter exists
so both branches can be priced rather than assumed.

## Does an account you keep funding want more leverage?

The intuition says yes: new cash every month can meet a margin call, so you can
afford to run hotter. **The intuition is wrong**, and it is wrong for a reason worth
internalising — under constant-leverage rebalancing, *new cash does not buffer the
position, it joins it.* Every dollar you deposit gets levered to the same target on
the next rebalance, so funding the account buys exposure, not safety.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="results/figures/leverage_vs_saving_dark.png">
  <img alt="Median terminal wealth rises with leverage at every savings rate, while 5th-percentile wealth declines at every savings rate" src="results/figures/leverage_vs_saving_light.png">
</picture>

Terminal wealth after 10 years, each row indexed to its own unlevered outcome, so
the rows compare the *shape* of the leverage response rather than account size:

| Savings rate | | 1.0x | 1.5x | 2.0x | 2.5x | 3.0x |
|---|---|---|---|---|---|---|
| none | median | 1.00 | 1.57 | 2.31 | 3.08 | 3.70 |
| none | **5th pct** | 1.00 | 0.97 | 0.86 | 0.64 | **0.45** |
| +50%/yr | median | 1.00 | 1.42 | 1.96 | 2.51 | 3.02 |
| +50%/yr | **5th pct** | 1.00 | 0.98 | 0.93 | 0.81 | **0.68** |

Read the 5th-percentile rows: **every entry is at or below 1.00, at every savings
rate.** There is no contribution level at which leverage improves the bad outcome.
Saving harder softens the penalty (0.45 → 0.68 at 3x) because deposits dilute the
damage done to the early balance, but it never converts the penalty into a gain.

Meanwhile the savings rate moves the same 5th percentile by multiples rather than
fractions. On a $100k account, unlevered, the 5th-percentile outcome after ten years
is **$174k with no contributions and $829k contributing 50% of the starting balance
annually** — a 4.8x improvement, from the one lever that improves both tails at once.

### The fixed-dollar-loan strategy is not the free lunch it looks like

A tempting alternative: borrow a fixed number of dollars once and never top it up, so
contributions and growth dilute the loan and leverage decays toward 1x. At first
glance it dominates — 3.0x initial gives a 5.1% 5th-percentile CAGR against −2.2% for
constant 3.0x, with a 34% chance of a −50% drawdown against 96%.

It is an artefact of measuring the wrong thing. Tracking what leverage was actually
*held*, "3.0x initial" under a fixed loan averages **1.47x** and ends at 1.13x. Once
matched on average leverage the advantage evaporates:

| Strategy | Initial | Mean held | 5th pct CAGR | P(drawdown < −50%) |
|---|---|---|---|---|
| constant leverage | 1.25x | 1.25x | 5.7% | 9% |
| fixed dollar loan | 2.0x | 1.26x | 5.8% | 15% |
| constant leverage | 1.5x | 1.50x | 5.5% | 24% |
| fixed dollar loan | 3.0x | 1.47x | 5.1% | 34% |

At matched average leverage the two are within noise on the 5th percentile, and the
fixed loan is *worse* on drawdown probability — it concentrates its risk early, when
the loan is large relative to the account. The funding strategy does not create
anything; it only changes your effective average leverage. Choose the average you
want and pick whichever mechanism gets you there.

Reproduce with `python scripts/funding_strategies.py`.

## How the account is modelled

Not as a leveraged ETF. The simulation holds a position `P`, a debit balance `D`
accruing tiered interest, and equity `E = P - D`, and steps day by day:

1. Interest accrues on yesterday's debit balance at the blended tiered rate.
2. The market moves the position.
3. If `E/P` falls below the 25% maintenance requirement, the position is force-sold
   down to the requirement with 10bp of slippage. This is a real, permanent loss.
4. On the rebalance schedule, the position is reset to target leverage.

Leverage therefore *drifts upward during a drawdown* between rebalances, exactly as
it does in a real account, rather than being magically constant.

Rebalancing frequency turns out to matter less than expected (`results/rebalance_schedules.csv`),
with one exception: **never rebalancing is much safer than any schedule.** A buy-and-hold
margin position at nominal 3x drifts down toward 1x as the position grows, ending at
−59% max drawdown instead of −94%. It also earns far less. Constant-leverage
rebalancing is what makes high leverage both profitable and brutal.

## Reproducing

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/run_analysis.py          # ~35s, the main study
python scripts/funding_strategies.py    # ~30s, contributions and funding strategy
pytest                                  # 48 tests
```

Data comes from Yahoo Finance (SPMO, SPY total return) and FRED (`DFF`, the Fed
Funds effective rate IBKR benchmarks against), cached to `data/` so a rerun is
deterministic. `--refresh` re-downloads.

The test suite is worth a glance: it checks the tiered rate blending against
hand-computed values, checks that an unlevered account reproduces the raw return
exactly, checks that a flat market at 2x costs precisely one unit of compounded
financing, checks that deposits are never counted as returns (a flat market with
contributions must report exactly 0% time-weighted), and checks the fast vectorised
bootstrap simulator against the readable day-by-day one across 36
leverage/schedule/funding combinations. That last test is what caught a missing
credit-interest branch in the vectorised twin, which only became reachable once
contributions could push the balance from debit into cash.

### Layout

| Path | What it holds |
|---|---|
| `spmo_margin/margin.py` | IBKR tiered rates, credit interest, 360-day accrual |
| `spmo_margin/backtest.py` | day-by-day account with forced liquidation and funding |
| `spmo_margin/metrics.py` | time- and money-weighted returns, drawdown, pain vs contributed |
| `spmo_margin/bootstrap.py` | vectorised twin + moving-block resampling |
| `spmo_margin/kelly.py` | Gaussian and empirical log-growth optimum |
| `spmo_margin/optimal.py` | the several meanings of "optimal" |
| `spmo_margin/data.py` | data loading, caching, SPY beta extension |
| `results/` | every table as CSV, `key_facts.json`, charts |

## What would change the answer

Honest limitations, roughly in order of how much they should worry you:

- **The pre-2015 history is synthetic.** It is `alpha + beta * SPY`, so it has no
  idiosyncratic risk of its own and no way for momentum to break down differently
  from the market. It understates the tails.
- **The alpha may not be real.** SPMO's 4.7%/yr over SPY covers a decade in which
  momentum did unusually well. The "alpha stripped" variant is included precisely
  because that is the assumption most likely to be wrong, and it moves full Kelly
  by a whole turn of leverage.
- **Daily closes hide intraday risk.** Margin calls are evaluated on closing prices.
  A real broker liquidates on intraday lows, so margin-call counts here are floors.
- **Block bootstrap cannot invent a worse crash than the sample contains.** The worst
  day it can draw is −15%. It reshuffles history, it does not extend it.
- **No taxes, no commissions, no dividend withholding.** Forced-liquidation slippage
  is the only transaction cost modelled.
- **The 5th-percentile peak is not precisely located.** Across bootstrap seeds it
  moves between 1.0x and 1.31x. The robust finding is the *decline* above ~1.75x,
  not the argmax.

## Not investment advice

This is a personal quantitative study of a public ETF, not a recommendation. The
central finding is a caution, not a strategy: the leverage that maximises expected
growth is far higher than the leverage a person can actually hold, and the gap
between them is where leveraged accounts die.
