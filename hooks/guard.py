#!/usr/bin/env python3
"""FORGE PreToolUse guard.

Two enforced controls that used to be mere prose in CLAUDE.md:
1. Deny destructive Bash commands (rm -rf /, force-push, drop table, ...).
2. Enforce the run tool-call ceiling ("noodrem") — but only while a FORGE run is
   active, so it never blocks unrelated sessions.

Exit 2 blocks the tool call. The guard fails OPEN: any internal error returns 0
(allow), so a bug here can never wedge the user's shell. It only ever blocks on a
confirmed match or a confirmed ceiling breach.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

DENY_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"rm\s+-rf\s+--no-preserve-root",
    r"git\s+push\b.*--force",
    r"git\s+push\b.*(\s|^)-f(\s|$)",
    r"\bdrop\s+(table|database)\b",
    r"\btruncate\s+table\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{.*\}\s*;\s*:",  # fork bomb
    r">\s*/dev/sd[a-z]",
    r"chmod\s+-R\s+777\s+/",
]

# Default ceiling; a run may override via active_run.json.
DEFAULT_CEILING = 40
STALE_SECONDS = 6 * 3600  # ignore an active run older than this (crash safety)


def is_denied(command: str) -> bool:
    return any(re.search(p, command, re.I) for p in DENY_PATTERNS)


def _active_run_path() -> str:
    return os.path.join(os.environ.get("FORGE_HOME", ".forge"), "active_run.json")


def tick_and_check(now: float | None = None) -> bool:
    """Increment the active run's tool-call count. Return True iff the ceiling is
    breached. No active run, stale run, or any error → False (never block)."""
    path = _active_run_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path) as fh:
            run = json.load(fh)
    except (OSError, ValueError):
        return False
    started = run.get("started_at", 0)
    now = time.time() if now is None else now
    if not started or (now - started) > STALE_SECONDS:
        return False  # crashed/forgotten run — don't hold the shell hostage
    run["tool_calls"] = int(run.get("tool_calls", 0)) + 1
    ceiling = int(run.get("ceiling", DEFAULT_CEILING))
    try:
        with open(path, "w") as fh:
            json.dump(run, fh)
    except OSError:
        return False
    return run["tool_calls"] > ceiling


def decide(payload: dict) -> int:
    command = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    if command and is_denied(command):
        print("FORGE guard: destructive command blocked", file=sys.stderr)
        return 2
    if tick_and_check():
        print(
            "FORGE guard: tool-call ceiling reached — run halted, escalate to a human",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0  # fail open
    return decide(payload)


if __name__ == "__main__":
    raise SystemExit(main())
