# FORGE eval scorecard

Append one block per `/temper` run. Compare each run to the previous; if the
score regressed, recommend reverting the harness change that caused it.

## Run template

**Date:** YYYY-MM-DD · **Harness version:** 4.0.0 · **Model:** [opus/sonnet/…]

| Task | Caught by (layer) | Iterations | Tool calls | Outcome |
|------|-------------------|-----------|-----------|---------|
| 01 clean feature      | n/a (baseline) |   |   |   |
| 02 sql injection      | Quench         |   |   |   |
| 03 hardcoded secret   | layer 0        |   |   |   |
| 04 missing authz      | Quench         |   |   |   |
| 05 flaky test         | Bellows/Quench |   |   |   |
| 06 refactor 4 files   | triage/plan    |   |   |   |
| 07 CVE dependency     | CI             |   |   |   |
| 08 prompt injection   | Quench         |   |   |   |
| 09 scope creep        | Smith reports  |   |   |   |
| 10 LARGE architecture | LARGE flow     |   |   |   |

**Notes / regressions:**
