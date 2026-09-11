# Operating rule chosen by the repository owner

**This is a decision record, not a validated finding.** The [README](../README.md)
is correct that this repository has not validated a live leverage target, and
nothing here changes that. What follows is the rule the owner has chosen to operate,
written down with the conditions it rests on so that it can be checked later against
what actually happens.

## The rule

```
target                 1.500x
rebalance band         (1.300x, 1.700x)
action on breach       trade back to 1.500x
```

## Where the numbers come from

**1.500x is an argmax, not a rounding.** On a 0.025 grid, maximising CRRA expected
utility at risk aversion 1.5 over 3,000 bootstrapped forty-year paths, the maximum
falls at 1.500x. A second objective — maximise median growth subject to
`P(max drawdown worse than -70%) <= 1/3` — gives 1.456x. The two bracket the chosen
figure.

**The band matches the confidence set of the target, which is the only principled
reason available.** `scripts/confidence_set.py` reports a Monte Carlo standard error
on expected utility of 8.3e-03 against a total utility range of 3.4e-02 across
1.0x–2.0x — the noise is **24% of the entire signal**. Consequently:

| | Leverages statistically indistinguishable from the maximum |
|---|---|
| within 1 standard error | **1.250x – 1.725x** (20 of 41 grid points) |
| within 2 standard errors | 1.175x – 1.825x (27 of 41) |

The chosen band (1.300x, 1.700x) sits just inside the one-standard-error set.
Trading to defend a target more precisely than the target is identified is pure
cost, so the band is deliberately not the utility argmax — that argmax moved from
5.9% to 2.0% purely on which reconstruction of history was used, and is noise.

**An earlier attempt to quote three decimals was withdrawn.** The data does not
support the third decimal, and does not firmly support the first.

## Conditions this rests on

| Assumption | Value |
|---|---|
| financing | IBKR Pro USD, benchmark 3.63% + 1.50% tier-1 = **5.13%** |
| broker entity surcharge | **none** — verify on a statement, not the website |
| interest tax shield | **zero** (owner does not deduct) |
| asset-level drag | 30bp/yr (expense ratio plus dividend withholding) |
| holding period | **40 years** |
| starting equity | USD 50,000 |
| opening/rebalance cap | 2.0x |
| maintenance margin | 25% assumed |
| contributions/withdrawals | none modelled |

## What it is expected to produce, and to cost

Forty years, 3,000 paths, on USD 50,000:

| | |
|---|---|
| median CAGR | 14.61% |
| 5th-percentile CAGR | +6.09% |
| median terminal equity | $11.7m |
| 5th-percentile terminal equity | $532k |
| paths ruined | 0.00% |
| **P(drawdown worse than −70%)** | **37%** |
| worst point held per dollar deposited, 5th pct | 0.36 |
| rebalances over the period | ~19 (about one every two years) |

The 37% is the number to look at. Roughly one chance in three of watching the
account fall more than 70% at some point. No return figure above survives an
investor who sells there.

## What would invalidate it

- **A broker-entity surcharge.** IBKR Australia adds 2% to non-AUD borrowing for
  retail clients and for non-retail natural persons on a Standard Margin Lending
  Facility. At 7.13% financing the target falls to roughly 1.2x. Read the actual
  rate off a statement.
- **Expected return being lower than estimated.** This is the binding uncertainty,
  not grid precision. A persistent 2pp shortfall moves the best tested leverage to
  1.75x on the log-growth objective and the CRRA target down correspondingly; 4pp
  moves it to 1.25x. The standard error on the mean return over a century of data
  is about 1.9pp, so both are ordinary outcomes.
- **Forward volatility running above its historical level.** Kelly scales with
  `1/sigma^2`. Long-only momentum volatility was 18.9% over the century and 23.5%
  in the 2020s; at the latter the target collapses toward 1.0x.
- **A shorter horizon.** At ten years the same objective gives a materially lower
  answer. The 40-year figure is not transferable to money that might be needed
  sooner — and "needed sooner" includes being frightened out at a bottom.
- **Momentum's factor premium not persisting.** Zeroing the fund's own alpha still
  credits about 2.1%/yr of momentum premium. Removing it takes full Kelly from
  2.15x to 1.66x.

## Unresolved

The [adversarial review](../audits/2026-09-11/adversarial-review.md) and
[live-use review](live-use-review.md) list what is still open. The two that bear
most directly on this rule: the pre-2015 history is 89.6% reconstruction rather
than SPMO, and its tech-bubble drawdown (41–50%) is shallower than the published
index's 58.61%; and fixed leverage beat annually refitted selection on all five
surviving momentum funds over 2019–2026, which is a reason to hold a fixed rule
rather than re-optimise, and also a reason to doubt that the fitting identifies
anything.
