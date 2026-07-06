# FORGE v4 — Fornax Orchestrated Review & Governance Engine

A governance harness delivered as a Claude Code plugin. It turns "just vibe-code
it" into a disciplined pipeline: **triage → plan → build → adversarial review →
loop discipline → shared memory → traces → evals**.

Foundations: Anthropic's CLAUDE.md/agentic-coding best practices, OWASP Top 10
(2025), OWASP ASVS 5.0, OWASP API Security Top 10, OWASP Top 10 for LLM
Applications, NIST SSDF (SP 800-218), Conventional Commits, RFC 9457.

## The pieces
- **Agents** — `smith` (build), `anvil` (plan), `quench` (adversarial review),
  `bellows` (tests), `ledger` (docs/commits). Least privilege per agent.
- **Commands** — `/forge` (pipeline), `/audit` (full security pass), `/temper`
  (run evals + scorecard), `/curate` (monthly hygiene), `/postmortem` (incident → rule).
- **Layer 0 (deterministic)** — a PreToolUse hook blocks catastrophic Bash;
  pre-commit runs gitleaks + ruff + mypy; CI runs lint/test/security/SBOM.
- **Shared memory** — `memory/forge_memory.py` (SQLite + FTS5), untrusted-data by rule.
- **Traces** — one JSONL per run: no evidence = didn't happen.
- **Evals** — 10 planted-fault tasks + a scorecard to catch harness regressions.

## Install into a target project
0. Start version control: `git init` and create a PRIVATE GitHub repo before real
   work — `gh repo create <name> --private --source . --push`. FORGE assumes a git
   remote exists (PRs, branch protection, CI all build on it).
1. Install the plugin and restart the session (agents load at startup).
   - Dev/local: launch Claude Code with `--plugin-dir /path/to/forge`.
   - Persistent: add `"forge": true` under `enabledPlugins` in `.claude/settings.json`
     (project) or your user settings, then restart.
2. Copy `templates/project-CLAUDE.md` → project root as `CLAUDE.md`; fill in the
   `[…]` placeholders (context, commands).
3. Copy `templates/pre-commit-config.yaml` → `.pre-commit-config.yaml`; run
   `pre-commit install`.
4. Add the CI template to your pipeline; enable branch protection on `main`
   (PR required, no force-push).
5. `python3 memory/forge_memory.py init` in the project; add `.forge/` and
   `traces/runs/` to `.gitignore`.
6. Baseline: run `/temper` and commit the first scorecard.

## Notes / deviations from the v4 spec
- Manifest lives at `.claude-plugin/plugin.json` (Claude Code requirement), not the
  repo root; `author` is an object.
- Pre-commit revs pinned to current stable: gitleaks v8.30.1, ruff v0.15.20,
  mypy v2.1.0.
- `commands/` are supported; Claude Code's newer convention is `skills/`. Kept as
  commands to match the spec.
