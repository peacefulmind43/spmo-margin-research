# Assessment recorded before reading README.md

Commit: 3b181bfab767f06a72805abd09cd521ed6a7d5da.

I inspected the source code and tests, but have not opened README.md. Some source comments contain past conclusions (including a stale 1.0x conclusion in position_calculator.py), so this is not a fully blinded assessment.

My provisional view is that the repo cannot identify a personalised optimum. It estimates a leverage choice conditional on a stationary historical return distribution, a utility function, and a financing model. Zeroing the fund intercept does not correct ticker selection, and measured Big HiPRIOR history is a different portfolio with omitted implementation expenses. Long horizons do not make uncertain expected returns known.

I would not yet authorise borrowing on this evidence: provisional operational number 1.0x (zero margin), pending the experiments. This is a decision under model uncertainty, not a claim that the model's fitted expected-utility maximum equals 1.0x. Horizon, investor utility, taxation, account currency and broker entity have been requested from the user.

Concrete suspected defects to reproduce: scalar metrics skip the loss on the day equity goes to zero; the constrained optimiser chooses the highest feasible leverage rather than maximising its stated median-growth objective; target and band are optimised in different strategy families and not jointly; the leverage grid excludes cash allocations; the 250-day coefficient range is never propagated; a post-liquidation rebalance can re-open an infeasible exposure when requirements rise.

Planned comparisons: identical ticker-specific factor construction on peers; independent residual vs coefficient-regime reconstructions; paired historical return/rate blocks vs rate permutation at the same rate distribution; withholding/expense drags; static and stress-dependent maintenance; joint target/band utility and uncertainty.
