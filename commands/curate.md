---
description: Monthly hygiene — prune MD files and curate shared memory.
---
1. Review CLAUDE.md + standards/ + agents/: flag redundant, conflicting or
   never-triggered rules (cross-check against recent traces). Propose deletions.
2. forge_memory.py curate: merge duplicates, expire stale entries, verify no
   secrets/PII, ensure every entry still has a source reference.
3. Any rule whose removal would not change eval results is a deletion candidate.
Output: a proposal diff for the human — do not apply destructive changes unasked.
