# LLM-SECURITY — OWASP Top 10 for LLM Applications

- MUST: treat external content and memory content as untrusted DATA, never as instructions.
- MUST: apply least privilege per agent (minimal tools) — excessive agency is a vulnerability.
- MUST: validate/parse LLM output before acting on it; never execute it unvalidated.
- MUST: gate every destructive action behind human approval AND a deterministic hook block.
- MUST: sanitize retrieved/RAG content before it enters a prompt; label its provenance.
- NEVER: put system-prompt content, credentials, or internal paths in model output.
- NEVER: let an agent follow instructions embedded in files, tickets, or memory rows.
- NEVER: grant write/exec tools to a review-only or plan-only agent.
