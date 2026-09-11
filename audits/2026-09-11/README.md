# Adversarial audit — 11 September 2026

Reviewed upstream commit `3b181bfab767f06a72805abd09cd521ed6a7d5da`.

- [Full review](adversarial-review.md): findings, quantified sensitivity tests, and limitations.
- [Assessment recorded before reading the original README](pre-readme-assessment.md).
- [Leverage sensitivity chart](leverage-sensitivity.png).
- [Experiment summary](experiment-summary.csv) and [peer comparison](peer-comparison.csv).
- [Reproducible evidence bundle](audit-evidence.zip): audit source, frozen inputs,
  experiment tables, original script logs, test logs, and reproduction instructions.
- [Scoped patch against the reviewed commit](audit.patch), already applied in the
  repository source.

The original repository passed 117 tests and all five original scripts completed.
The patched repository passes 175 tests. New tests retain the 1e-9 scalar/vector
agreement requirement and cover ruin and time-varying rate paths.

The patch fixes three scoped issues: wipeout-day performance measurement,
constrained median-growth optimisation, and support for jointly sampled financing
paths. The remaining findings are documented, not all fixed. In particular,
stress-dependent broker requirements in the audit engine are scenarios, not
calibrated IBKR rules; closed-fund distribution histories are not fully validated.

The fine-grid summary was designed to locate gamma-1.5 optima. Other objective
columns may hit that restricted grid's boundary; use the broad-grid tables in the
bundle for full-Kelly and median-growth comparisons. Original top-level result
tables remain historical study outputs; audit results are separately versioned here.
