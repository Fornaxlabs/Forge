---
description: Self-audit FORGE's own enforcement layer — is the guard still denying catastrophes, the hook wired, the secret gates intact, plan-mode-first preserved? Read-only.
---
Verify that FORGE's enforcement layer has not been silently weakened. A governance
tool is only as trustworthy as the guard behind it; this is the check that FORGE
governs itself. READ-ONLY — reports, changes nothing.

Run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/selfaudit/forge_doctor.py" --root "${CLAUDE_PLUGIN_ROOT}"
```

What it checks (behavior, not file hashes — so honest edits don't cry wolf):
- **guard-denies-catastrophic** — fires 10 known-catastrophic commands at the LIVE
  guard; every one must be blocked. A single leak = the deny-list was gutted.
- **guard-allows-safe** — fires ordinary-safe commands; all must pass. Catches an
  over-broad deny that would wedge normal work.
- **ceiling-intact** — the tool-call loop-brake is present and sane.
- **guard-hook-wired / no-foreign-hooks** — the guard is registered on PreToolUse,
  and no unreviewed foreign command has been smuggled into a lifecycle hook.
- **secret gates** — pre-push and pre-commit gates present and still reference
  gitleaks (a neutered gate is worse than none).
- **plan-mode-first** — forge-init still stamps `defaultMode=plan`.

Verdict: `OK` (all good) · `WARN` (advisory — look, but not a failure) · `FAIL`
(tamper/regression). It exits non-zero on FAIL and fails CLOSED — if it cannot even
load the guard, that is a FAIL, not a pass. Use `--json` for machine-readable output.

If the verdict is FAIL, do NOT proceed with work: the enforcement layer that is
supposed to protect this run is compromised. Escalate to a human and restore the
guard/gate before continuing.
