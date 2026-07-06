---
description: Run the FORGE pipeline with triage, loop discipline, tracing and checkpoints.
---
Execute for task: $ARGUMENTS

1. TRACE: create traces/runs/<date>-<slug>.jsonl; log run_start (task, git ref).
2. TRIAGE per CLAUDE.md; log the choice + reason. When in doubt, go heavier.
3. MEMORY: forge_memory.py search on the task topic; feed hits to the next steps.
   The single `reviewer` agent wears the PLAN / BUILD / REVIEW hat per step.
4. SMALL: checkpoint → reviewer builds → layer 0 → reviewer reviews.
   MEDIUM: reviewer plan → checkpoint → build → layer 0 → review.
   LARGE: reviewer best-of-2 plan → HUMAN approves → checkpoint
          (separate worktree if parallel work is possible) → build → layer 0 → review.
5. LOOP: on BLOCKER → attribution (PLAN|CONTEXT|TOOL|CAPABILITY, log it) →
   reviewer fixes (max 3 iterations) → repeated identical finding or 3 misses →
   reviewer replans (max 1) → human. Hard stop: >40 tool calls or >6 iterations.
6. GREEN: reviewer adds missing tests if coverage dropped, updates docs, and
   writes a Conventional Commit message.
7. TRACE: log run_end (iterations, findings, tokens est., outcome); one-line
   summary to forge_memory if a durable lesson emerged.
Never bypass a veto. Never continue past the hard stop.
