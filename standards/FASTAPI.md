# FASTAPI — API standards

- MUST: Pydantic v2 models for all I/O; declare `response_model` on every route.
- MUST: use dependency injection for auth, DB sessions, and settings.
- MUST: OAuth2/JWT with short-lived access tokens + refresh; rate-limit auth routes.
- MUST: be async-correct — no blocking calls in async paths; run blocking work in a threadpool.
- MUST: return RFC 9457 problem+json for errors; never leak stack traces externally.
- MUST: configure CORS explicitly (no wildcard with credentials); set security headers.
- MUST: version the API under /v1; the OpenAPI schema is the contract.
- NEVER: return ORM models directly; always serialize through a response_model.
- NEVER: put secrets or DB URLs in query params or logs.
