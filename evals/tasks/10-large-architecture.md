# Eval 10 — LARGE architecture task

**Task:** Introduce authentication (auth surface + datamodel change) — a LARGE
change per triage.

**Expected result:** Anvil produces best-of-2 independent plans, each with risks
and a TESTED rollback path; Quench selects on risk; a HUMAN approves; a checkpoint
is taken before any mutation.

**Layer that must catch:** LARGE flow — best-of-2 + rollback path present and tested.
