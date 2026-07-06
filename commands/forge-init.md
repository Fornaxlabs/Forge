---
description: Bootstrap FORGE into the current project — stamp the constitution, gates and memory (idempotent, never overwrites).
---
Bootstrap FORGE into the current project.

1. Run: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/forge-init.sh"`
   It stamps (only if absent): CLAUDE.md, .pre-commit-config.yaml, .gitleaks.toml,
   .github/workflows/forge-ci.yml; initializes .forge/memory.db; and gitignores
   the runtime dirs. It never overwrites an existing file.
2. Report exactly what was stamped vs skipped (echo the script output).
3. If CLAUDE.md already existed (skipped), do NOT replace it — offer to merge
   FORGE's constitution into the existing one instead.
4. Remind the user of the manual follow-ups the script printed: `pre-commit install`,
   create a PRIVATE GitHub repo if none exists, fill the CLAUDE.md placeholders,
   then run /temper for a baseline.
