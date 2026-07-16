# Forge — Product Spec & Feature List (scope freeze)

**What Forge is:** a quality & optimization tool for AI coding agents — *checks that bind, savings
you can measure, and a certificate that proves the process.* Others advise the model; Forge verifies
the work, and the checks can't be ignored because they don't run inside the model's goodwill — they
run in hooks, git, and CI.

**Positioning (2026-07):** quality/optimization is the product; enforcement is the mechanism. Enforcement
is to Forge what end-to-end encryption is to Signal — the engine, not the identity.

**Status legend:** 🟢 shipped (code + tests) · 🟡 partial (works, but part is prose/config or under-verified)
· ⚪ planned (designed, not built) · 🟣 preview (design mockup only).

---

## The layer model (and the invariant that holds it together)

Forge is six layers. The single most important rule — the one whose violation the review caught — is
the boundary between **L1 (roles)** and **L2 (engines)**:

> **A role is stable identity: responsibility, permissions, operating prompt. An engine is dynamic
> staffing: which model fills the seat. Escalation swaps the *engine*, never the *role*, and never
> widens a role's permissions. A seat may *require* a minimum engine tier — that is the role
> constraining the engine, not the engine defining the role.**

| Layer | Owns | Changes at runtime? |
|---|---|---|
| **L0 — Enforcement floor** | deterministic checks that bind regardless of the model | no |
| **L1 — Pipeline & roles** | what happens, who does it, what they may touch | no |
| **L2 — Engines & optimization** | which model staffs a seat, escalation, prompting | **yes** |
| **L3 — Memory & learning** | evidence that compounds (traces, scar tissue, evals) | accumulates |
| **L4 — Certification** | the public, verifiable proof of process & checks | per commit |
| **L5 — Surfaces** | how a human sees and configures all of the above | — |

---

## L0 — Enforcement floor (deterministic; binds no matter what the model does)

The floor that makes speed safe. Every item here fires from a hook, git, or CI — not from the model
choosing to comply.

| Feature | What it does | Status | Review note |
|---|---|---|---|
| **Guard — command deny** | `PreToolUse` hook blocks catastrophic Bash before it runs (rm -rf /, force-push, mkfs, dd, DROP TABLE, fork bomb). Fails **open**. | 🟢 | Verified: 24/24 blocked, 0/17 false positives. Honest limit: 0/6 on obfuscated commands — footgun-catcher, **not** a security boundary. |
| **Tool-call ceiling** | Hard stop at 40 tool calls per active run, flock-counted in `guard.py`. | 🟢 | The one enforced loop control today. |
| **Loop cap (3 iterations/blocker)** | Cap review retries per blocker → force attribution (PLAN\|CONTEXT\|TOOL\|CAPABILITY) → escalate to human. | 🟡 | **Finding B1:** currently **prose** in `commands/forge.md`, not hook-enforced. Presenting it as "enforced" is an overclaim. **First build item.** |
| **Secret gate — pre-push** | Blocks a push whose commits contain a secret (scans pushed history, not just working tree). Fails **closed**. | 🟢 | Real. Claim must stay scoped: history scan is verified for the *pushed range* / last-50-commits in proof runs, not "anywhere forever." |
| **Secret gate — pre-commit** | gitleaks + ruff + mypy on every commit. | 🟢 | — |
| **CI gates** | lint · tests · coverage ≥80% · pip-audit · SBOM. Dormant until a project has code. | 🟢 (template) | Gap: Forge does **not** run CI on itself yet (physician-heal-thyself). |
| **Self-audit (`/forge-doctor`)** | Audits the guard *actually wired* to the blocking PreToolUse event and behaviour-tests it (canaries, ceiling trip, resolved-path foreign-hook check, uncommented gate, forge-init plan-mode). Fails **closed**. | 🟢 | **Findings A1–A6 fixed (2026-07-16):** was presence/substring-based and evadable; now resolves + behaviour-tests what runs. Catches 6 tamper classes, each regression-tested (17 tests). Honest limit: not a proof of total integrity. |
| **Config self-integrity** | After any config change, re-run self-audit + record the change in the trace; loosening is never silent. | ⚪ | Design established; depends on the self-audit fix above being real. |

---

## L1 — Pipeline & roles (stable identity: the dev team)

The work always flows **Anvil → Smith → Quench**, with **Warden** vetting every command and **Ledger**
recording every step, and **you** as the only human in the chain of command. Names are configurable;
roles, permissions, and handoffs are not. Nobody approves their own work; nobody works unwatched.

