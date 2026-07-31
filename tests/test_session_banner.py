"""Tests for hooks/session_banner.py — the truthful SessionStart banner."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parent.parent / "hooks" / "session_banner.py"
_spec = importlib.util.spec_from_file_location("session_banner", _P)
assert _spec and _spec.loader
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)

_ROOT = Path(__file__).resolve().parent.parent  # the real Forge repo


def test_guard_wired_true_on_real_repo():
    # the shipped hooks.json wires guard.py on a Bash-covering PreToolUse entry
    assert sb.guard_wired(str(_ROOT)) is True


def test_guard_wired_false_when_no_pretooluse(tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"PreToolUse": []}})
    )
    assert sb.guard_wired(str(tmp_path)) is False


def test_guard_wired_false_when_guard_missing(tmp_path):
    # a PreToolUse entry that covers Bash but wires something other than guard.py
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "python3 decoy.py"}
                            ],
                        }
                    ]
                }
            }
        )
    )
    assert sb.guard_wired(str(tmp_path)) is False


def test_guard_wired_false_on_missing_or_corrupt(tmp_path):
    assert sb.guard_wired(str(tmp_path)) is False  # no hooks.json
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text("{not json")
    assert sb.guard_wired(str(tmp_path)) is False  # corrupt → conservative False


def test_main_never_blocks_and_prints_armed(monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_ROOT))
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session":"x"}'))
    assert sb.main() == 0
    err = capsys.readouterr().err
    assert "FORGE active" in err and "armed" in err


def test_main_warns_when_unwired(monkeypatch, capsys, tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text(
        json.dumps({"hooks": {"PreToolUse": []}})
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert sb.main() == 0
    assert "NOT wired" in capsys.readouterr().err


@pytest.mark.parametrize("bad_stdin", ["", "not json", '{"a":1}'])
def test_main_tolerates_any_stdin(monkeypatch, bad_stdin):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_ROOT))
    monkeypatch.setattr("sys.stdin", io.StringIO(bad_stdin))
    assert sb.main() == 0  # a banner must never wedge startup


# --- 2026-07-30 FIELD RCA: the auto-arm permanently wedged a user -------------
# Launched from $HOME, it armed an ad-hoc run that no task boundary ever closed, so one
# counter accumulated across every session until it crossed the ceiling and halted them
# all. Three rules, each regression-tested.


def _proj(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path / ".forge"


def test_rule1_never_arms_outside_a_project(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / ".forge"))  # no .git alongside
    assert sb.arm_session_run() == "skipped"
    assert not (tmp_path / ".forge" / "active_run.json").exists()


def test_rule1_never_arms_in_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / ".forge"))
    assert sb.arm_session_run() == "skipped"


def test_rule2_new_session_resets_the_adhoc_counter(tmp_path, monkeypatch):
    home = _proj(tmp_path)
    monkeypatch.setenv("FORGE_HOME", str(home))
    assert sb.arm_session_run() == "armed"
    run = json.loads((home / "active_run.json").read_text())
    run["tool_calls"] = 499
    (home / "active_run.json").write_text(json.dumps(run))
    assert sb.arm_session_run() == "armed"  # replaced, not reused
    assert json.loads((home / "active_run.json").read_text())["tool_calls"] == 0


def test_rule2_real_forge_run_is_never_clobbered(tmp_path, monkeypatch):
    home = _proj(tmp_path)
    home.mkdir(parents=True, exist_ok=True)
    (home / "active_run.json").write_text(
        json.dumps({"run_id": "real", "path": "x", "started_at": 1e9, "tool_calls": 7})
    )
    monkeypatch.setenv("FORGE_HOME", str(home))
    assert sb.arm_session_run() == "existing"
    kept = json.loads((home / "active_run.json").read_text())
    assert kept["run_id"] == "real" and kept["tool_calls"] == 7


def test_rule3_adhoc_ceiling_is_a_backstop_not_a_budget(tmp_path, monkeypatch):
    home = _proj(tmp_path)
    monkeypatch.setenv("FORGE_HOME", str(home))
    sb.arm_session_run()
    assert json.loads((home / "active_run.json").read_text())["ceiling"] == 500
