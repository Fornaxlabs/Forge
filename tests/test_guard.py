"""Tests for hooks/guard.py — deny patterns + run tool-call ceiling."""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"
_spec = importlib.util.spec_from_file_location("guard", _P)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "sudo rm -rf ~",
    "git push origin main --force",
    "git push -f origin main",
    "DROP TABLE users",
    "truncate table logs",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    "chmod -R 777 /",
    # regression: bypasses found by adversarial testing 2026-07-08
    "rm -fr /",
    "rm -r -f /",
    "rm --recursive --force /",
    "git push origin +main",
    "chmod 777 -R /",
    "rm -rf /*",
])
def test_denied(cmd):
    assert guard.is_denied(cmd) is True


@pytest.mark.parametrize("cmd", [
    "ls -la",
    "git push origin main",
    "rm -rf ./build",
    "pytest -q",
    "python3 manage.py migrate",
])
def test_allowed(cmd):
    assert guard.is_denied(cmd) is False


def test_decide_blocks_destructive():
    assert guard.decide({"tool_input": {"command": "rm -rf /"}}) == 2


def test_decide_allows_safe():
    assert guard.decide({"tool_input": {"command": "ls"}}) == 0


def test_project_deny_extra(tmp_path, monkeypatch):
    # per-project deny extension: core allows it, project deny-extra.txt blocks it
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    assert guard.is_denied("nft flush ruleset") is False  # not in core
    (tmp_path / "deny-extra.txt").write_text(
        "# fornaxos\nnft\\s+flush\\s+ruleset\nsetenforce\\s+0\n"
    )
    assert guard.decide({"tool_input": {"command": "nft flush ruleset"}}) == 2
    assert guard.decide({"tool_input": {"command": "setenforce 0"}}) == 2
    assert guard.decide({"tool_input": {"command": "nft list ruleset"}}) == 0


def test_project_deny_extra_bad_regex_fails_open(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    (tmp_path / "deny-extra.txt").write_text("[unclosed(\nrm\\s+-rf\\s+/tmp/x\n")
    # malformed pattern is skipped; the valid one still works; nothing crashes
    assert guard.decide({"tool_input": {"command": "echo ok"}}) == 0


def test_ceiling_no_active_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    assert guard.tick_and_check() is False  # no active_run.json


def test_ceiling_breach(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    active = tmp_path / "active_run.json"
    active.write_text(json.dumps({
        "run_id": "r", "path": "x", "started_at": time.time(),
        "tool_calls": 2, "ceiling": 3,
    }))
    assert guard.tick_and_check() is False  # 3, not > 3
    assert guard.tick_and_check() is True   # 4 > 3


def test_ceiling_ignores_stale_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    active = tmp_path / "active_run.json"
    active.write_text(json.dumps({
        "run_id": "r", "path": "x",
        "started_at": time.time() - guard.STALE_SECONDS - 10,
        "tool_calls": 999, "ceiling": 1,
    }))
    assert guard.tick_and_check() is False  # stale → never blocks


def test_ceiling_corrupt_file_fails_open(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    (tmp_path / "active_run.json").write_text("{not json")
    assert guard.tick_and_check() is False


def test_main_fails_open_on_bad_stdin(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert guard.main() == 0


@pytest.mark.parametrize("payload", ["null", "[]", '"x"', "5"])
def test_main_fails_open_on_non_dict_json(monkeypatch, payload):
    # regression: valid-but-non-object JSON used to crash decide() with a traceback
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert guard.main() == 0


@pytest.mark.parametrize("cmd", [
    # regression 2026-07-09: tokens from DIFFERENT invocations in a compound line
    # must not combine into a false positive (recursive/force/target scattered).
    "git rm x && chmod -R 755 d && rm -f /tmp/y && ls /",
    "git rm -q leak.py && git init -q --bare /tmp/r.git",
    "rm -rf ./build && cp -r src /tmp/out",
])
def test_compound_no_false_positive(cmd):
    assert guard.is_denied(cmd) is False


@pytest.mark.parametrize("cmd", [
    "cd /tmp && rm -rf /",
    "echo hi; rm -rf ~",
    "true || rm --recursive --force /",
])
def test_compound_real_danger_still_blocked(cmd):
    assert guard.is_denied(cmd) is True


# --- loop-cap enforcement (2026-07-16): guard blocks once a blocker exceeds cap ---

def _active(tmp_path, blockers, cap=3, age=0):
    import time as _t
    home = tmp_path / ".forge"
    home.mkdir(parents=True, exist_ok=True)
    (home / "active_run.json").write_text(json.dumps({
        "run_id": "r", "path": str(home / "runs" / "r.jsonl"),
        "started_at": _t.time() - age, "tool_calls": 0,
        "iteration_cap": cap, "blockers": blockers,
    }))
    return str(home)


def test_iteration_not_breached_under_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", _active(tmp_path, {"authz": 3}))  # 3 == cap, allowed
    assert guard.iteration_breached() is False


def test_iteration_breached_over_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", _active(tmp_path, {"authz": 4}))  # 4 > cap
    assert guard.iteration_breached() is True


def test_decide_blocks_on_loop_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", _active(tmp_path, {"authz": 4}))
    assert guard.decide({"tool_input": {"command": "ls"}}) == 2  # safe cmd, still blocked


def test_stale_run_ignores_blockers(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", _active(tmp_path, {"authz": 9}, age=7 * 3600))
    assert guard.iteration_breached() is False  # stale run never holds the shell hostage


def test_no_active_run_no_breach(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "nope"))
    assert guard.iteration_breached() is False


# --- 2026-07-18: ceiling now counts MUTATING actions, not just Bash ---

def test_ceiling_counts_non_bash_mutating_tool(tmp_path, monkeypatch):
    """An Edit tool call (no shell command) must still tick the ceiling — the gap
    that let subagent/edit-heavy runs blow past the limit uncounted."""
    import time as _t
    home = tmp_path / ".forge"
    home.mkdir(parents=True)
    (home / "active_run.json").write_text(json.dumps({
        "run_id": "r", "path": str(home / "runs" / "r.jsonl"),
        "started_at": _t.time(), "tool_calls": 0, "ceiling": 2,
    }))
    monkeypatch.setenv("FORGE_HOME", str(home))
    edit = {"tool_name": "Edit", "tool_input": {"file_path": "x.py", "old_string": "a", "new_string": "b"}}
    assert guard.decide(edit) == 0   # call 1 (count 1 <= 2)
    assert guard.decide(edit) == 0   # call 2 (count 2 <= 2)
    assert guard.decide(edit) == 2   # call 3 (count 3 > 2) -> blocked, even though it's not Bash


# --- 2026-07-18: run-state anchored to CLAUDE_PROJECT_DIR (CWD-independent) ---

def test_forge_home_resolution(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert guard._forge_home() == ".forge"                          # cwd fallback
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert guard._forge_home() == str(tmp_path / ".forge")          # project anchor
    monkeypatch.setenv("FORGE_HOME", "/explicit")
    assert guard._forge_home() == "/explicit"                       # explicit wins
