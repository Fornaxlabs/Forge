"""Tests for the guard's harness adapter layer (multi-harness, 2026-07-18).

Covers the translation boundary only — no external harness is required:
- _extract() normalizes each documented harness payload shape;
- exit-2 mode (the default): denied command -> exit 2 + stderr, safe -> 0;
- json mode (FORGE_BLOCK_MODE=json or --mode json): denied -> deny-JSON on
  stdout, allow -> silent exit 0;
- forge-init --harness stamps the matching adapter config with the plugin
  path substituted (and default/claude behavior is unchanged).
"""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import time
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"
_spec = importlib.util.spec_from_file_location("guard_harness", _P)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

_INIT = Path(__file__).resolve().parent.parent / "scripts" / "forge-init.sh"
_PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent)


# --- _extract: one payload shape per documented harness ---------------------

@pytest.mark.parametrize("payload,expect", [
    # Claude Code (native; also Codex CLI, AWS Kiro, Cline — same shape)
    ({"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "agent_id": "a1"},
     {"command": "ls -la", "tool_name": "Bash", "agent_id": "a1"}),
    # Gemini CLI / camelCase harnesses
    ({"toolName": "run_shell_command", "toolInput": {"command": "git status"}, "agentId": "g7"},
     {"command": "git status", "tool_name": "run_shell_command", "agent_id": "g7"}),
    # params-style nesting
    ({"tool": "shell", "params": {"command": "make build"}},
     {"command": "make build", "tool_name": "shell", "agent_id": ""}),
    # arguments-style nesting
    ({"arguments": {"command": "pytest -q"}, "tool": "bash"},
     {"command": "pytest -q", "tool_name": "bash", "agent_id": ""}),
    # bare top-level command (last resort)
    ({"command": "echo hi"},
     {"command": "echo hi", "tool_name": "", "agent_id": ""}),
    # agent field variant
    ({"tool_input": {"command": "ls"}, "agent": "sub-2"},
     {"command": "ls", "tool_name": "", "agent_id": "sub-2"}),
])
def test_extract_known_shapes(payload, expect):
    assert guard._extract(payload) == expect


@pytest.mark.parametrize("payload", [
    {},                                          # nothing at all
    {"tool_input": "not-a-dict"},                # container is not a dict
    {"tool_input": {"command": 5}},              # command is not a string
    {"tool_input": {"file_path": "x.py"}},       # non-command tool (Edit/Write)
    {"tool_name": 7, "agent_id": None},          # foreign types everywhere
])
def test_extract_degrades_to_empty(payload):
    assert guard._extract(payload)["command"] == ""


def test_extract_nested_container_wins_over_bare_command():
    got = guard._extract({"tool_input": {"command": "inner"}, "command": "outer"})
    assert got["command"] == "inner"


# --- exit-2 mode (default): the Claude Code contract, for every shape -------

def _main(monkeypatch, payload: str, argv: list[str] | None = None) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    monkeypatch.setattr("sys.argv", ["guard.py"] + (argv or []))
    return guard.main()


@pytest.mark.parametrize("payload", [
    {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},          # CC/Codex/Kiro/Cline
    {"toolName": "run_shell_command", "toolInput": {"command": "rm -rf /"}},  # Gemini
    {"tool": "shell", "params": {"command": "rm -rf /"}},
    {"arguments": {"command": "rm -rf /"}},
    {"command": "rm -rf /"},
])
def test_denied_exits_2_for_every_shape(monkeypatch, capsys, payload):
    monkeypatch.delenv("FORGE_BLOCK_MODE", raising=False)
    assert _main(monkeypatch, json.dumps(payload)) == 2
    captured = capsys.readouterr()
    assert "destructive command blocked" in captured.err
    assert captured.out == ""  # exit-2 mode never writes stdout


@pytest.mark.parametrize("payload", [
    {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
    {"toolName": "run_shell_command", "toolInput": {"command": "git status"}},
    {"command": "pytest -q"},
])
def test_safe_allows_for_every_shape(monkeypatch, payload):
    monkeypatch.delenv("FORGE_BLOCK_MODE", raising=False)
    assert _main(monkeypatch, json.dumps(payload)) == 0


# --- json mode: deny-JSON on stdout, exit 0 ---------------------------------

def _deny_json(capsys) -> dict:
    out = capsys.readouterr().out
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    return decision


def test_json_mode_denied_emits_deny_json(monkeypatch, capsys):
    monkeypatch.setenv("FORGE_BLOCK_MODE", "json")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert _main(monkeypatch, payload) == 0  # decision travels in stdout, not exit code
    decision = _deny_json(capsys)
    assert decision["permissionDecision"] == "deny"
    assert "destructive command blocked" in decision["permissionDecisionReason"]


def test_json_mode_safe_is_silent_allow(monkeypatch, capsys):
    monkeypatch.setenv("FORGE_BLOCK_MODE", "json")
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert _main(monkeypatch, payload) == 0
    assert capsys.readouterr().out == ""  # no decision object -> harness default allow


def test_mode_flag_selects_json(monkeypatch, capsys):
    monkeypatch.delenv("FORGE_BLOCK_MODE", raising=False)
    payload = json.dumps({"tool_input": {"command": "rm -rf /"}})
    assert _main(monkeypatch, payload, argv=["--mode", "json"]) == 0
    assert _deny_json(capsys)["permissionDecision"] == "deny"


def test_mode_flag_overrides_env(monkeypatch, capsys):
    monkeypatch.setenv("FORGE_BLOCK_MODE", "exit2")
    payload = json.dumps({"tool_input": {"command": "rm -rf /"}})
    assert _main(monkeypatch, payload, argv=["--mode=json"]) == 0
    assert _deny_json(capsys)["permissionDecision"] == "deny"


def test_unrecognized_mode_falls_back_to_exit2(monkeypatch, capsys):
    # A typo'd mode must never become a way to disable blocking.
    monkeypatch.setenv("FORGE_BLOCK_MODE", "yolo")
    payload = json.dumps({"tool_input": {"command": "rm -rf /"}})
    assert _main(monkeypatch, payload) == 2
    assert capsys.readouterr().out == ""


def test_json_mode_ceiling_breach_emits_deny_json(tmp_path, monkeypatch, capsys):
    home = tmp_path / ".forge"
    home.mkdir()
    (home / "active_run.json").write_text(json.dumps({
        "run_id": "r", "path": "x", "started_at": time.time(),
        "tool_calls": 5, "ceiling": 3,
    }))
    monkeypatch.setenv("FORGE_HOME", str(home))
    monkeypatch.setenv("FORGE_BLOCK_MODE", "json")
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "a.py"}})
    assert _main(monkeypatch, payload) == 0
    assert "ceiling" in _deny_json(capsys)["permissionDecisionReason"]


