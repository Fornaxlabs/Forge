#!/usr/bin/env bash
# Forge self-updater — an update that PROVES it didn't weaken your guardrails.
#
#   bash scripts/forge-update.sh            # check, update, verify, auto-rollback on failure
#   bash scripts/forge-update.sh --check    # only report whether an update is available
#   bash scripts/forge-update.sh --yes      # non-interactive (CI/cron)
#
# Why this is not just `git pull`: Forge is the thing that blocks disasters. A bad
# update could silently disarm it — the worst failure mode for a governance tool
# (you'd believe you were protected). So every update is followed by a behavioural
# re-verification, and ANY failure rolls the update back automatically.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CHECK_ONLY=0; ASSUME_YES=0
for a in "$@"; do
  case "$a" in
    --check) CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
info() { printf '  · %s\n' "$*"; }

PY=""; for c in python3 python; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
[ -z "$PY" ] && { bad "python not found"; exit 1; }

# --- verification battery: does enforcement still BIND? ----------------------
verify_enforcement() {
  local fails=0
  # 1. a catastrophic command must be blocked (exit non-zero from the guard)
  if echo '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
       | "$PY" "$ROOT/hooks/guard.py" >/dev/null 2>&1; then
    bad "guard NO LONGER blocks destructive commands"; fails=1
  else ok "guard blocks destructive commands"; fi
  # 2. a safe command must still pass (no false positives)
  if echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' \
       | "$PY" "$ROOT/hooks/guard.py" >/dev/null 2>&1; then
    ok "guard allows safe commands"
  else bad "guard now blocks SAFE commands (false positive)"; fails=1; fi
  # 3. full self-audit (hook wiring, ceiling, loop cap, secret gates, tamper classes)
  if "$PY" "$ROOT/selfaudit/forge_doctor.py" >/dev/null 2>&1; then
    ok "self-audit passed"
  else bad "self-audit FAILED"; fails=1; fi
  # 4. the labelled deny corpus (24/24, 0 false positives)
  if "$PY" "$ROOT/evals/prove_guard.py" >/dev/null 2>&1; then
    ok "guard proof passed (deny corpus)"
  else bad "guard proof FAILED"; fails=1; fi
  return $fails
}

printf '\n🔨 Forge updater\n\n'

command -v git >/dev/null 2>&1 || { bad "git not found"; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || { bad "$ROOT is not a git checkout — update manually"; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BEFORE="$(git rev-parse HEAD)"
info "checkout: $ROOT (branch $BRANCH @ ${BEFORE:0:8})"

git fetch --quiet origin "$BRANCH" 2>/dev/null || { bad "cannot reach origin"; exit 1; }
AHEAD="$(git rev-list --count HEAD..origin/"$BRANCH" 2>/dev/null || echo 0)"

if [ "$AHEAD" = "0" ]; then
  ok "already up to date"
  exit 0
fi

info "$AHEAD new commit(s) available:"
git --no-pager log --oneline --no-decorate HEAD..origin/"$BRANCH" | sed 's/^/      /' | head -10

# Flag changes that touch the enforcement layer — those deserve a closer read.
ENF="$(git diff --name-only HEAD origin/"$BRANCH" -- hooks/ selfaudit/ evals/ 2>/dev/null || true)"
[ -n "$ENF" ] && { printf '\n'; info "this update TOUCHES THE ENFORCEMENT LAYER:";
                   printf '%s\n' "$ENF" | sed 's/^/      /'; }

[ "$CHECK_ONLY" = "1" ] && { printf '\nRun without --check to apply.\n\n'; exit 0; }

if ! git diff --quiet || ! git diff --cached --quiet; then
  bad "you have uncommitted local changes — commit or stash them first"; exit 1
fi

if [ "$ASSUME_YES" != "1" ] && [ -t 0 ]; then
  printf '\nApply update? [y/N] '; read -r reply
  case "$reply" in y|Y|yes) ;; *) info "aborted"; exit 0 ;; esac
fi

printf '\nUpdating…\n'
if ! git merge --ff-only "origin/$BRANCH" --quiet 2>/dev/null; then
  bad "cannot fast-forward (local commits diverge) — resolve manually"; exit 1
fi
ok "updated to $(git rev-parse --short HEAD)"

printf '\nRe-verifying enforcement (an update must prove it did not disarm Forge)…\n'
if verify_enforcement; then
  printf '\n\033[32m✅ Update applied and verified.\033[0m\n'
  printf '   Restart any running session so the plugin reloads.\n\n'
  exit 0
fi

printf '\n\033[31m✗ VERIFICATION FAILED — rolling back.\033[0m\n'
git reset --hard "$BEFORE" --quiet
ok "rolled back to ${BEFORE:0:8} (your previous, working enforcement)"
printf '   Please report this at https://github.com/Fornaxlabs/Forge/issues\n\n'
exit 1
