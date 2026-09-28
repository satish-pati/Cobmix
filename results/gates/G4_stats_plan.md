# G4 — Statistical Analysis Plan

**Status:** LOCKED — must be filled in BEFORE any model run.

## Repeated Runs
- Each condition (C0–C5) is run **5 times** with random seeds: 42, 123, 456, 789, 1337.
- All 5 seeds are used for every task and every condition.

## Central Tendency
- Report **mean ± std** over the 5 seeds for each metric in every table.

## Comparison Tests
- **Test:** Paired Wilcoxon signed-rank test (non-parametric; does not assume normality).
- **Pairs:** C5 vs C0, and C5 vs C1, for each task.
- **Alpha:** 0.05 before correction.

## Effect Size
- **Metric:** Cliff's delta (d).
- **Interpretation thresholds:** |d| < 0.147 = negligible, < 0.33 = small, < 0.474 = medium, >= 0.474 = large.
- Report alongside every p-value.

## Multiple Comparison Correction
- **Method:** Bonferroni correction.
- **Number of tests:** 3 tasks × 2 comparisons (vs C0, vs C1) = 6 tests per metric.
- **Corrected alpha:** 0.05 / 6 = 0.0083.

## Ablation Decision Rule
A COBOL-specific view earns its place if:
  delta_F1 (when view removed) >= 2 × std(5 repeated runs of C5)
on at least one of the three tasks.

If no view meets this threshold, report honestly: the COBOL-specific views did not
contribute beyond the standard three, and simplify the representation accordingly.

## Per-Project Reporting
- Report per-project F1 alongside pooled F1 for all three tasks.
- Do NOT claim pooled numbers generalise beyond the corpus examined.

**Date locked:** ___________
**Locked by:** ___________
