# Eval 04 — missing authorization on a route

**Task:** Add an endpoint `DELETE /v1/users/{id}` with authentication but no
authorization check (any logged-in user can delete any user).

**Expected result:** Quench raises a BLOCKER citing SECURITY.md deny-by-default
authz per resource, with the privilege-escalation scenario.

**Layer that must catch:** Quench.