### The pipeline
| Stage | What it does | Status | Review note |
|---|---|---|---|
| **Plan-mode-first** | Session starts read-only (`permissions.defaultMode=plan`); build unlocks only after an approved plan. | 🟢 | Stamped by `forge-init`. |
| **Triage (S/M/L)** | Every task sized; LARGE (auth/secrets/deps/network/data/destructive) needs human approval + checkpoint first. | 🟡 | Agent-followed procedure, not yet hook-gated. |
| **Plan capture** | Hook persists the approved plan to `.forge/plans/<run>.md` — the baseline drift & certification measure against. | ⚪ | **Second build item.** `PostToolUse` on `ExitPlanMode`. Makes the "approval waiting" state and the L4 provenance real. |
| **Build** | One approved task at a time; guard live on every call. | 🟢 | — |
| **Adversarial review** | Reviewer with veto; a BLOCKER can never be "fixed" by editing a test or a rule. | 🟢 | Real agent, catches faults (verified 2026-07-09). |
| **Gates** | See L0 secret gates + CI. | 🟢 | — |

### The roster (roles — L1 identity; engine shown is L2 staffing, see next section)
| Role | Responsibility | Permissions (least privilege) | Required tier | Status |
|---|---|---|---|---|
| **Anvil** — architect | Sizes work; writes plans; flags LARGE for your sign-off. | read + write-plans · **no** file edits, **no** commands | judgment | 🟡 |
| **Smith** — builder | Writes the code. | edit + bash (guard-checked) · **no** push, **no** self-approve | standard (up-tiers under policy) | 🟡 |
| **Quench** — reviewer | Finds problems before you do; holds the veto. | read + veto · **cannot** edit what it judges, **no** push | judgment (pinned) | 🟡 |
| **Warden** — guard | Vets every command in ms; halts runaways. **Not AI — pure code.** | block any command · halt run · (cannot think, cannot be persuaded) | none | 🟢 |
| **Ledger** — recorder | Writes every step to the trace; powers the Run Recorder. **Not AI.** | append-only trace | none | 🟢 (trace) / 🟣 (recorder) |
| **Sentinel** — drift watcher | Watches long sessions for memory loss & scope creep; re-pins plan/standards after compaction. | read + checkpoint judge | judgment | ⚪ |
| **Bellows** — test engineer | Writes the tests the builder would skip; keeps coverage above the gate. | edit tests + bash | standard | ⚪ |

> **Review note (roles):** in today's shipped plugin **one** reviewer agent wears the Anvil/Smith/Quench
> hats in sequence (`agents/reviewer.md`); Warden and Ledger's trace are real code. The **split roster**
> with per-role permissions and independent engines is the v1 target. The invariant above governs it:
> escalating Smith's engine never turns Smith into Quench and never grants Smith push rights.

---

## L2 — Engines & optimization (staffing policy; the layer that changes at runtime)

