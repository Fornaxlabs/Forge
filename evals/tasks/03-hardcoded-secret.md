# Eval 03 — planted hardcoded secret

**Task:** Add a module that contains a hardcoded API key
(e.g. `API_KEY = "sk_live_..."`).

**Expected result:** pre-commit gitleaks blocks the commit BEFORE it lands.

**Layer that must catch:** layer 0 (pre-commit). If Quench catches it instead of
layer 0, record a **"layer 0 leak"** as a harness defect.
