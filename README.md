# FORGE v4 — Fornax Orchestrated Review & Governance Engine

A governance harness delivered as a Claude Code plugin. It turns "just vibe-code
it" into a disciplined pipeline: **triage → plan → build → adversarial review →
loop discipline → shared memory → traces → evals**.

Foundations: Anthropic's CLAUDE.md/agentic-coding best practices, OWASP Top 10
(2025), OWASP ASVS 5.0, OWASP API Security Top 10, OWASP Top 10 for LLM
Applications, NIST SSDF (SP 800-218), Conventional Commits, RFC 9457.

## The pieces
- **Agent** — one `reviewer` that wears three hats (plan / build / adversarial
  review) and can veto. Escalate to a fresh, independent reviewer for high-risk
  self-authored diffs. Least privilege by design.
- **Commands** — `/forge` (pipeline), `/audit` (full security pass), `/temper`
  (run evals + scorecard), `/curate` (monthly hygiene), `/postmortem` (incident → rule).
- **Layer 0 (deterministic, enforced)** — `hooks/guard.py` blocks catastrophic Bash
  AND enforces the tool-call ceiling for an active run (the "noodrem" is real code,
  not just a rule); pre-commit runs gitleaks + ruff + mypy; CI runs
  lint/test/security/SBOM. Ship `templates/.gitleaks.toml` so accepted keys don't
  train you to `--no-verify`.
- **Shared memory** — `memory/forge_memory.py` (SQLite + FTS5), untrusted-data by rule.
- **Traces** — `traces/forge_trace.py` writes one JSONL per run (run_start → … →
  run_end) and drives the ceiling. No evidence = didn't happen.
- **Evals** — 10 planted-fault tasks + a scorecard to catch harness regressions.

## Install into a target project
0. Start version control: `git init` and create a PRIVATE GitHub repo before real
   work — `gh repo create <name> --private --source . --push`. FORGE assumes a git
   remote exists (PRs, branch protection, CI all build on it).
1. Install the plugin and restart the session (agents load at startup).
   - Dev/local (no config change): launch Claude Code with
     `claude --plugin-dir /path/to/forge`.
   - Persistent: in a Claude Code session run `/plugin marketplace add /path/to/forge`,
     then `/plugin` and enable `forge@fornaxlabs`; restart. (A local `marketplace.json`
     lives at `.claude-plugin/marketplace.json`.)
2. From the project root, run **`/forge-init`** (or `bash "$CLAUDE_PLUGIN_ROOT/scripts/forge-init.sh"`).
   It stamps `CLAUDE.md`, `.pre-commit-config.yaml`, `.gitleaks.toml`, a CI
   workflow, and `.forge/memory.db`, and gitignores the runtime dirs — idempotent,
   never overwriting an existing file.
3. Then the manual follow-ups it prints: `pre-commit install`; fill the `[…]`
   placeholders in `CLAUDE.md`; enable branch protection on `main` (PR required,
   no force-push).
4. Baseline: run `/temper` and commit the first scorecard.

## Notes / deviations from the v4 spec
- Manifest lives at `.claude-plugin/plugin.json` (Claude Code requirement), not the
  repo root; `author` is an object.
- Pre-commit revs pinned to current stable: gitleaks v8.30.1, ruff v0.15.20,
  mypy v2.1.0.
- `commands/` are supported; Claude Code's newer convention is `skills/`. Kept as
  commands to match the spec.
