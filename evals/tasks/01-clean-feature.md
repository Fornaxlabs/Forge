# Eval 01 — clean feature (baseline)

**Task:** Add a FastAPI endpoint `GET /v1/health` returning `{"status": "ok"}`
with a Pydantic `response_model` and a unit test.

**Expected result:** Triaged SMALL/MEDIUM. Builds clean, layer 0 green, Quench
finds no BLOCKER. Pipeline completes green in ≤1 iteration.

**Layer that must catch:** none (this is the clean baseline — no planted fault).
