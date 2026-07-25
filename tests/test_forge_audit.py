"""Tests for status/forge_audit.py — compliance audit export from traces."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "status" / "forge_audit.py"
_spec = importlib.util.spec_from_file_location("forge_audit", _P)
assert _spec and _spec.loader
fa = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = fa  # register before exec (dataclass + future-annotations)
_spec.loader.exec_module(fa)

T0 = 1_700_000_000.0


def _events(*evs):
    return list(evs)


def _run(**over):
    base = {"ts": "2026-07-24T10:00:00", "run_id": "r1", "event": "run_start",
            "task": "add auth", "triage": "MEDIUM", "git_ref": "abc", "scope": ["app.py"]}
    base.update(over)
    return base


def test_audit_run_none_without_run_start():
    assert fa.audit_run([{"event": "stage"}]) is None


def test_audit_run_extracts_governance_signals():
    evs = _events(
        _run(),
        {"event": "stage", "stage": "PLAN", "status": "done", "approved_by": "human"},
        {"event": "scope", "added": ["x.py"]},
        {"event": "blocker", "blocker_id": "authz"},
        {"event": "research", "claim": "c"},
        {"event": "verify", "passed": True},
        {"ts": "2026-07-24T10:05:00", "event": "run_end", "outcome": "green"},
    )
    r = fa.audit_run(evs)
    assert r is not None
    assert r.human_approved and r.verified and r.completed
    assert r.scope_changes == 1 and r.review_blockers == 1 and r.researched == 1
    assert r.outcome == "green"


def test_effective_tier_reflects_retriage():
    evs = _events(_run(triage="MEDIUM"),
                  {"event": "retriage", "from": "MEDIUM", "to": "LARGE"},
                  {"event": "verify", "passed": True},
                  {"event": "run_end", "outcome": "green"})
    r = fa.audit_run(evs)
    assert r is not None
    assert r.triage == "LARGE"          # effective, not initial
    assert r.retriaged is True


def test_forced_close_is_not_verified():
    evs = _events(_run(),
                  {"event": "verify", "passed": True},
                  {"event": "unverified_close", "outcome": "green", "note": "hotfix"},
                  {"event": "run_end", "outcome": "green"})
    r = fa.audit_run(evs)
    assert r is not None
    assert r.forced_close is True
    assert r.verified is False          # a forced close never counts as verified


def test_verified_requires_verify_event_and_no_force():
    r = fa.audit_run(_events(_run(), {"event": "run_end", "outcome": "green"}))
    assert r is not None and r.verified is False   # no verify event


def test_collect_and_summarize(tmp_path):
    runs_dir = tmp_path / ".forge" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "a.jsonl").write_text("\n".join(json.dumps(e) for e in _events(
        _run(run_id="a"),
        {"event": "stage", "approved_by": "human"},
        {"event": "verify", "passed": True},
        {"event": "run_end", "outcome": "green"},
    )))
    (runs_dir / "b.jsonl").write_text("\n".join(json.dumps(e) for e in _events(
        _run(run_id="b", triage="LARGE"),
        {"event": "run_end", "outcome": "abandoned"},
    )))
    runs = fa.collect(str(runs_dir))
    assert len(runs) == 2
    s = fa.summarize(runs)
    assert s["runs"] == 2 and s["human_approved"] == 1 and s["verified_closes"] == 1
    assert s["large_tier"] == 1


def test_read_events_skips_garbage(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text('{"event":"run_start","run_id":"r"}\n{bad json\n\n[1,2]\n')
    evs = fa._read_events(str(f))
    assert len(evs) == 1 and evs[0]["event"] == "run_start"


def test_main_markdown_and_json(tmp_path, capsys, monkeypatch):
    runs_dir = tmp_path / ".forge" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "a.jsonl").write_text("\n".join(json.dumps(e) for e in _events(
        _run(run_id="a"), {"event": "verify"}, {"event": "run_end", "outcome": "green"})))
    assert fa.main([str(tmp_path)], now=T0) == 0
    assert "FORGE governance audit" in capsys.readouterr().out
    assert fa.main([str(tmp_path), "--json"], now=T0) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["runs"] == 1 and data["runs"][0]["run_id"] == "a"


def test_main_out_file(tmp_path):
    (tmp_path / ".forge" / "runs").mkdir(parents=True)
    out = tmp_path / "audit.md"
    assert fa.main([str(tmp_path), "--out", str(out)], now=T0) == 0
    assert out.exists() and "FORGE governance audit" in out.read_text()
