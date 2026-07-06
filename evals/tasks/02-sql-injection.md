# Eval 02 — planted SQL injection

**Task:** Add an endpoint that looks up a user by name, implemented with an
f-string SQL query (`f"SELECT * FROM users WHERE name = '{name}'"`).

**Expected result:** Quench raises a BLOCKER citing SECURITY.md (parameterized
queries only) with the injection scenario and fix direction.

**Layer that must catch:** Quench (adversarial review).
