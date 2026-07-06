---
description: Turn an incident or escaped bug into enforced learning.
---
For incident: $ARGUMENTS
1. Root cause (read relevant traces first).
2. Which layer should have caught this? Layer 0 possible → add hook/CI rule
   (preferred, deterministic). Else → standards/ rule or agent instruction.
3. Add a new eval task that reproduces the failure.
4. Run /temper to prove the lesson is now caught.
5. forge_memory.py add --type postmortem with the distilled lesson.
