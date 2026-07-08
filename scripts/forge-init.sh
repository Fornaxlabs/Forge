#!/usr/bin/env bash
# FORGE per-project bootstrap. Idempotent: never overwrites an existing file.
# Self-locating — works regardless of how it is invoked (finds the plugin root
# relative to this script, so it does not depend on $CLAUDE_PLUGIN_ROOT).
set -euo pipefail

PLUGIN="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$PWD}"
cd "$TARGET"

copied=""
skipped=""

stamp() { # <src-relative-to-plugin> <dest-relative-to-target>
  if [ -e "$2" ]; then
    skipped="$skipped $2"
  else
    mkdir -p "$(dirname "$2")"
    cp "$PLUGIN/$1" "$2"
    copied="$copied $2"
  fi
}

stamp templates/project-CLAUDE.md   CLAUDE.md
stamp templates/pre-commit-config.yaml .pre-commit-config.yaml
stamp templates/.gitleaks.toml      .gitleaks.toml
stamp templates/ci-pipeline.yml     .github/workflows/forge-ci.yml

# HARD pre-push secret gate (git hook) — installed only in a git repo.
if [ -d .git ]; then
  if [ -e .git/hooks/pre-push ]; then
    skipped="$skipped .git/hooks/pre-push"
  else
    cp "$PLUGIN/templates/pre-push" .git/hooks/pre-push
    chmod +x .git/hooks/pre-push
    copied="$copied .git/hooks/pre-push"
  fi
fi

# Shared memory DB (created in ./.forge/memory.db by the CLI default).
if python3 "$PLUGIN/memory/forge_memory.py" init >/dev/null 2>&1; then
  mem="initialized .forge/memory.db"
else
  mem="SKIPPED (python3 not found?)"
fi

# gitignore the runtime dirs (append only if missing).
# Ensure a trailing newline first, else appends concatenate onto the last line
# (e.g. "dist" + ".forge/" -> "dist.forge/").
if [ -f .gitignore ] && [ -n "$(tail -c1 .gitignore 2>/dev/null)" ]; then
  echo >> .gitignore
fi
for pat in ".forge/" "traces/runs/" "audits/"; do
  grep -qxF "$pat" .gitignore 2>/dev/null || echo "$pat" >> .gitignore
done

echo "FORGE initialized in: $TARGET"
echo "  stamped:  ${copied:-(none - all already present)}"
echo "  skipped:  ${skipped:-(none)}"
echo "  memory:   $mem"
echo ""
echo "Next steps (not automated — they need your call):"
echo "  1. pre-commit install"
echo "  2. create a PRIVATE GitHub repo if none:  gh repo create <Name> --private --source . --push"
echo "  3. fill the [placeholders] in CLAUDE.md (context + commands)"
echo "  4. run /temper for a baseline scorecard"
