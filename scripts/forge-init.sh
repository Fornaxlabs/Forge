#!/usr/bin/env bash
# FORGE per-project bootstrap. Idempotent: never overwrites an existing file.
# Self-locating — works regardless of how it is invoked (finds the plugin root
# relative to this script, so it does not depend on $CLAUDE_PLUGIN_ROOT).
set -euo pipefail

PLUGIN="$(cd "$(dirname "$0")/.." && pwd)"

# --harness <name> selects which agent harness's guard config to stamp.
# Default: claude (behavior identical to before the flag existed).
HARNESS="claude"
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --harness)   HARNESS="${2:?forge-init: --harness needs a value}"; shift 2 ;;
    --harness=*) HARNESS="${1#--harness=}"; shift ;;
    *)           TARGET="$1"; shift ;;
  esac
done
TARGET="${TARGET:-$PWD}"
case "$HARNESS" in
  claude|codex|goose|kimi|gemini|grok|cline|kiro) ;;
  *) echo "forge-init: unknown --harness '$HARNESS' (claude|codex|goose|kimi|gemini|grok|cline|kiro)" >&2
     exit 1 ;;
esac

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

# Harness adapter (non-claude only): stamp the matching adapters/ config with
# the absolute plugin path substituted for __FORGE_PLUGIN_ROOT__, so the config
# invokes the SAME hooks/guard.py. Claude Code needs no stamp — the plugin's
# own hooks/hooks.json (via ${CLAUDE_PLUGIN_ROOT}) already wires the guard.
stamp_adapter() { # <src-relative-to-plugin> <dest-relative-to-target>
  if [ -e "$2" ]; then
    skipped="$skipped $2"
  else
    mkdir -p "$(dirname "$2")"
    sed "s|__FORGE_PLUGIN_ROOT__|$PLUGIN|g" "$PLUGIN/$1" > "$2"
    copied="$copied $2"
  fi
}

adapter_note=""
case "$HARNESS" in
  claude) : ;;  # native — nothing extra to stamp
  codex)  stamp_adapter adapters/codex/hooks.json      .codex/hooks.json ;;
  goose)  stamp_adapter adapters/goose/hooks.json      .agents/plugins/forge/hooks/hooks.json
          adapter_note="copy/symlink .agents/plugins/forge into ~/.agents/plugins/ (Goose discovers hooks there)" ;;
  kimi)   stamp_adapter adapters/kimi/config.toml      .forge/kimi-hooks.toml
          adapter_note="append .forge/kimi-hooks.toml to ~/.kimi/config.toml (Kimi's config is user-global)" ;;
  gemini) stamp_adapter adapters/gemini/settings.json  .gemini/settings.json
          adapter_note="if .gemini/settings.json already existed it was NOT touched — merge the hooks block from adapters/gemini/ by hand" ;;
  grok)   stamp_adapter adapters/grok/hooks.json       .grok/hooks.json ;;
  cline)  stamp_adapter adapters/cline/settings.json   .cline/settings.json
          adapter_note="if .cline/settings.json already existed it was NOT touched — merge the hooks block from adapters/cline/ by hand" ;;
  kiro)   stamp_adapter adapters/kiro/hooks.json       .kiro/hooks/forge-guard.json ;;
esac

# Shared memory DB (created in ./.forge/memory.db by the CLI default).
if python3 "$PLUGIN/memory/forge_memory.py" init >/dev/null 2>&1; then
  mem="initialized .forge/memory.db"
else
  mem="SKIPPED (python3 not found?)"
fi

# Plan-mode-first, ENFORCED by the harness (not a soft CLAUDE.md line): every
# session starts read-only until a plan is approved. Merge into .claude/settings.json
# idempotently — never clobber other settings.
if command -v python3 >/dev/null 2>&1; then
  planmode=$(python3 - "$TARGET/.claude/settings.json" <<'PY'
import json, os, sys
p = sys.argv[1]
os.makedirs(os.path.dirname(p), exist_ok=True)
try:
    with open(p) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        cfg = {}
except (OSError, ValueError):
    cfg = {}
perms = cfg.get("permissions")
if not isinstance(perms, dict):
    perms = {}
if perms.get("defaultMode") == "plan":
    print("already plan-mode-first")
else:
    perms["defaultMode"] = "plan"
    cfg["permissions"] = perms
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
    print("set defaultMode=plan")
PY
)
else
  planmode="SKIPPED (python3 not found?)"
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
echo "  harness:   $HARNESS"
echo "  stamped:   ${copied:-(none - all already present)}"
echo "  skipped:   ${skipped:-(none)}"
echo "  memory:    $mem"
echo "  plan-mode: $planmode"
if [ -n "$adapter_note" ]; then
  echo "  adapter:   $adapter_note"
fi
if [ "$HARNESS" != "claude" ]; then
  echo "  NOTE: the $HARNESS adapter is built to that harness's documented hook"
  echo "        contract but NOT yet validated on the live harness — see docs/HARNESSES.md."
fi
echo ""
echo "Next steps (not automated — they need your call):"
echo "  1. pre-commit install"
echo "  2. create a PRIVATE GitHub repo if none:  gh repo create <Name> --private --source . --push"
echo "  3. fill the [placeholders] in CLAUDE.md (context + commands)"
echo "  4. run /temper for a baseline scorecard"
