# FORGE v4 — Fornax Orchestrated Review & Governance Engine

A governance harness delivered as a Claude Code plugin. It turns "just vibe-code
it" into a disciplined pipeline: **triage → plan → build → adversarial review →
loop discipline → shared memory → traces → evals**.

Foundations: Anthropic's CLAUDE.md/agentic-coding best practices, OWASP Top 10
(2025), OWASP ASVS 5.0, OWASP API Security Top 10, OWASP Top 10 for LLM
Applications, NIST SSDF (SP 800-218), Conventional Commits, RFC 9457.

## Status & honest scope (read this first)

**Early tool. Tested, not battle-proven.** Forge works and has real tests, but it
has NOT been proven in production or by a second user. Use it with that in mind.

**What it is:** a hard floor that blocks disasters (committed secrets, destructive
commands, failing lint/test/CVE gates) + adversarial review against *your*
standards + an eval loop that turns each escaped bug into a regression test. It
makes practices you already believe in impossible to skip.

**What it is NOT:** it does not design your app, pick your stack, plan for you, or
turn a non-expert into an engineer. The command-deny guard is a *footgun-catcher,
not a security boundary* against a determined adversary — a denylist can't be
complete.

**Who it's for:** capable builders who want their own discipline enforced.
Python/FastAPI-flavored today. Not a hand-holder for beginners.

## The pieces
- **Agent** — one `reviewer` that wears three hats (plan / build / adversarial
  review) and can veto. Escalate to a fresh, independent reviewer for high-risk
  self-authored diffs. Least privilege by design.
- **Commands** — `/forge` (pipeline), `/forge-init` (bootstrap a project),
  `/forge-comply` (read-only compliance audit of an existing app), `/temper`
  (run evals + scorecard), `/curate` (monthly hygiene), `/postmortem` (incident → rule).
- **Pre-push gate (HARD)** — a git `pre-push` hook (installed by `/forge-init`)
  blocks any push that would leak a secret. Enforced by git, not by a soft
  CLAUDE.md rule — works even outside Claude Code.
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
   workflow, `.forge/memory.db`, the `pre-push` gate, and sets
   `permissions.defaultMode=plan` in `.claude/settings.json` (plan-mode-first,
   enforced) — all idempotent, never overwriting an existing file.
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
