#!/usr/bin/env python3
"""How precisely is the leverage target identified? Barely.

Every optimiser in this repo returns an argmax to as many decimals as you ask for.
This script asks the prior question: how much of the utility surface is signal, and
how much is Monte Carlo noise. It reports the standard error of expected utility at
each leverage and the set of leverages that cannot be distinguished from the
maximum.

The answer governs two decisions. It says how many digits of the target are real --
on 3,000 forty-year paths, not even the first decimal is firmly identified. And it
sets a floor on the rebalance band: holding a position to a tighter tolerance than
the target is identified to is pure transaction cost, so the band should be at
least as wide as the confidence set.

    python scripts/confidence_set.py
"""

import numpy as np, pandas as pd
from spmo_margin import data, bootstrap
BM, EQ, DRAG, BAND, CAP, YRS, NP = 0.0363, 50_000.0, 0.003, 0.10, 2.0, 40, 3000
G = 1.5
f, _ = data.long_only_momentum_history('SPMO')
paths = bootstrap.moving_block_paths(f.ret.to_numpy(), NP, YRS*252, seed=11)

grid = np.round(np.arange(1.00, 2.0001, 0.025), 6)
grid = grid[grid <= CAP]
rows = []
for L in grid:
    o = bootstrap.simulate_paths(paths, float(L), BM, equity0=EQ, annual_drag=DRAG,
                                 rebalance='band', band=BAND, max_leverage=CAP)
    W = o['terminal_equity']/EQ
    u = W**(1-G)/(1-G)                     # per-path utility
    rows.append({'leverage': float(L), 'u': u.mean(), 'se': u.std(ddof=1)/np.sqrt(len(u)),
                 'median_cagr': float(np.median(o['cagr'])),
                 'p05': float(np.percentile(o['cagr'], 5)),
                 'pdd': float((o['max_drawdown'] < -0.70).mean())})
t = pd.DataFrame(rows).set_index('leverage')

best = t.u.idxmax()
se = t.se.max()
# leverages whose utility is within 1 and 2 standard errors of the maximum
for k in (1, 2):
    band = t[t.u >= t.u.max() - k*se]
    print('within %d SE of the maximum: %.3fx to %.3fx  (%d of %d grid points)'
          % (k, band.index.min(), band.index.max(), len(band), len(t)))
print()
print('argmax on this grid            %.3fx' % best)
print('Monte Carlo SE on utility      %.2e   (utility range over 1.0-2.0x: %.2e)'
      % (se, t.u.max()-t.u.min()))
print('ratio of SE to the whole range %.1f%%' % (100*se/(t.u.max()-t.u.min())))
print()
print(t.round(5).to_string())
