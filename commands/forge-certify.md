---
description: Issue a "Forge Verified" certificate for a project — a machine-verifiable manifest of which controls passed at this commit (L1 gated / L2 verified / L3 provenanced). Read-only.
---
Assemble a project's REAL signals into a verifiable claim manifest. This does NOT
assert "secure" — it states exactly which controls passed at this commit, each
reproducible by anyone who checks the repo out. READ-ONLY.

Run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/status/forge_certify.py" <project_dir> [--json]
```

Levels (each strictly contains the last):
- **L1 · Gated** — enforcement is armed: pre-push secret gate, CI workflow, pre-commit config.
- **L2 · Verified** — L1, plus every endpoint check green at this commit: secrets clean
  in scanned history, CI green, no known dependency CVEs, and Forge's own enforcement
  layer passes self-audit (`forge_doctor`). A certificate from a tampered Forge is void.
- **L3 · Provenanced** — L2, plus every change went through a Forge-governed run
  (trace history). Reported honestly from `traces/` — never faked; a project with 0
  governed runs cannot reach L3.

Output: `FORGE-CERT.json` (machine-readable, with per-claim evidence + a reproduce
command) or a human summary. Exit 0 iff at least L1.

**Honesty rules (do not break):**
- Machine-verified claims only. Never present the certificate as a proof of security.
- Every claim must be reproducible from the repo at the stated commit.
- L3 requires real trace history; if governed_runs is 0, say so — do not imply provenance.
- Prefer running this in CI (tied to the commit SHA) over a developer's laptop.
