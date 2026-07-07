---
description: Read-only compliance review of the current app against FORGE standards — score, prioritized gaps, consolidation plan. Never modifies.
---
Review the current project for FORGE compliance. READ-ONLY: report only, change nothing.

1. Gather deterministic signals: run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/forge-comply.sh"`
   and read its output (secrets in tree + recent history, deps/CVEs, lint volume +
   auto-fixable count, route/auth heuristic, gate-liveness, repo hygiene,
   tests/coverage, governance-doc sprawl). It honors .forgeignore and .gitleaks.toml.
2. As the reviewer, judge the codebase against standards/SECURITY.md,
   LLM-SECURITY.md, ENGINEERING.md. SKIP anything listed in .forge/waivers.md
   (accepted exceptions — do not re-nag).
3. Write COMPLIANCE.md:
   - a SCORE per standard (MUSTs met / total),
   - findings grouped and prioritized: QUICK WINS (auto-fixable, e.g. `ruff --fix`)
     vs ARCHITECTURAL (needs a triaged task),
   - a CONSOLIDATION PLAN for scattered/duplicate governance docs: propose which to
     merge into the constitution/standards and which to archive — PROPOSE, never delete,
   - a COULD-NOT-CHECK section (be honest about limits).
4. If a previous COMPLIANCE.md exists, diff against it and note improvement/regression.

Never edit code or delete files. Fixes go through /forge; accepted exceptions are
added to .forge/waivers.md with a written justification.
