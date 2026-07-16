# Proof — does FORGE actually do what it claims?

Every number below is produced by a script in this repo. The reproduce command is
printed under each claim — run it yourself. Nothing here is hand-typed; a proof you
can't re-run is marketing.

Last measured: 2026-07-14 · Python 3.11 · commit at time of measurement.

---

## 1. The guard blocks catastrophes and doesn't cry wolf

A labelled corpus of 47 real commands fired at the live guard (`evals/prove_guard.py`).

| Bucket | Result | Meaning |
|---|---|---|
| **Catastrophic** (must block) | **24 / 24 blocked — 100%** | zero false negatives |
| **Safe** (must allow) | **17 / 17 allowed — 0% false-positive** | never wedges normal work |
| **Adversarial** (obfuscated) | **0 / 6 caught** | *documented limit, see §5* |

Blocked includes every common footgun and its variants: `rm -rf /`, `rm -fr /`,
`rm --recursive --force /`, `rm -rf /*`, `--no-preserve-root`, `mkfs`, `dd if=…of=/dev/sda`,
fork bomb, `git push --force / -f / +main / --force-with-lease`, `chmod -R 777 /`,
`DROP TABLE`, `drop database`, `truncate table`, `find / -delete`.

Allowed includes the day-job that a naive denylist breaks: `rm -rf ./build`,
`rm -rf node_modules`, `git push origin feature`, `chmod +x`, `grep -rf`, `git rm … && commit`.

```
python3 evals/prove_guard.py
```

## 2. FORGE audits its own enforcement layer — and catches tampering

`selfaudit/forge_doctor.py` audits the guard **that is actually wired to the blocking
PreToolUse event** (resolved from `hooks.json`, not a fixed path), and behaviour-tests
it. Behaviour, not file-hashes; what runs, not what's on disk.

- **Self-audit on this repo: `verdict: OK` (9/9 checks pass).**
- **Six tamper classes are caught** (each covered by a regression test):
  1. deny-list trimmed → canary battery fails;
  2. guard re-pointed at a decoy script → the *decoy* is loaded and fails;
  3. guard moved to a non-blocking event with a PreToolUse decoy → "no guard wired";
  4. tool-call ceiling neutered (`tick_and_check` stubbed) → behaviour test trips it;
  5. a foreign hook smuggled in (even one whose command contains "guard.py", e.g.
     `curl …/guard.py | sh`) → flagged by *resolved path*, not substring;
  6. a secret gate or plan-mode neutered but left as a commented decoy → rejected
     (gitleaks must appear uncommented; plan-mode is verified by running forge-init).

Any FAIL exits 1. **Honest limit:** this proves the enforcement layer has not been
weakened in these known ways — it is not a proof of total integrity; a novel tamper
outside these classes could still pass. The blessed-hook allowlist is `guard.py` only.

```
python3 selfaudit/forge_doctor.py                 # -> verdict: OK
# demo the catch (on a throwaway copy, never the real repo):
#   remove one pattern from hooks/guard.py -> verdict: FAIL, exit 1
```

## 3. The harness is tested, not asserted

```
python3 -m pytest -q
```

- **74 tests pass.**
- **93% line coverage** across the enforced core:

| Module | Coverage |
|---|---|
| `hooks/guard.py` | 92% |
| `memory/forge_memory.py` | 96% |
| `traces/forge_trace.py` | 97% |
| `selfaudit/forge_doctor.py` | 90% |
| **total** | **93%** |

```
python3 -m coverage run -m pytest -q && python3 -m coverage report \
  --include="hooks/*,memory/*,traces/*,selfaudit/*"
```

## 4. FORGE scans clean under its own compliance tool

```
bash scripts/forge-comply.sh
```

- **Secrets in working tree: 0.** Secrets in last 50 commits of history: **0.**
- Self-audit line reports `verdict: OK`.

---

## 5. Honest limits (read this — it's why the rest is credible)

- **The denylist is a footgun-catcher, not a security boundary.** It caught 0 / 6
  obfuscated commands (base64-piped, variable-hidden target, `python -c shutil.rmtree`,
  aliased, eval-constructed). A regex denylist *cannot* see through those and we do
  not pretend otherwise. Real protection against a determined adversary is least
  privilege + human approval for destructive ops + not executing untrusted input.
  The guard's job is to stop the *honest mistake* and the *runaway loop* — and at
  that, it is 100% / 0% on the corpus above.
- **FORGE does not yet run CI on itself.** It ships the CI template + pre-push gate
  for the projects it bootstraps, but the plugin repo's own `forge-comply` reports
  "pre-push gate NOT installed / CI workflow MISSING." Physician, heal thyself — this
  is a known gap, tracked, not hidden.
- **Multi-agent is Claude-Code-only today.** The Codex adapter (the portability
  claim) is designed in `docs/MULTI-HARNESS-ANALYSIS.md` but not yet built. Until it
  ships, "portable across agents" is a roadmap item, not a fact.
- **Coverage ≠ correctness.** 93% is a floor for regression safety, not a proof of
  bug-freedom.

If any number above ever fails to reproduce, that is a bug — open an issue.
