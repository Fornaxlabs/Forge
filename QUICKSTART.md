# Forge — Quickstart (5 minutes)

Forge is a governance harness for Claude Code: it **blocks disasters** (destructive
commands, committed secrets, runaway loops, out-of-scope edits), enforces a
**plan → build → review** pipeline, and **won't let a run close "done" without proof**.
This gets you from zero to a governed session.

> **Requirements:** Python 3.11+, git, and Claude Code (`claude`) installed.

## 1. Get Forge
```bash
git clone https://github.com/Mx4flav0r/Forge.git ~/Forge   # or your fork/path
```

## 2. Install the `claude forge` launcher (optional but recommended)
```bash
bash ~/Forge/scripts/install-forge-cli.sh
source ~/.zshrc          # ← REQUIRED: a new shell function only loads after this
                         #   (or just open a new terminal window)
```
Now `claude forge` starts a governed session. Any other `claude …` is untouched.

> **Gotcha we hit ourselves:** editing your shell rc does **not** affect a terminal
> that's already open. If `claude forge` seems to do nothing, you didn't `source` /
> reopen. You'll know it worked when you see the `🔨 Forge:` banner.

## 3. Initialise a project
```bash
cd /path/to/your/project        # must be a git repo: `git init` if not
claude forge                    # or: claude --plugin-dir ~/Forge --permission-mode plan
```
Inside the session:
```
/forge:forge-init               # stamps CLAUDE.md, gates, pre-push hook, plan-mode
```
Then, in a normal terminal, the one-time follow-ups it prints:
```bash
pip install pre-commit && pre-commit install
```

## 4. Verify it's actually enforcing (do NOT skip)
Inside the session:
```
/forge:forge-doctor
```
Expect **`verdict: OK`** with 10/10 checks. This is the difference between Forge being
*loaded* and Forge actually *blocking* — a governance tool that only looks armed is
worse than none. If this isn't green, the guard isn't wired; stop and fix it.

## 5. Work
```
/forge  add a rate limiter to the login route
```
The pipeline runs: triage → plan (you approve) → build (in declared scope) → adversarial
review → verify → close. Along the way the guard will **block**:
- destructive commands (`rm -rf /`, force-push, `DROP TABLE`, …)
- edits outside the plan's declared scope
- the run's tool-call ceiling / repeated-blocker loop cap
- closing a run "green" with no verification logged

Press **Shift+Tab** to cycle permission modes; with the launcher you can drop to
**bypass** once a plan is approved (no more prompts — the guard still blocks).

## What Forge is NOT (read this)
- **Not a security boundary.** The command denylist is a *footgun-catcher* — it stops
  honest mistakes and runaway loops, not a determined adversary (a denylist can't be
  complete). Real protection = least privilege + human approval + not executing
  untrusted input.
- **Not a designer/architect.** It enforces *your* discipline; it doesn't make
  decisions for you. Ambiguous task → it asks, it doesn't guess.
- **Early + Python/Claude-Code-flavoured.** Tested and self-auditing, but young.

## Prove the claims yourself
```bash
python3 ~/Forge/evals/prove_guard.py            # 24/24 blocked, 0 false-positive
python3 ~/Forge/selfaudit/forge_doctor.py       # verdict: OK
python3 -m pytest -q                            # the harness is tested, not asserted
```
Full enforcement test plan: `docs/ENFORCEMENT-TEST-PLAN.md`.
