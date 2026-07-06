# ENGINEERING — Python · FastAPI · Git · Testing (folded)

## Python
- MUST: uv-managed (uv.lock committed) · ruff (check + format) · mypy --strict · pytest.
- MUST: type hints on every public signature. NEVER: bare `except:`.

## FastAPI
- MUST: Pydantic v2 I/O with `response_model` on every route.
- MUST: DI for auth/DB/settings · OAuth2/JWT short expiry + refresh · rate-limit auth routes.
- MUST: RFC 9457 problem+json errors (no stack traces external) · explicit CORS · /v1 versioning.
- NEVER: return ORM models directly; serialize through a response_model.

## Git
- MUST: at project start create a PRIVATE GitHub repo before real work.
- MUST: Conventional Commits · feature branches · PR required · atomic commits.
- NEVER: force-push a shared branch · commit secrets/.env/artifacts.

## Testing
- MUST: pyramid (many unit, fewer integration, few e2e) · unit+integration per feature.
- MUST: coverage ≥80% in CI (fail below) · assert behavior, not implementation/timing.
- NEVER: weaken an assertion to pass · leave a flaky test (fix or remove).
