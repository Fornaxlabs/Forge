# Why FORGE

**FORGE makes the good practices you already believe in impossible to skip.**

Not a linter. Not a "rules file." A governance harness for AI-assisted coding that
turns "trust the model and hope" into a disciplined pipeline with a floor you
*cannot* fall through.

---

## The problem it solves

AI writes code fast — and drops the discipline just as fast. Under deadline, the
predictable things happen:

- a secret gets committed,
- a test gets *weakened* to go green instead of the bug getting fixed,
- a destructive command runs,
- an endpoint ships with no auth,
- the same bug you fixed last month quietly comes back,
- the model spirals in a fix-it loop for an hour and makes it worse.

You know better. The problem isn't knowledge — it's that discipline slips exactly
when it matters most. FORGE is the machinery that stops the slipping.

---

## What you get

**1. A hard security floor — enforced by machine, not by memory.**
A `PreToolUse` hook blocks catastrophic commands (`rm -rf /`, force-push, DB drops,
network-lockout commands). Pre-commit + a `pre-push` gate stop secrets from ever
being committed or pushed. CI runs tests, dependency-audit, and SBOM. None of it
needs you to cooperate — it fires even if you run with `--dangerously-skip-permissions`.
*Verified: the guard blocks real commands; the pre-push gate catches a secret sitting
in git history, not just the working tree.*

**2. An adversarial reviewer on every change.**
A reviewer that thinks like an attacker, judging your diff against your standards —
SQL injection, missing authorization, injection via config. In testing it caught the
planted faults **and a vulnerability nobody planted.** It's the second pair of eyes
that doesn't get tired and isn't invested in defending the code it just wrote.

**3. Enforced loop discipline.**
The default failure mode of AI coding is the runaway loop. FORGE caps it: max 3
iterations per blocker, *diagnose why it failed before retrying*, **never resolve a
blocker by editing the test**, and a hard stop that escalates to a human. Convergent
iteration instead of thrashing.

**4. Bugs become permanent tests.**
Every escaped bug goes through `postmortem → eval`: it's turned into a regression
test that fails until it's caught. The bug you fix once can't silently return.

---

## Why it's different

Most "AI coding frameworks" are markdown telling the model to behave — advice the
model can skip. FORGE's core insight: **a rule belongs at the lowest layer where it's
enforceable.** The things that matter are hooks, git gates, and CI — mechanisms that
hold whether or not the model (or you) cooperates. The soft guidance sits on top of a
hard floor, not the other way around.

That's why the security floor and loop-brake survive even when you turn permissions
off: they're not asking nicely, they're enforced.

---

## What it is NOT (so you can trust what it is)

- **Not a security boundary.** The command guard is a footgun-catcher; a denylist
  can't stop a determined adversary. It raises the floor; it doesn't make you secure.
- **Not a designer or a stack-picker.** It enforces discipline on what *you* decide
  to build; it won't architect your app or make a beginner an engineer.
- **Not magic, not finished.** It's opinionated toward Python/FastAPI today, and it's
  early. Use it as a power tool, not a silver bullet.

If a tool promises to make your code good automatically, it's lying. FORGE promises
something smaller and real: **it makes disasters hard and your standards non-optional.**

---

## Who it's for

Capable builders who *have* standards worth enforcing and are tired of them slipping.
If you've ever shipped a bug you'd already fixed, committed a key by accident, or
watched an AI thrash a fix into the ground — this is for you.

---

## Try it (two commands)

```
# load it (dev)
claude --plugin-dir /path/to/Forge

# bootstrap a project (constitution + gates + plan-mode + memory, idempotent)
/forge-init
```

Then run `/forge <task>` and watch it triage, build the smallest increment, review it
adversarially, and refuse to bypass its own veto.

---

**The one-liner:** *FORGE turns a project from "disciplined when you remember" into
"disciplined by default, disaster-proofed by machine, and permanently guarded against
every bug it has already seen."*
