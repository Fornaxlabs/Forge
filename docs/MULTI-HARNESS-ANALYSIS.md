# Forge — Multi-Harness Strategy Analysis

**Question:** Can Forge become genuinely *unique and better* by going multi-agent (Claude Code + Codex + more), and what is the honest positioning against ECC?

**One-line verdict:** Yes — but not by copying ECC. Forge's defensible identity is **the portable enforcement floor for AI coding agents**: the small, hard, non-optional layer (guard + git/CI gates + loop discipline + compounding evals) that survives *whichever* agent you use and *switching between them*. That is an empty niche today. It is real, it is grounded in what the agents now expose, and it is achievable by a solo maintainer *only because it stays lean*. Breadth would kill it; enforcement is the wedge.

---

## 1. The positioning (honest, grounded)

Two different philosophies, and they are not the same product:

| | **ECC** | **Forge** |
|---|---|---|
| Core bet | **Breadth of capability** — give the model more (261 skills, 67 agents, memory, research) | **A hard floor** — stop disasters and thrash whether or not the model cooperates |
| Layer | Advisory (skills, rules, guidance the model *may* follow) | Enforced (hooks/CI/git gates that fire regardless) |
| Loop discipline | **None** (verified — no retry cap, no attribution, no hard stop) | Yes — 3-iteration cap, attribution, `>40` tool-call hard stop |
| Model tiering | **Advisory only** (`/model` by hand) | Can be **enforced/auto-escalating** (unbuilt, on-thesis) |
| Config self-audit | Partial (AgentShield scans config) | Add-on candidate — audit the enforcement layer itself |
| Maintenance model | 230+ contributors, weekly | Solo — *must* stay small to survive |

**We will never out-breadth ECC and should not try.** Breadth × 7 harnesses is a maintenance army's job. But breadth is advisory, and advisory is exactly the layer that "the model may ignore." Forge's whole thesis — *a rule belongs at the lowest layer where it's enforceable* — is the layer ECC deliberately skips. That is the seam.

---

## 2. Feasibility — what actually ports across agents

Forge is not one thing; it is three layers with **very different portability**. This is the crux.

### Layer A — Agent-agnostic (ports everywhere, zero adaptation)
These do not care which agent generated the diff:
- **Pre-commit + pre-push secret gate** (gitleaks) — git-level, universal.
- **CI pipeline** (tests, dep-audit, SBOM) — runs on the repo, not the agent.
- **Standards docs** (SECURITY / LLM-SECURITY / ENGINEERING) — plain markdown any agent can be pointed at.
- **`forge-init` bootstrap** — stamps the above into any repo.

> This layer alone already makes Forge multi-agent: it protects a repo used with Cursor, Copilot, Gemini, *anything*, because it lives in git + CI, not in the agent.

### Layer B — Enforcement hooks (ports to agents that expose lifecycle hooks)
The in-session guard (`PreToolUse` → block destructive commands, tool-call ceiling) depends on the agent having a hook API.

**Grounded capability matrix (July 2026):**

| Agent | `PreToolUse`-style hook? | Plugin can bundle hooks? | Guard ports? |
|---|---|---|---|
| **Claude Code** | Yes (~26–30 lifecycle events) | Yes (`hooks/hooks.json`) | ✅ native (today) |
| **Codex CLI** | **Yes — `PreToolUse`, `PostToolUse`, `PreCompact`, `SessionStart`, `Stop`, etc.** | **Yes — plugin manifest / `hooks/hooks.json`** | ✅ with an adapter |
| **OpenCode** | Plugin system (headless, model-agnostic) | Yes (plugin) | ⚠️ likely, needs verification |
| **Cursor** | Rules-based (`.cursor/rules`) — advisory, not enforced hooks | No enforced hook layer | ❌ Layer A only |
| **Copilot** | VS Code instructions — advisory | No | ❌ Layer A only |

