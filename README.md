# Forge — Governance & Security Guardrails for AI Coding Agents

**Your AI coding agent will run `rm -rf /` if you let it. Forge doesn't let it.**

Forge is an open-source **AI coding governance harness** that puts a deterministic
enforcement floor under AI coding agents — Claude Code, Codex, Cursor, Gemini CLI,
Cline, Kiro and more. It **blocks destructive commands, stops runaway agent loops,
prevents out-of-scope edits, catches committed secrets, and refuses to let a task be
called "done" without proof it was verified.**

Not suggestions. Not a prompt that asks the model nicely. **Hooks that return exit 2
and stop the tool call.**

```bash
git clone https://github.com/Fornaxlabs/Forge.git ~/Forge && bash ~/Forge/install.sh
```

The installer verifies the enforcement actually works before it claims success.

---

## Why this exists

AI coding tool adoption is at ~84% — and developer *trust* in the output is at an
all-time low. Teams now spend **more time reviewing AI-generated code than writing
code**, and studies keep finding a large share of AI-generated code ships avoidable
security flaws. The developers getting real value aren't the ones who trust AI most —
they're the ones with **systematic review built into the workflow**.

Forge is that workflow, enforced — so it can't be skipped on the day you're tired.

### The uncomfortable part: most "guardrails" don't guard

"Enforcement" hooks are easy to get wrong. Reading the source of one of the most-starred
Claude Code toolkits on GitHub, its two "blocking" hooks print `BLOCKED` and then call
`process.exit(1)`. Per Claude Code's
[hook documentation](https://code.claude.com/docs/en/hooks.md), **only exit code 2
blocks a tool call** — exit 1 is a *non-blocking* error and the action proceeds:

> "Claude Code treats exit code 1 as a non-blocking error and proceeds with the action…
> If your hook is meant to enforce a policy, use `exit 2`."

A guardrail that says "blocked" while the command runs is worse than none — it buys
false confidence. **Forge exits 2, and ships a self-audit that proves it still does.**

## What Forge enforces

| Control | What it stops | Enforced by |
|---|---|---|
| **Destructive-command deny** | `rm -rf /`, force-push, `DROP TABLE`, `mkfs`, fork bombs, `curl … \| sh` | PreToolUse hook, exit 2 |
| **Subagent fan-out cap** | a run quietly spawning an agent swarm | run-wide agent roster |
| **Tool-call ceiling** | runaway agents burning tokens in a loop | run-wide counter, all subagents |
| **Loop cap** | the same blocker "fixed" over and over | trace-driven, escalates to a human |
| **Scope guard** | edits to files the plan never declared | hook blocks the write |
| **Definition-of-done gate** | closing a task "done" with no verification | run cannot close without evidence |
| **Secret gates** | credentials reaching your remote | git pre-commit + pre-push (works outside the agent) |
| **Self-audit** | *the guardrails being quietly weakened* | `forge-doctor`, 9 tamper classes |

Plus a governed pipeline — **triage → plan → human approval → build → adversarial
review → verify** — with a JSONL trace of every run.

## Compliance-ready audit trail

Every governed run is recorded, and `forge_audit.py` exports it as evidence: who
approved what, at which risk tier, what scope was declared, and whether it was verified
before closing.

```bash
python3 status/forge_audit.py . --out audit.md     # or --json
```

That's the lineage-backed, human-oversight record that **EU AI Act** readiness and
**ISO 42001** programs ask for — generated from what actually happened, not a
questionnaire.

## Quick start

```bash
bash install.sh          # installs + self-verifies
source ~/.zshrc          # required: load the launcher (or open a new terminal)
cd /your/project
claude forge             # governed session: plugin + plan-mode
```
Inside the session:
```
/forge:forge-init        # stamp gates into this project
/forge:forge-doctor      # confirm it's actually armed  ← never skip this
/forge  add rate limiting to the login route
```

Full guide: **[QUICKSTART.md](QUICKSTART.md)**

## Prove it yourself — don't take our word

Forge's rule is that no claim ships without a reproducible proof:

```bash
python3 evals/prove_guard.py        # 24/24 catastrophic blocked, 0 false positives
python3 selfaudit/forge_doctor.py   # verdict: OK — enforcement layer intact
python3 -m pytest -q                # 324 tests
```

- **[PROOF.md](PROOF.md)** — every claim, with the command that reproduces it
- **[docs/ENFORCEMENT-TEST-PLAN.md](docs/ENFORCEMENT-TEST-PLAN.md)** — verify each
  control blocks, safely, on your own machine

## It maintains its own calibration

Guardrails rot. A limit tuned for last year's models fires on this year's honest work —
and a guardrail that annoys is one you switch off. Two tools keep Forge honest over time:

```bash
python3 status/forge_calibrate.py .        # are my limits still right?
bash scripts/forge-update.sh               # update, re-verify, auto-rollback
```

- **`forge_calibrate`** reads *your* run history and reports limits that are **too tight**
  (firing on honest work) or **too loose** (never firing — security theatre), with the
  evidence and the command to fix it. It never edits your config: a control that loosens
  itself is a control that disarms itself, so Forge proposes and you decide.
- **`forge-update`** is not `git pull`. After updating it re-runs the enforcement battery
  and **rolls the update back automatically if any check fails** — verified against a
  simulated supply-chain attack that stubbed out the deny-list under an innocuous commit
  message. A governance tool must never be able to silently disarm itself.

Models shift too: guidance for current models is in places *opposite* (one is a literal
follower that spawns few subagents; another expands scope and delegates readily). Per-engine
prompt deltas — and the measurements behind them — live in
[docs/ENGINE-PROFILES.md](docs/ENGINE-PROFILES.md). **Enforcement itself is model-agnostic:**
the guard inspects the tool call, never the model, so `curl … | sh` is denied whoever emitted it.

## Honest limits (please read)

- **The denylist is a footgun-catcher, not a security boundary.** It stops honest
  mistakes and runaway loops — not a determined adversary. It catches 0/6 deliberately
  obfuscated commands, and we publish that number. Real protection is least privilege
  + human approval + not executing untrusted input.
- **Forge does not design your software.** It enforces *your* standards. Ambiguous
  task → it asks; it does not guess.
- **Early project.** Tested, self-auditing, and used on real work — but young, and
  Python/Claude-Code-flavoured today. Other harnesses are wired to their documented
  hook contracts and are marked experimental until validated live.
- **Traces are self-reported by each run** — they evidence governed discipline;
  enforcement integrity is attested separately by the self-audit.

## Multi-harness

One harness-neutral decision core (`hooks/guard.py`) speaks both documented block
signals — exit-2 + stderr, or deny-JSON (`FORGE_BLOCK_MODE=json`) — with thin install
configs in `adapters/` for Codex CLI, Gemini CLI, Cline, Kiro, Goose, Kimi and
grok-build. Validation status per harness: **[docs/HARNESSES.md](docs/HARNESSES.md)**.

## Contributing

Issues and PRs welcome — especially real-world false positives from the guard, and
adapter validation on harnesses other than Claude Code. Forge runs its own gates in CI
(`ruff`, `mypy --strict`, `pytest`, gitleaks, guard-proof, self-audit); PRs must be
green.

## License

Apache-2.0 — see [LICENSE](LICENSE).

---

<sub>**Keywords:** AI coding agent governance · AI code security guardrails · Claude
Code hooks · AI agent guardrails · LLM code review enforcement · AI coding compliance ·
EU AI Act AI code audit trail · ISO 42001 AI governance · prevent destructive commands
AI agent · agentic coding safety · AI code quality gates</sub>
