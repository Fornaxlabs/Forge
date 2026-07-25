"""Tests for traces/forge_trace.py — run lifecycle + JSONL events."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_P = Path(__file__).resolve().parent.parent / "traces" / "forge_trace.py"
_spec = importlib.util.spec_from_file_location("forge_trace", _P)
assert _spec and _spec.loader
ft = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ft)

T0 = 1_700_000_000.0  # fixed epoch for deterministic ts/run_id


def _lines(home: Path):
    (run,) = list((home / "runs").glob("*.jsonl"))
    return [json.loads(x) for x in run.read_text().splitlines()]


def test_full_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    assert ft.main(["start", "--task", "add auth", "--triage", "LARGE",
                    "--git-ref", "abc123"], now=T0) == 0
    assert (tmp_path / "active_run.json").exists()
    assert ft.main(["log", "--event", "review",
                    "--json", '{"iteration": 1, "findings": []}'], now=T0) == 0
    assert ft.main(["end", "--outcome", "green", "--iterations", "2"], now=T0) == 0
    # active run cleared on end
    assert not (tmp_path / "active_run.json").exists()

    events = _lines(tmp_path)
    assert events[0]["event"] == "run_start"
    assert events[0]["triage"] == "LARGE"
    # run_id now carries HHMMSS (collision guard): YYYY-MM-DD-HHMMSS-slug
    assert events[0]["run_id"] == "2023-11-14-221320-add-auth"
    assert events[1]["event"] == "review"
    assert events[-1]["event"] == "run_end"
    assert events[-1]["outcome"] == "green"
    # every event carries ts + run_id + event
    for e in events:
        assert {"ts", "run_id", "event"} <= set(e)


def test_start_writes_ceiling_into_active(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL",
             "--git-ref", "r", "--ceiling", "12"], now=T0)
    active = json.loads((tmp_path / "active_run.json").read_text())
    assert active["ceiling"] == 12
    assert active["tool_calls"] == 0


def test_log_without_active_run_returns_1(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    assert ft.main(["log", "--event", "x"], now=T0) == 1


def test_slug_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    rid = ft.start(task="a very long task description that would be truncated",
                   triage="MEDIUM", git_ref="r", ceiling=40, slug="short", now=T0)
    assert rid == "2023-11-14-221320-short"


def test_log_rejects_non_object_json(tmp_path, monkeypatch):
    # regression: --json '[1,2]' / '5' used to crash log() with an uncaught TypeError
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    assert ft.main(["log", "--event", "x", "--json", "[1,2]"], now=T0) == 1
    assert ft.main(["log", "--event", "x", "--json", "5"], now=T0) == 1


def test_record_blocker_increments_and_enforces(tmp_path, monkeypatch):
    import json as _j
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.start(task="add refund", triage="MEDIUM", git_ref="HEAD", ceiling=40, slug="r", now=1000.0)
    assert ft.record_blocker("authz", now=1001.0) == 1
    assert ft.record_blocker("authz", now=1002.0) == 2
    assert ft.record_blocker("other", now=1003.0) == 1
    run = _j.loads((tmp_path / "active_run.json").read_text())
    assert run["blockers"] == {"authz": 2, "other": 1}
    assert run["iterations"] == 3


# --- 2026-07-20: scope declaration (assumption guard, build-time) ---

def test_start_persists_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r",
             "--scope", "hooks/*, tests/test_guard.py"], now=T0)
    active = json.loads((tmp_path / "active_run.json").read_text())
    assert active["scope"] == ["hooks/*", "tests/test_guard.py"]
    assert _lines(tmp_path)[0]["scope"] == ["hooks/*", "tests/test_guard.py"]


def test_scope_add_widens_and_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r",
             "--scope", "hooks/*"], now=T0)
    assert ft.main(["scope", "--add", "traces/*"], now=T0) == 0
    active = json.loads((tmp_path / "active_run.json").read_text())
    assert active["scope"] == ["hooks/*", "traces/*"]
    assert _lines(tmp_path)[-1]["event"] == "scope"


def test_scope_set_replaces(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r",
             "--scope", "hooks/*"], now=T0)
    ft.main(["scope", "--set", "docs/*"], now=T0)
    assert json.loads((tmp_path / "active_run.json").read_text())["scope"] == ["docs/*"]


def test_scope_add_dedupes(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r",
             "--scope", "hooks/*"], now=T0)
    ft.main(["scope", "--add", "hooks/*"], now=T0)
    assert json.loads((tmp_path / "active_run.json").read_text())["scope"] == ["hooks/*"]


# --- 2026-07-20: definition-of-done gate — success requires verification ---

def test_end_success_without_verification_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    # no verify/test/review event logged → cannot claim success
    assert ft.main(["end", "--outcome", "done"], now=T0) == 1
    assert (tmp_path / "active_run.json").exists()  # run NOT closed


def test_end_success_with_verification_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    ft.main(["log", "--event", "verify", "--json", '{"passed": true}'], now=T0)
    assert ft.main(["end", "--outcome", "done"], now=T0) == 0
    assert not (tmp_path / "active_run.json").exists()


def test_end_green_requires_verification(tmp_path, monkeypatch):
    # Forge's own success word must be gated too
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    assert ft.main(["end", "--outcome", "green"], now=T0) == 1


def test_end_failed_verify_event_does_not_count(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    ft.main(["log", "--event", "test", "--json", '{"passed": false}'], now=T0)
    assert ft.main(["end", "--outcome", "success"], now=T0) == 1  # a failed check is not proof


def test_end_non_success_outcome_not_gated(tmp_path, monkeypatch):
    # 'escalated'/'abandoned' don't claim success → no verification required
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    assert ft.main(["end", "--outcome", "escalated"], now=T0) == 0


def test_end_force_overrides_but_logs_assumption(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ft.main(["start", "--task", "t", "--triage", "SMALL", "--git-ref", "r"], now=T0)
    assert ft.main(["end", "--outcome", "done", "--force", "--note", "hotfix"], now=T0) == 0
    events = _lines(tmp_path)
    assert any(e["event"] == "unverified_close" and e["note"] == "hotfix" for e in events)
    assert events[-1]["event"] == "run_end"
