#!/usr/bin/env bash
# FORGE compliance scanner — READ-ONLY. Gathers deterministic signals for
# /forge-comply; the reviewer agent scores + prioritizes from this output.
# Never modifies the project. Missing tools degrade gracefully (reported, not fatal).
set -uo pipefail

TARGET="${1:-$PWD}"
cd "$TARGET"
sep() { echo "== $1 =="; }

# Build an ignore regex from .forgeignore (+ sane defaults) for the file-walk checks.
IGN='node_modules|/vendor/|/dist/|\.min\.(js|css)|\.(jpg|jpeg|png|gif|webp|ico|pdf|zip|rlib|rmeta)$|/target/'
if [ -f .forgeignore ]; then
  while IFS= read -r p; do [ -n "$p" ] && IGN="$IGN|$p"; done < .forgeignore
fi

sep "SECRETS (tree + history)"
if command -v gitleaks >/dev/null 2>&1; then
  tree_n=$(gitleaks dir . --redact --no-banner 2>/dev/null | grep -ic "finding" || true)
  echo "tree findings: ${tree_n:-0} (post-.gitleaks.toml allowlist)"
  hist_n=$(gitleaks git --log="HEAD~50..HEAD" --redact --no-banner 2>/dev/null | grep -ic "finding" || true)
  echo "recent-history findings (last 50 commits): ${hist_n:-0}"
  [ -f .gitleaks.toml ] && echo "allowlist: .gitleaks.toml present" || echo "allowlist: MISSING (.gitleaks.toml) — scan will be noisy"
else
  echo "gitleaks: NOT INSTALLED — cannot check secrets"
fi

sep "DEPENDENCIES / CVEs"
req=$(ls requirements*.txt pyproject.toml 2>/dev/null | head -1 || true)
if command -v pip-audit >/dev/null 2>&1 && [ -n "$req" ]; then
  cve=$(pip-audit -r "$req" --progress-spinner off 2>/dev/null | grep -c "^[a-zA-Z]" || true)
  echo "source: $req · vulnerable-package lines: ${cve:-0}"
else
  echo "pip-audit or requirements file: not available"
fi

sep "LINT (ENGINEERING)"
if command -v ruff >/dev/null 2>&1; then
  total=$(ruff check . --output-format=concise 2>/dev/null | grep -cE "^\S+:[0-9]+" || true)
  fixable=$(ruff check . --output-format=concise 2>/dev/null | grep -c "\[\*\]" || true)
  echo "findings: ${total:-0} · auto-fixable (ruff --fix): ${fixable:-0}"
else
  echo "ruff: NOT INSTALLED"
fi

sep "ROUTES / AUTH (heuristic — reviewer must confirm)"
routes=$(grep -rEl "@(app|router)\.(get|post|put|delete|patch)" --include="*.py" . 2>/dev/null | grep -vE "$IGN" | wc -l | tr -d ' ')
route_decl=$(grep -rE "@(app|router)\.(get|post|put|delete|patch)" --include="*.py" . 2>/dev/null | grep -vE "$IGN" | wc -l | tr -d ' ')
deps=$(grep -rE "Depends\(" --include="*.py" . 2>/dev/null | grep -vE "$IGN" | wc -l | tr -d ' ')
echo "route decorators: $route_decl across $routes files · Depends() usages: $deps"
echo "(if Depends usages << route decorators, suspect missing deny-by-default authz — reviewer inspects)"

sep "GATE LIVENESS (present AND active?)"
[ -f .pre-commit-config.yaml ] && echo "pre-commit config: present" || echo "pre-commit config: MISSING"
[ -f .git/hooks/pre-commit ] && echo "pre-commit INSTALLED (hook present)" || echo "pre-commit NOT installed (run 'pre-commit install')"
[ -f .git/hooks/pre-push ] && echo "pre-push gate INSTALLED" || echo "pre-push gate NOT installed"
ls .github/workflows/*.y*ml >/dev/null 2>&1 && echo "CI workflow: present" || echo "CI workflow: MISSING"

sep "REPO HYGIENE"
bin_tracked=$(git ls-files 2>/dev/null | grep -icE "\.(jpg|jpeg|png|gif|webp|ico|pdf|zip|rlib|rmeta|min\.js|min\.css)$" || true)
echo "tracked binary/build/minified files: ${bin_tracked:-0} (candidates for .gitignore)"

sep "TESTS / COVERAGE"
tests=$(git ls-files 2>/dev/null | grep -cE "test_.*\.py|_test\.py|/tests?/" || true)
echo "test files: ${tests:-0}"
grep -qiE "cov-fail-under|--cov" .github/workflows/*.y*ml .pre-commit-config.yaml pyproject.toml 2>/dev/null \
  && echo "coverage gate: referenced in CI/config" || echo "coverage gate: NOT found"

sep "GOVERNANCE DOC SPRAWL"
md=$(git ls-files '*.md' '*.txt' 2>/dev/null | wc -l | tr -d ' ')
gov=$(git ls-files '*.md' '*.txt' 2>/dev/null | grep -icE "(CLAUDE|AGENTS|STANDARD|AUDIT|PLAN|VISION|FIX|GUIDE|READINESS|NOTES|TODO|DESIGN|ARCHITECTURE)" || true)
echo "markdown/text docs: ${md:-0} · governance/rule-ish docs: ${gov:-0} (consolidation candidates)"

sep "WAIVERS"
[ -f .forge/waivers.md ] && echo "accepted-exception file: .forge/waivers.md present" || echo "no .forge/waivers.md (findings cannot be waived yet)"

sep "COULD NOT CHECK (state in report)"
echo "runtime behavior · whether leaked secrets were rotated · full git history beyond 50 commits · auth correctness (only presence heuristics)"
