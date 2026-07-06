---
description: Run the FORGE pipeline with triage, loop discipline, tracing and checkpoints.
---
Execute for task: $ARGUMENTS

1. TRACE: create traces/runs/<date>-<slug>.jsonl; log run_start (task, git ref).
2. TRIAGE per CLAUDE.md; log the choice + reason. When in doubt, go heavier.
3. MEMORY: forge_memory.py search on the task topic; feed hits to the next steps.
4. SMALL: checkpoint → Smith → layer 0 → Quench.
   MEDIUM: Anvil plan → checkpoint → Smith → layer 0 → Quench.
   LARGE: Anvil best-of-2 → Quench selects → HUMAN approves → checkpoint
          (separate worktree if parallel work is possible) → Smith → layer 0 → Quench.
5. LOOP: on BLOCKER → attribution (PLAN|CONTEXT|TOOL|CAPABILITY, log it) →
   fix via Smith (max 3 iterations) → repeated identical finding or 3 misses →
   Anvil replan (max 1) → human. Hard stop: >40 tool calls or >6 iterations.
6. GREEN: Bellows if coverage dropped; Ledger for docs + commit message.
7. TRACE: log run_end (iterations, findings, tokens est., outcome); one-line
   summary to forge_memory if a durable lesson emerged.
Never bypass a veto. Never continue past the hard stop.