**The key finding:** Codex copied Claude Code's model closely — same event names, same `hooks/hooks.json` plugin bundling. Forge's `guard.py` is ~one adapter away from running under Codex. Two agents now share the enforcement primitive Forge is built on. That is what makes "portable enforcement" real rather than aspirational.

Caveat: the hook **input JSON schema and exit-code semantics differ** between Claude Code and Codex — `guard.py` needs a thin per-harness shim (parse that harness's event payload, emit that harness's block signal). Not free, but small and bounded.

Note also (grounded): **Codex enforces in the kernel (sandbox); Claude Code enforces in the harness.** Different mechanisms, both real enforcement points — which actually strengthens the story: Forge can lean on whichever the host agent offers.

### Layer C — Agent-specific (does not port cleanly)
- **Adversarial reviewer** = a Claude Code subagent. Codex has `SubagentStart`/`Stop`, so a port is plausible; Cursor/Copilot have no equivalent. Treat as Claude-Code-first, Codex-maybe, others-no.
- **Plan-mode enforcement** (`permissions.defaultMode=plan`) is Claude-Code-specific.

---

## 3. The unique wedge

Nobody owns **cross-agent enforcement.**
- ECC does cross-agent **advisory breadth** (skills ported to 7 tools).
- Everyone else does **single-agent** tooling.
- No one ships *"the disaster-proofing + loop-discipline + compounding-eval floor that works under any agent and survives you switching agents."*

That sentence is the product. It is honest (Layer A is genuinely universal; Layer B genuinely ports to Claude Code + Codex), it is unmet, and it is *small enough for one person* because it is a floor, not a library.

**Why "survives switching agents" matters:** teams increasingly run more than one agent (Claude Code for depth, Codex for others, Cursor in the IDE). Their *standards, secret gates, loop discipline, and bug-corpus* should not reset per tool. Forge as the constant enforcement layer beneath a rotating cast of agents is a real, felt need — and it is the opposite of what a per-agent skills pile offers.

---

## 4. What makes it genuinely *better* (not bigger)

Four mechanisms, all enforced, all portable to the degree each agent allows — each does something ECC provably does **not**:

1. **Enforced loop discipline** — cap retries per blocker, attribute failure (`PLAN|CONTEXT|TOOL|CAPABILITY`), hard-stop to a human. ECC has none.
2. **Auto model-escalation** — repeat `CAPABILITY` blocker → up-tier the builder model automatically before escalating to a human. ECC's tiering is advisory `/model` only. (Timely: Fable is now rationed/paid, so keeping the strong model on judgment matters.)
3. **Config self-audit** — check the enforcement layer itself hasn't been weakened/tampered (deny-list gutted, hook disabled, hostile hook added). Directly closes the class of blind spot that let a real secret slip past the automated gate before.
4. **Compounding eval corpus (the "instincts" idea, done lean)** — auto-capture a lesson at session-end, promote recurring ones into regression evals. This is the one asset that appreciates with use and cannot be cloned from you — it's *your* projects' scar tissue.

"Better" = better **at enforcement** and better **at portability of enforcement**. Not better/bigger overall. Stated that way, it's true.

---

## 5. Proposed architecture

```
forge-core/                 # agent-agnostic, the real product
  standards/                # markdown, universal
  gates/                    # gitleaks config, pre-commit, pre-push, CI templates
  guard/guard.py            # enforcement logic, harness-neutral core
  loop/                     # iteration cap + attribution + auto-escalation
  evals/                    # compounding corpus (instincts capture + promote)
  selfaudit/                # config-tamper check

adapters/
  claude-code/              # hooks.json + guard shim + reviewer subagent + plan-mode
  codex/                    # hooks.json/config.toml + guard shim (+ subagent reviewer)
  opencode/                 # plugin wrapper (verify)
  generic-git/              # Layer A only: for Cursor/Copilot/anything — git+CI, no in-session guard
```

