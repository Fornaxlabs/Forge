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
