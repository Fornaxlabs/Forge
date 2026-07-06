# TESTING — test standards

- MUST: follow the test pyramid — many unit, fewer integration, few e2e.
- MUST: add unit + integration tests for every feature.
- MUST: keep coverage ≥80% in CI (fail the build below it).
- MUST: assert behavior/outcomes, not implementation details.
- NEVER: weaken or delete an assertion to make a test pass.
- NEVER: leave a flaky test — fix it or remove it.
