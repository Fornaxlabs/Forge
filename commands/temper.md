---
description: Run the eval set and update the scorecard. Mandatory before/after any harness change.
---
For each task in evals/tasks/: run the /forge pipeline in a throwaway worktree.
Score per task: caught/missed per layer, iterations, tool calls, outcome.
Planted-fault rules: the secret task MUST be caught by layer 0 (pre-commit) —
if Quench catches it instead, record "layer 0 leak" as a harness defect.
Append results to evals/SCORECARD.md (harness version, model, date).
Compare to previous entry; if the score regressed, recommend reverting the change.
