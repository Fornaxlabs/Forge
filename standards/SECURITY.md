# SECURITY — OWASP Top 10 (2025) + ASVS 5.0 + NIST SSDF

- MUST: validate all input server-side (Pydantic models, allowlists over denylists).
- MUST: use exclusively parameterized queries / ORM bindings — never string-built SQL.
- MUST: deny-by-default authorization on every route; authenticate then authorize per resource.
- MUST: keep secrets only in env vars or a secret manager; never in code, config, or logs.
- MUST: use vetted crypto only — Argon2id for password hashing, TLS 1.2+ in transit.
- MUST: pin dependencies; run pip-audit in CI; generate an SBOM (CycloneDX).
- MUST: structured logging without secrets/PII; emit audit events on auth actions.
- MUST: return generic errors externally; keep detail internal (logs/traces only).
- NEVER: roll your own crypto, tokens, or session logic.
- NEVER: trust client-supplied identifiers for authorization decisions.
- NEVER: log request bodies, tokens, or PII.
