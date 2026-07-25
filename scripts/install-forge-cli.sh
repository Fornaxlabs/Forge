#!/usr/bin/env bash
# Install the `claude forge` launcher — a shell function that starts a Forge-governed
# Claude Code session (plugin + plan-mode + bypass-on-tab). Idempotent; safe to re-run.
# Any other `claude …` usage passes straight through untouched.
#
# Usage:  bash scripts/install-forge-cli.sh [path-to-rc-file]
set -euo pipefail

FORGE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
START="# >>> forge cli >>>"
END="# <<< forge cli <<<"

if [ "${1:-}" != "" ]; then
  RC="$1"
else
  case "${SHELL##*/}" in
    zsh)  RC="$HOME/.zshrc" ;;
    bash) RC="$HOME/.bashrc" ;;
    *)    RC="$HOME/.profile" ;;
  esac
fi
touch "$RC"

read -r -d '' BLOCK <<EOF || true
$START
# 'claude forge' -> Forge-governed Claude Code (plugin + plan-mode; Shift+Tab to bypass).
claude() {
  if [ "\$1" = "forge" ]; then
    shift
    if [ ! -d "$FORGE_ROOT/.claude-plugin" ]; then
      echo "⚠ forge: plugin not found at $FORGE_ROOT — launching UNGOVERNED" >&2
    else
      echo "🔨 Forge: loading plugin + plan-mode (verify with /forge:forge-doctor inside)" >&2
    fi
    command claude --plugin-dir "$FORGE_ROOT" --permission-mode plan --allow-dangerously-skip-permissions "\$@"
  else
    command claude "\$@"
  fi
}
$END
EOF

# Strip any previous forge-cli block, then append the fresh one (idempotent).
if grep -qF "$START" "$RC"; then
  awk -v s="$START" -v e="$END" '$0==s{skip=1} !skip{print} $0==e{skip=0}' "$RC" > "$RC.forge.tmp"
  mv "$RC.forge.tmp" "$RC"
fi
printf '\n%s\n' "$BLOCK" >> "$RC"

echo "✓ Installed 'claude forge' into $RC (Forge at $FORGE_ROOT)"
echo "  Activate: source \"$RC\"   (or open a new terminal)"
echo "  Then:     claude forge     # look for the 🔨 banner, verify with /forge:forge-doctor"
