#!/usr/bin/env python3
"""FORGE PreToolUse guard.

Three enforced controls that used to be mere prose in CLAUDE.md:
1. Deny destructive Bash commands (rm -rf /, force-push, drop table, ...).
2. Enforce the run tool-call ceiling — counts MUTATING actions (Bash/Edit/Write/
   MultiEdit/NotebookEdit; see hooks.json matcher), not reads, and only while a
   FORGE run is active, so it never blocks unrelated sessions.
3. Enforce the loop cap (same blocker exceeded its iteration limit → block + escalate).

Exit 2 blocks the tool call. The guard fails OPEN: any internal error returns 0
(allow), so a bug here can never wedge the user's shell. It only ever blocks on a
confirmed match or a confirmed ceiling/loop breach.

HONEST LIMIT 1 — deny is a footgun-catcher, NOT a security boundary: a denylist can
never be complete (base64/eval/encoded args get through). Real protection = least
privilege + human approval for destructive ops + not executing untrusted input.

RUN-WIDE ENFORCEMENT (2026-07-18, empirically verified): the ceiling + loop cap span
the WHOLE fleet — main agent AND subagents. Two verified facts make this work:
(a) a subagent's tool calls DO fire this same PreToolUse hook, carrying agent_id; and
(b) anchoring active_run.json to $CLAUDE_PROJECT_DIR/.forge (see _forge_home) gives the
main agent and every subagent ONE shared counter, regardless of each tool's cwd.
Validated end-to-end: with ceiling=3, a subagent's 4th run-wide call was blocked
(exit 2). The earlier 118-vs-40 miss was NOT subagent bypass — it was the old
cwd-relative counter, so agents running in different dirs didn't share state. Fixed.

REMAINING BOUND — only tool calls that fire this hook are counted: the mutating tools
in hooks.json's matcher (Bash/Edit/Write/MultiEdit/NotebookEdit), not reads. Claude
Code's 200-subagent/session hard cap (CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION) backstops
runaway fan-out.
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
# Loop discipline: max review iterations on the SAME blocker before a human must
# take over. Enforced here (not just prose): once the reviewer has recorded a
# blocker this many times (via `forge_trace blocker --id`), the next tool call in
# the run is blocked. A run may override via active_run.json ("iteration_cap").
DEFAULT_ITERATION_CAP = 3
STALE_SECONDS = 6 * 3600  # ignore an active run older than this (crash safety)


# Shell separators — split a compound line into individual command invocations so
# tokens from DIFFERENT commands aren't combined into a false positive (e.g.
# `git rm x && git init --bare /r` must not read as an `rm --recursive ... /`).
_SEP = re.compile(r"&&|\|\||[;\n|]")


def _segment_denied(seg: str) -> bool:
    """Multi-condition structural checks, evaluated within ONE command invocation."""
    # rm: recursive AND force AND a bare catastrophic target (/, ~, /*).
    if re.search(r"\brm\b", seg):
        recursive = bool(re.search(r"--recursive|-[a-z]*r", seg))
        force = bool(re.search(r"--force|-[a-z]*f", seg))
        target = bool(re.search(r"(?:^|[\s=])(?:/|~|/\*)(?:\s|$)", seg)) \
            or "--no-preserve-root" in seg
        if recursive and force and target:
            return True
    # git push: any force flag OR a '+refspec' (forced update).
    if re.search(r"\bgit\s+push\b", seg):
        if re.search(r"--force|--force-with-lease|(?:^|\s)-[a-z]*f(?:\s|$)", seg):
            return True
        if re.search(r"\s\+\S", seg):
            return True
    # chmod: recursive 777 on bare root.
    if re.search(r"\bchmod\b", seg) and "777" in seg:
        if re.search(r"--recursive|-[a-z]*r", seg) and re.search(r"(?:^|[\s=])/(?:\s|$)", seg):
            return True
    return False


def is_denied(command: str) -> bool:
    """Best-effort deny of catastrophic commands (see module HONEST LIMIT).
    Multi-condition checks run PER invocation (split on shell separators); the
    single-pattern static + project lists match anywhere on the line."""
    c = command.lower()
    if any(_segment_denied(seg) for seg in _SEP.split(c)):
        return True
    if any(re.search(p, c) for p in _STATIC_DENY):
        return True
    for pat in _extra_patterns():  # project-specific extensions
        try:
            if re.search(pat, c, re.I):
                return True
        except re.error:
            continue  # a malformed project pattern must never wedge the guard
    return False


def _forge_home() -> str:
    """Resolve the .forge dir INDEPENDENTLY of the tool's working directory.

    Empirically (verified 2026-07-18) a subagent's tool calls fire this same hook and
    every hook invocation — main agent and every subagent — receives the same
    CLAUDE_PROJECT_DIR. Anchoring here means all of them read/write the SAME
    active_run.json, so the ceiling + loop cap count RUN-WIDE (the whole fleet), not
    per-cwd. Precedence: explicit FORGE_HOME > $CLAUDE_PROJECT_DIR/.forge > ./.forge.
    (The old cwd-relative default silently no-op'd enforcement whenever a tool ran
    from a directory other than the one the run was started in — the 118-vs-40 bug.)"""
    home = os.environ.get("FORGE_HOME")
    if home:
        return home
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        return os.path.join(proj, ".forge")
    return ".forge"


def _active_run_path() -> str:
    return os.path.join(_forge_home(), "active_run.json")


def _extra_patterns() -> list[str]:
    """Project-specific deny regexes from ${forge-home}/deny-extra.txt (one per line,
    '#' comments allowed). Lets a project extend the deny-list WITHOUT forking the
    shared plugin — e.g. FornaxOS adds nft/ip/rpm-ostree lockout patterns here."""
    path = os.path.join(_forge_home(), "deny-extra.txt")
    try:
        with open(path) as fh:
            return [
                ln.strip() for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")
            ]
    except OSError:
        return []


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


def iteration_breached(now: float | None = None) -> bool:
    """True iff the active run has hit the same blocker more than the iteration cap.
    Read-only (never mutates the run file). No active/stale run, or any error → False,
    so this can never wedge an unrelated shell — same fail-open contract as the ceiling."""
    path = _active_run_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path) as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_SH)  # shared read lock: never read a torn write
            except OSError:
                pass
            run = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(run, dict):
        return False
    started = run.get("started_at", 0)
    now = time.time() if now is None else now
    if not started or (now - started) > STALE_SECONDS:
        return False
    cap = int(run.get("iteration_cap", DEFAULT_ITERATION_CAP))
    blockers = run.get("blockers", {})
    if not isinstance(blockers, dict):
        return False
    try:
        return any(int(v) > cap for v in blockers.values())
    except (TypeError, ValueError):
        return False


def decide(payload: dict[str, Any]) -> int:
    ti = payload.get("tool_input") or {}
    command = ti.get("command", "") if isinstance(ti, dict) else ""
    if command and is_denied(command):
        print("FORGE guard: destructive command blocked", file=sys.stderr)
        return 2
    if iteration_breached():
        print(
            "FORGE guard: loop cap — the same blocker exceeded the iteration limit; "
            "attribute (PLAN|CONTEXT|TOOL|CAPABILITY) and escalate to a human",
            file=sys.stderr,
        )
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
