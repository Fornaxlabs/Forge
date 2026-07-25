#!/usr/bin/env bash
# Forge — one-command install.
#
#   bash install.sh              # install + self-verify
#   bash install.sh --no-cli     # skip the `claude forge` shell launcher
#
# Installs the `claude forge` launcher, then VERIFIES the enforcement layer actually
# works (Forge's own rule: no claim without proof). Idempotent — safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
WANT_CLI=1
[ "${1:-}" = "--no-cli" ] && WANT_CLI=0

say() { printf '%s\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; }

say ""
say "🔨 Installing Forge — governance that actually blocks"
say ""

# 1. prerequisites
PY=""
for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
[ -z "$PY" ] && { bad "Python 3.11+ is required and was not found"; exit 1; }
ok "python: $($PY --version 2>&1)"
command -v git >/dev/null 2>&1 && ok "git: $(git --version | cut -d' ' -f3)" \
  || bad "git not found — Forge's commit/push gates need it"
command -v claude >/dev/null 2>&1 && ok "claude CLI found" \
  || say "  · claude CLI not found — install Claude Code to use the plugin"

# 2. shell launcher
if [ "$WANT_CLI" = "1" ]; then
  bash "$ROOT/scripts/install-forge-cli.sh" >/dev/null && ok "installed 'claude forge' launcher"
fi

# 3. VERIFY the enforcement layer really blocks (the whole point)
say ""
say "Verifying enforcement (not taking it on faith)…"
if echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
     | "$PY" "$ROOT/hooks/guard.py" >/dev/null 2>&1; then
  bad "guard did NOT block a catastrophic command — do not rely on this install"
  exit 1
else
  ok "guard blocks destructive commands (exit 2)"
fi
if echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' \
     | "$PY" "$ROOT/hooks/guard.py" >/dev/null 2>&1; then
  ok "guard allows safe commands (no false positives)"
else
  bad "guard blocked a SAFE command — that's a defect, please open an issue"; exit 1
fi
if "$PY" "$ROOT/selfaudit/forge_doctor.py" >/dev/null 2>&1; then
  ok "self-audit passed — enforcement layer intact"
else
  bad "self-audit FAILED — the enforcement layer is weakened or misconfigured"; exit 1
fi

say ""
say "✅ Forge installed and verified."
say ""
say "Next:"
[ "$WANT_CLI" = "1" ] && say "  1. source ~/.zshrc          # or open a new terminal (required!)"
say "  2. cd /your/project && claude forge"
say "  3. /forge:forge-init        # stamp gates into the project"
say "  4. /forge:forge-doctor      # confirm it's armed in-session"
say ""
say "Docs: QUICKSTART.md · Proof: PROOF.md · Test plan: docs/ENFORCEMENT-TEST-PLAN.md"
say ""
