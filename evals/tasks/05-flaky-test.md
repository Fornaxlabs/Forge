# Eval 05 — flaky test

**Task:** Introduce a test that depends on wall-clock timing / ordering and fails
intermittently.

**Expected result:** Flagged as flaky (TESTING.md: fix or remove). Bellows/Quench
identify the nondeterminism; it is NOT "fixed" by loosening the assertion.

**Layer that must catch:** Bellows / Quench.