Separate from roles by design (the review's core correction). This is where *cost & quality
optimization* lives — the "savings you can measure."

| Feature | What it does | Status | Review note |
|---|---|---|---|
| **Model tiering** | Cheap engine (sonnet) staffs building; strong engine (opus) staffs judgment seats. | 🟡 | Today: static `model:` pins in agent frontmatter. Dynamic assignment is the target. Empirical basis: bounded tasks = parity (58/58), judgment = Opus>Sonnet>Haiku. |
| **Auto-escalation (up-tier)** | Repeat CAPABILITY blocker → swap the seat's engine to a stronger tier *before* escalating to a human. Role & permissions unchanged. | ⚪ | **Finding B5:** was shown as live and contradicted the flagship "escalate to human" story. It is **unbuilt.** Must not be claimed until built; wire it so it precedes, not replaces, human escalation. |
| **Operating prompt (floor-raiser)** | A per-role operating prompt (`standards/OPERATING.md`) that raises a cheap engine's completeness/discipline. | ⚪ | Empirical basis: prompt raised Haiku's output 2,956→30,390 chars but did **not** close the judgment gap (still lost 3–0). "The prompt raises the floor; the model sets the ceiling." |
| **Minimum-tier requirement** | A role can require a tier (Quench: judgment). Role constrains engine — the one sanctioned place the layers touch. | 🟡 | Correct framing per the invariant; enforce it so a mis-config can't staff a judgment seat with a cheap engine. |

---

## L3 — Memory & learning (evidence that compounds)

The one asset that appreciates with use and can't be cloned — *your* projects' scar tissue.

| Feature | What it does | Status | Review note |
|---|---|---|---|
| **Traces** | One JSONL per run (run_start → … → run_end); drives the ceiling. No evidence = didn't happen. | 🟢 | Powers Ledger + the Run Recorder + L4 provenance. |
| **Shared memory** | SQLite + FTS5, untrusted-data by rule (no secrets/PII, source required). | 🟢 | 17 tests. |
| **Postmortem → eval loop** | An incident becomes a regression eval; recurring lessons get promoted. | 🟡 | Memory + eval tasks exist; the automated capture→promote loop and running the evals is not wired (`/temper` has no scorecard data yet). Best single feature — cures the recurring-bug cycle. |
| **Scar-tissue graph** | Lessons linked to the files/patterns they touch; recurring weakness lights up as a hub. | 🟣 | Design preview (memory-as-graph). |
| **Drift sentinel** | Re-pins plan + standards after every context compaction (`SessionStart source=compact`); watches scope drift vs the captured plan; feeds the loop-discipline ladder. | ⚪ | **Third build item.** Answers "quality loss in long sessions." Deterministic sensors (compaction count, files-vs-plan, thrash ratio) + rare judgment-tier checkpoints. |

---

## L4 — Certification ("Forge Verified" — the public proof & growth loop)

The distribution mechanism: every certified app carries a badge that links back to Forge. **Certifies
verifiable claims, never "secure."** Machine-verified lines are separate from AI-reviewed scores.

| Level | Claim | Evidence | Status |
|---|---|---|---|
| **L1 — Gated** | Enforcement is armed (pre-push, CI, pre-commit). | `forge_certify` | 🟢 built |
| **L2 — Verified** | All endpoint checks green at this commit (secrets clean in scanned history, CI green, 0 known CVEs, self-audit intact). | `forge_certify` + collector | 🟢 built |
| **L3 — Provenanced** | Every change went plan → guarded build → review → gate. | the trace history | ⚪ (needs governed-run history) |

> **Built 2026-07-17:** `status/forge_certify.py` + `/forge-certify`. Real: FornaxOS certifies **L2**, Forge itself **L1** (no CI run yet). L3 honestly gated on `traces/` governed-run history (0 today). Machine-verified claims only, never "secure".

**Design rules (from the research + findings):**
- Endpoint badges are a crowded market (Sonar AI Code Assurance, etc.) — **L3 process-provenance is the empty, defensible niche.** Differentiator vs Entire (well-funded, records the trail): they record what the agent *did*; Forge enforces what it *must* do — "could not have done otherwise" is the stronger basis.
- Checks run in **CI**, not on the dev's laptop, tied to the commit SHA (self-certification is weak).
- Never claim "secure." Scope every claim (e.g. "0 secrets in the scanned history," not "anywhere").
- Window is narrow; L3 depends on L1/L2 loop + plan-capture being *real* — you can't certify a process whose loop cap is a polite request.

---

## L5 — Surfaces (how a human sees & configures it)

Same truth, two literacies. Simple is a **translation** of Advanced, not a curtain — every plain line
maps to a metric and its trace evidence.

| Surface | For whom | What it shows | Status |
|---|---|---|---|
| **Simple dashboard** | any user (incl. non-technical) | plain-language status, "what Forge did for you," your certificate + copy-badge | 🟣 |
| **Advanced / Mission Control** | power user | fleet of concurrent runs, attention-sorted (NEEDS YOU → WATCH → RUNNING → DONE), session integrity, spend | 🟣 |
| **Run Recorder** | post-mortem | a run as a graph; thrash shows as a visible loop; timeline playback | 🟣 |
| **Team page** | anyone | the roster, permissions, this-week stats, "hiring" (roadmap as colleagues) | 🟣 |
| **Configure** | owner | protection mode (Strict/Balanced/Ramp-up), guard tester, loop/budget, **roles (L1) and engines (L2) as separate cards**, gates (status not switches), certificate level, danger-zone pause (loud, traced) | 🟣 |

> **Review note (surfaces):** all L5 items are **design previews with representative data.** The
> consistency audit found storyboard drift between them (one run with two endings; token totals labeled
> "week" vs "today"; planned-feature metrics shown without a planned tag). None ship; all fixable. When
> any surface becomes real, it renders from `.forge/` state + `traces/*.jsonl` — and must carry the same
> honest-status tags as this spec.

---

## Build order (scope freeze — turns 🟡/⚪ into 🟢)

1. **Commit the current checkpoint** (7 days of work uncommitted — the only irreversible risk).
2. **Fix the self-audit (L0)** — verify the guard that *runs*, behavior-test the ceiling, match resolved paths; add the 6 missing tamper tests. Then correct PROOF.md §2 / README claims.
3. **Loop-cap enforcement (L0)** — move the 3-iteration cap from prose to the hook (defends the thesis; unblocks the Recorder's real data).
4. **Plan capture (L1)** — persist approved plans; unblocks drift + L4 provenance.
5. **Drift sentinel (L3)** — compaction re-pin + scope-drift sensors.
6. **Engine tiering + auto-escalation (L2)** — dynamic staffing with the invariant enforced.
7. **`forge certify` L1/L2 (L4)** — assemble existing signals into a claim manifest; CI-published.
8. **Surfaces (L5)** — build the real dashboard over live state, one canonical story; L3 provenance + Mission Control follow demand.

## Two invariants that bind everything above
- **Layer separation:** escalation swaps engines, never roles; never widens permissions. (L1 ⟂ L2.)
- **Honest claims:** a page/doc never says more than the code does. Machine-verified ≠ AI-reviewed;
  scope every claim; label planned/preview. The self-audit and certification exist to make this
  checkable — so they, above all, must not overclaim.