Design rule: **the core is harness-neutral; adapters are thin.** `guard.py` already parses an event payload and decides block/allow — split it into `decide(event) -> verdict` (shared) + `parse_<harness>(stdin) -> event` / `emit_<harness>(verdict)` (per adapter). Same for the loop layer.

---

## 6. Honest risks (what could kill this)

- **Maintenance multiplies.** Even a lean core × N harnesses is real solo work. Each adapter is ongoing (agents change their hook APIs). Mitigation: ship Layer A + Claude Code + Codex only; add others *on demand*, never speculatively.
- **The moat is thin and time-boxed.** ECC (or Claude Code itself) could add loop discipline and enforced escalation in a release. Forge's window is *now*; if this drags for months, the seam closes. Speed is the strategy.
- **Cursor/Copilot get Layer A only.** Be honest in the README: on agents without enforced hooks, Forge is the git/CI floor, not the in-session guard. Don't oversell.
- **Adapter drift.** Codex's hook schema ≠ Claude Code's; both will change. The `decide()`-core / thin-adapter split is what keeps this survivable — do not let harness specifics leak into the core.
- **Demand is unproven.** "Cross-agent enforcement floor" is a real-sounding need, not a validated one. Treat the first public release as a probe, not a bet-the-farm.
- **Subagent reviewer doesn't generalize.** Keep it a Claude-Code (and maybe Codex) feature; don't block the multi-harness story on it.

---

## 7. Phased roadmap

**Phase 0 — sharpen the core, single agent (days).**
Build the 4 mechanisms on Claude Code first: instincts capture (seed with the 4 STFC RCAs), auto-escalation, config self-audit, keep the loop-brake. Prove they're real where the API is native.

**Phase 1 — extract the harness-neutral core (days).**
Refactor `guard.py` and the loop layer into `decide()` + adapter shims. No new features — just the seam that makes Phase 2 cheap.

**Phase 2 — Codex adapter (the proof of "multi-agent") (days).**
Write the Codex `hooks/hooks.json` + payload shim. Ship Forge as a Codex plugin. This is the credibility moment: the *same* enforcement floor under two agents.

**Phase 3 — generic-git adapter (Layer A everywhere).**
Package the git+CI floor as a drop-in for Cursor/Copilot/any repo. Low effort, broad reach, honest scope.

**Phase 4 — evaluate demand before going wider.**
Only add OpenCode/Gemini/etc. if real users ask. Never port speculatively.

---

## 8. Recommendation

1. **Reframe Forge publicly as "the portable enforcement floor for AI coding agents."** That is unique, true, and unoccupied.
2. **Do Phase 0 + 1 + 2** — sharpen the enforcement mechanisms, extract the neutral core, ship the Codex adapter. That single sequence delivers "unique and better" honestly, on grounded facts, at solo scale.
3. **Refuse breadth.** No skill piles, no 7-harness speculation, no advisory features. The moment Forge chases ECC's game, it loses; the moment it owns enforcement, it wins its niche.
4. **Move now.** The window is the gap between "agents shipped hooks" and "the big harnesses add loop discipline." That gap is open today.

**Bottom line:** Forge can be genuinely unique and genuinely better — as the *enforcement floor no one else builds, portable across the agents that now expose the hooks to enforce it.* Small on purpose. That smallness is the strategy, not the limitation.

---

### Sources
- Codex hooks (lifecycle events, plugin hook bundling): https://developers.openai.com/codex/hooks · https://deepwiki.com/openai/codex/3.11-hooks-system
- "Codex hooks make the harness real": https://blakecrosley.com/blog/codex-hooks-make-the-harness-real
- Kernel-vs-harness enforcement framing: https://www.firecrawl.dev/blog/best-ai-coding-agents
- ECC (breadth, no loop discipline, advisory tiering): https://github.com/affaan-m/ECC · https://github.com/affaan-m/ECC/blob/main/docs/token-optimization.md
