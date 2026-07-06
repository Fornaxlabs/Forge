# PYTHON — language standards

- MUST: manage the project with uv (uv.lock committed).
- MUST: lint and format with ruff (ruff check + ruff format).
- MUST: type-check with mypy --strict; no untyped public API.
- MUST: test with pytest.
- MUST: type hints on every public function/method signature.
- NEVER: introduce a dependency without pinning it and running pip-audit.
- NEVER: use bare `except:`; catch specific exceptions.