def test_json_mode_fails_open_on_bad_stdin(monkeypatch, capsys):
    monkeypatch.setenv("FORGE_BLOCK_MODE", "json")
    assert _main(monkeypatch, "not json") == 0
    assert capsys.readouterr().out == ""


# --- Claude Code path regression: decide() ignores mode entirely ------------

def test_decide_is_mode_immune(monkeypatch, capsys):
    # Even with json mode ambient, decide() (the CC entry) still exits 2 + stderr.
    monkeypatch.setenv("FORGE_BLOCK_MODE", "json")
    assert guard.decide({"tool_input": {"command": "rm -rf /"}}) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "destructive command blocked" in captured.err


# --- forge-init --harness ----------------------------------------------------

def _init(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_INIT), *args, str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )


def test_forge_init_harness_codex_stamps_substituted_config(tmp_path):
    result = _init(tmp_path, "--harness", "codex")
    assert result.returncode == 0, result.stderr
    stamped = tmp_path / ".codex" / "hooks.json"
    assert stamped.is_file()
    cfg = json.loads(stamped.read_text())
    command = cfg["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "__FORGE_PLUGIN_ROOT__" not in command       # placeholder substituted
    assert f"{_PLUGIN_ROOT}/hooks/guard.py" in command  # absolute path to THE guard
    assert "NOT yet validated" in result.stdout          # honesty note printed


def test_forge_init_harness_kiro_stamps_hook_file(tmp_path):
    result = _init(tmp_path, "--harness=kiro")
    assert result.returncode == 0, result.stderr
    stamped = tmp_path / ".kiro" / "hooks" / "forge-guard.json"
    assert stamped.is_file()
    assert "__FORGE_PLUGIN_ROOT__" not in stamped.read_text()


def test_forge_init_default_is_claude_and_unchanged(tmp_path):
    result = _init(tmp_path)  # positional-only call, exactly as before the flag
    assert result.returncode == 0, result.stderr
    assert "harness:   claude" in result.stdout
    for leftover in (".codex", ".gemini", ".grok", ".cline", ".kiro", ".agents"):
        assert not (tmp_path / leftover).exists()  # no adapter noise on the default path
    assert (tmp_path / "CLAUDE.md").is_file()      # the classic stamps still land


def test_forge_init_rejects_unknown_harness(tmp_path):
    result = _init(tmp_path, "--harness", "cursor")
    assert result.returncode != 0
    assert "unknown --harness" in result.stderr


def test_forge_init_adapter_stamp_is_idempotent(tmp_path):
    assert _init(tmp_path, "--harness", "codex").returncode == 0
    marker = tmp_path / ".codex" / "hooks.json"
    marker.write_text('{"custom": true}')
    result = _init(tmp_path, "--harness", "codex")  # re-run must not overwrite
    assert result.returncode == 0
    assert json.loads(marker.read_text()) == {"custom": True}
