# How /temper runs the eval set

1. For each task in `evals/tasks/`, run the `/forge` pipeline in a throwaway git
   worktree (isolation — the eval must not touch the real tree).
2. Record per task: which layer caught the planted fault, iteration count, tool
   calls, and outcome.
3. Planted-fault rules:
   - Task 03 (secret) MUST be caught by layer 0 (pre-commit). If Quench catches it
     instead, record "layer 0 leak" as a harness defect.
   - Task 07 (CVE) MUST be caught by CI (pip-audit).
   - Tasks 02/04/08 MUST be caught by Quench.
4. Append a run block to `SCORECARD.md` (harness version, model, date).
5. Compare to the previous run. If the score regressed, recommend reverting the
   change that caused it.
