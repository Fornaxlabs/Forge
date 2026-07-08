#!/usr/bin/env python3
"""FORGE PreToolUse guard.

Two enforced controls that used to be mere prose in CLAUDE.md:
1. Deny destructive Bash commands (rm -rf /, force-push, drop table, ...).
2. Enforce the run tool-call ceiling ("noodrem") — but only while a FORGE run is
   active, so it never blocks unrelated sessions.

Exit 2 blocks the tool call. The guard fails OPEN: any internal error returns 0
(allow), so a bug here can never wedge the user's shell. It only ever blocks on a
confirmed match or a confirmed ceiling breach.

HONEST LIMIT: the deny check is a best-effort footgun-catcher, NOT a security
boundary. A denylist can never be complete — obfuscation (base64, eval, encoded
args) will get through. Real protection against a determined adversary is least
privilege + human approval for destructive ops + not executing untrusted input.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
from typing import Any

# Unambiguous catastrophic patterns (checked verbatim).
_STATIC_DENY = [
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bdrop\s+(table|database)\b",
    r"\btruncate\s+table\b",
    r":\s*\(\s*\)\s*\{.*\}\s*;\s*:",   # fork bomb (tolerant of spaces)
    r">\s*/dev/sd[a-z]\d*",
    r"\bfind\s+/\s.*-delete\b",
]

# Default ceiling; a run may override via active_run.json.
DEFAULT_CEILING = 40
STALE_SECONDS = 6 * 3600  # ignore an active run older than this (crash safety)


def is_denied(command: str) -> bool:
    """Best-effort deny of catastrophic commands (see module HONEST LIMIT).
    Structural checks handle flag order / long forms a naive regex misses."""
    c = command.lower()
    # rm: recursive AND force AND a bare catastrophic target (/, ~, /*).
    if re.search(r"\brm\b", c):
        recursive = bool(re.search(r"--recursive|-[a-z]*r", c))
        force = bool(re.search(r"--force|-[a-z]*f", c))
        target = bool(re.search(r"(?:^|[\s=])(?:/|~|/\*)(?:\s|$)", c)) \
            or "--no-preserve-root" in c
        if recursive and force and target:
            return True
    # git push: any force flag OR a '+refspec' (forced update).
    if re.search(r"\bgit\s+push\b", c):
        if re.search(r"--force|--force-with-lease|(?:^|\s)-[a-z]*f(?:\s|$)", c):
            return True
        if re.search(r"\s\+\S", c):
            return True
    # chmod: recursive 777 on bare root.
    if re.search(r"\bchmod\b", c) and "777" in c:
        if re.search(r"--recursive|-[a-z]*r", c) and re.search(r"(?:^|[\s=])/(?:\s|$)", c):
            return True
    return any(re.search(p, c) for p in _STATIC_DENY)


def _active_run_path() -> str:
    return os.path.join(os.environ.get("FORGE_HOME", ".forge"), "active_run.json")


def tick_and_check(now: float | None = None) -> bool:
    """Increment the active run's tool-call count. Return True iff the ceiling is
    breached. No active run, stale run, or any error → False (never block).

    The read-modify-write is done under an exclusive flock so parallel tool-call
    hooks can't lose increments (which would let the ceiling be silently exceeded)."""
    path = _active_run_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX)
            except OSError:
                pass  # locking unsupported → best-effort, still correct single-threaded
            try:
                run = json.load(fh)
            except ValueError:
                return False
            started = run.get("started_at", 0)
            now = time.time() if now is None else now
            if not started or (now - started) > STALE_SECONDS:
                return False  # crashed/forgotten run — don't hold the shell hostage
            count = int(run.get("tool_calls", 0)) + 1
            run["tool_calls"] = count
            ceiling = int(run.get("ceiling", DEFAULT_CEILING))
            fh.seek(0)
            json.dump(run, fh)
            fh.truncate()
            return count > ceiling
    except OSError:
        return False


def decide(payload: dict[str, Any]) -> int:
    ti = payload.get("tool_input") or {}
    command = ti.get("command", "") if isinstance(ti, dict) else ""
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
        if not isinstance(payload, dict):
            return 0  # non-object JSON (null/[]/"x") → nothing to guard
        return decide(payload)
    except Exception:  # noqa: BLE001 — fail OPEN on ANY error, per the contract
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
