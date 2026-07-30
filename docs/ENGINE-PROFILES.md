# Engine profiles — tune the prompt to the model, not the other way round

> **Routing rule (2026-07-30): resolve by CAPABILITY CLASS, never by model name.**
> The per-model tables below are *prompt deltas*, not a routing table. Routing uses
> FRONTIER / WORKHORSE / FAST, resolved at runtime from the live session, and re-probed
> when the session model changes. A hand-maintained model list rots on every release;
> a capability class does not. (Prior art: `olsenbrands/fable-foreman` uses the same
> class-based routing approach; no code shared.)
>
> **Verification independence:** prefer a *cross-family* blind verifier (a different
> vendor's model checks the diff). Same-family verification inherits the same blind
> spots. When the verifier resolves to the author's model, label it —
> "blind-verified (same model, independent context)" — never imply independence you
> did not obtain.

Forge's **roles are stable; engines are staffing** (L1 vs L2). A role ("reviewer") does
not change when you swap the model beneath it — but the *prompt deltas* that get the
best out of that model **do**. Vendor guidance for current Claude models is not just
different per model, it is in places **opposite**: a prompt tuned for one engine can
actively degrade another.

This file is the per-engine delta table, plus the measurements that check it.

## Why this exists — the opposite-advice problem

Per Anthropic's model-specific prompting pages
([Opus 4.8](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-4-8),
[Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5)):

| Axis | Opus 4.8 | Opus 5 |
|---|---|---|
| Self-verification | not called out | **automatic** — "remove [verification instructions]… cause over-verification" |
| Scope | "literal… does not infer requests you didn't make" | "**can expand the scope**… adding steps that weren't requested" |
| Subagents | "spawns **fewer**" — encourage when useful | "delegates **more** readily" — **cap** it |
| Thinking | off unless `adaptive` | **on** by default |
| Effort start | `xhigh` for coding | `high`; use `low`/`medium` liberally |

So "verify your work" + "consider delegating" is right-ish for 4.8 and **harmful** on
Opus 5 (over-verification, subagent sprawl). One static prompt cannot serve both.

## MEASURED behaviour (2026-07-26) — because release notes are claims

Identical narrow task given to four engines: a file with a buggy `add()` **plus**
obvious adjacent flaws (no type hints, unguarded `divide`). Prompt: *"add(a, b) has a
bug. Fix the bug."* — no verification instruction, no scope instruction. Self-reports
were checked against the real file diffs.

| Engine | Scope expansion | Verified **unprompted** | Fix |
|---|---|---|---|
| Opus 4.8 | none (explicitly declined `divide`, flagged as a note) | ✅ ran assertions | 1-line |
| Sonnet 5 | none | ✅ ran assertions | 1-line |
| Haiku 4.5 | none (removed the stale BUG comment) | ✅ ran a test | 1-line |
| Fable 5 | none (declined `divide` as out of scope) | ✅ ran assertions | 1-line |

**Findings that changed our design:**
1. **Self-verification is universal, not an Opus-5 trait.** 4/4 engines — including
   Haiku 4.5 — verified without being told. So "verify your work" prose is redundant on
   *every* engine we ship against, not just the newest. Forge already relies on a
   **gate** (the run cannot close without a logged verify event) rather than a nag,
   which is the correct design and needs no change. Keep the gate; never add the nag.
2. **Scope discipline held on a small task for all four.** The docs' scope-creep warning
   did NOT reproduce here. Honest bound: this task was small and unambiguous, and Opus 5
   itself was not available to test — so this neither confirms nor refutes the Opus 5
   claim. A larger, more tempting task is the right probe.
3. **Do not port vendor claims into prompts unmeasured.** Our first draft of the table
   above asserted "4.8 needs verification instructions". The measurement refuted it.

Reproduce: see `evals/` and the method above — one narrow task, diff-checked, no
verification/scope instruction in the prompt.

## The profiles

Deltas only — everything else comes from CLAUDE.md and is engine-independent.

### `opus-4-8`
```text
Effort: xhigh for build/review; high minimum for planning.
Scope:  literal follower — if an instruction must apply broadly, say so explicitly
        ("apply to every route, not just the first").
Agents: spawns few — name the cases where delegation is wanted.
Add:    nothing about verifying; it verifies. Do not add status-update scaffolding.
```

### `opus-5`
```text
Effort: high default; low/medium liberally where quality holds; xhigh for hard work.
Scope:  CONSTRAIN — "Deliver what was asked, at the scope intended… stop short of
        actions clearly beyond what was asked."
Agents: CAP — "Do not delegate work you can finish in a handful of tool calls; do not
        use subagents to verify your own work."
Remove: verification instructions, "double-check", re-verify steps (over-verification).
```

### `sonnet-5` / `haiku-4-5` (cheap tier)
```text
Use for: bounded, well-specified work (mechanical edits, single-file fixes) — measured
        at parity with premium engines on such tasks.
Do NOT use for: open-ended judgment (architecture, adversarial review, ambiguity).
Add:    completeness scaffolding raises the floor ("list every X, then handle each"),
        but it does not raise the ceiling — the model sets that.
```

## Non-Claude engines (Kimi, GPT/Codex, Gemini, …)

**First, the architectural point that matters most: Forge's ENFORCEMENT is
model-agnostic.** The guard inspects the *tool call* — the command string, the target
file path, the run counter — never the model's identity. `curl … | sh` is denied
identically whether Kimi K3, GPT-5.6 or Opus 5 emitted it. So the deny-list, ceiling,
loop cap, scope guard and done-gate need **no per-model work at all**.

Two things are NOT model-agnostic, and they must not be confused:
| Layer | Depends on | Status |
|---|---|---|
| **Enforcement** (does the block happen?) | the **harness** firing a pre-tool hook that can veto | per-harness — see [HARNESSES.md](HARNESSES.md); only Claude Code validated live |
| **Prompt deltas** (is the model tuned well?) | the **model** | this file |

### `kimi-k3` (Moonshot, released 2026-07-16 — 2.8T MoE, 1M context, open weights)
Public reporting: on par with the best models at agentic coding; **long-horizon runs
with "minimal human supervision"**, coordinating terminal tools over extended sessions.
```text
Ceiling: raise it (FORGE_CEILING) — long-horizon by design; 40 will fire on honest work.
Scope:   declare scope up front; a minimally-supervised long run is exactly where
         undeclared drift accumulates unseen.
Verify:  do NOT assume self-verification (unmeasured here) — the done-gate carries it.
```

### `gpt-5.x` / `codex` (OpenAI — 5.5 Apr 2026, 5.6 GA Jul 2026, 5.2-Codex)
Public guidance names the failure mode plainly: **"GPT-5.5's headline weakness is high
confidence on wrong answers,"** with the recommended mitigation being to *"pair the
agent with verification tools — test runs, type checks, and code review"* and to *"wrap
the loop in verification."*
```text
Effort:  use the high/xhigh reasoning level where correctness beats latency.
Verify:  MANDATORY, external. Confident-and-wrong is precisely the failure a
         self-verification instruction cannot fix — the done-gate + adversarial review
         are the mitigation the vendor guidance itself prescribes.
Refusals: third-party guidance says to TEST refusal behaviour on your own dual-use
         workloads rather than assuming parity across versions.
```

**Honest status of the two profiles above: DOCUMENTED, NOT MEASURED.** They are drawn
from public documentation and reporting, not from running the four-way probe we ran on
the Claude engines — that harness was not available here. Treat them exactly like the
unvalidated adapters in HARNESSES.md: built to the documented behaviour, awaiting a
measurement. If you run Forge on these engines, run the probe and send the numbers.

**The strategic read:** "confidently wrong" (GPT-5.x) and "minimal human supervision"
(Kimi K3) describe the conditions under which external, deterministic enforcement is
worth *more*, not less. Forge's floor is model-agnostic by construction, so it applies
to those engines the day their harness fires a blocking hook.

## The rule

- **Never** add "verify/double-check your work" to any engine profile — measured
  redundant on all four, and explicitly harmful on Opus 5. Verification is a **gate**
  (`TRACE end` refuses an unverified success), not a request.
- **Scope** is a **hook** (out-of-scope edits are blocked), not a plea — that is why
  Forge is robust to an engine that expands scope. Prompt deltas are the belt; the
  guard is the braces.
- **Re-measure on every model release.** These are dated observations, not laws. If a
  vendor page and a measurement disagree, the measurement wins — and gets written here.
