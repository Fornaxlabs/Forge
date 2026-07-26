#!/usr/bin/env python3
"""FORGE SessionStart banner — truthful and self-verifying.

The cooking-app failure was a session that *looked* governed but wasn't. This closes
that: at session start it CHECKS whether the guard is actually wired to the blocking
PreToolUse event and says so — armed or not. It never asserts "armed" without looking.

It NEVER blocks a session (always exit 0) and never raises — a banner must not be able
to wedge startup. The authoritative check is still `/forge:forge-doctor`; this is the
glanceable "is it on?" signal, pointing you there to verify.
"""
from __future__ import annotations

import json
import os
import sys
import time


def _root() -> str:
    r = os.environ.get("CLAUDE_PLUGIN_ROOT")
    return r if r else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def guard_wired(root: str) -> bool:
    """True iff hooks.json wires a guard.py command on a PreToolUse entry covering Bash.
    Deliberately conservative: any error or unexpected shape → False (say 'not armed'
    rather than falsely claim 'armed')."""
    try:
        with open(os.path.join(root, "hooks", "hooks.json")) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
    for entry in hooks.get("PreToolUse", []) or []:
        if not isinstance(entry, dict) or "Bash" not in str(entry.get("matcher", "")):
            continue
        for hook in entry.get("hooks", []) or []:
            cmd = hook.get("command", "") if isinstance(hook, dict) else ""
            # basename match on a bare `python <path>/guard.py` — a `curl …/guard.py|sh`
            # would still slip past this loose check, which is why we point at forge-doctor
            if os.path.basename(cmd.split('"')[-2] if '"' in cmd else cmd.split()[-1]) == "guard.py":
                return True
    return False


def _forge_home() -> str:
    """Same resolution as hooks/guard.py::_forge_home."""
    home = os.environ.get("FORGE_HOME")
    if home:
        return home
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    return os.path.join(proj, ".forge") if proj else ".forge"


def arm_session_run() -> str:
    """Auto-arm an ad-hoc run so the ceiling and loop cap BIND from the first tool call.

    Before this, `claude forge` armed only the deny-list: the ceiling, loop cap and
    done-gate all require an active run, so a session that never typed `/forge <task>`
    was a third protected while looking fully governed. That mismatch is exactly the
    trust failure Forge exists to prevent, so a session now arms itself.

    Returns "armed" (new ad-hoc run), "existing" (a real run is active — never clobber
    it), or "" on failure (fail open). Scope stays UNDECLARED on purpose: an ad-hoc
    session has no plan, and empty scope fails open, so the scope guard remains opt-in
    via `/forge <task>`.
    """
    try:
        home = _forge_home()
        path = os.path.join(home, "active_run.json")
        if os.path.exists(path):
            return "existing"
        now = time.time()
        run_id = time.strftime("%Y-%m-%d-%H%M%S-session", time.gmtime(now))
        os.makedirs(os.path.join(home, "runs"), exist_ok=True)
        run_path = os.path.join(home, "runs", f"{run_id}.jsonl")
        with open(run_path, "a") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now)),
                "run_id": run_id, "event": "run_start", "task": "ad-hoc session",
                "triage": "SMALL", "git_ref": "", "scope": [], "ad_hoc": True,
            }) + "\n")
        with open(path, "w") as fh:
            json.dump({"run_id": run_id, "path": run_path, "started_at": now,
                       "tool_calls": 0, "scope": [], "ad_hoc": True}, fh)
        return "armed"
    except OSError:
        return ""


def main() -> int:
    try:
        sys.stdin.read()  # drain the SessionStart payload; we don't need it
    except Exception:  # noqa: BLE001,S110 — deliberate: never wedge startup
        pass
    try:
        if not guard_wired(_root()):
            print("\u26a0 FORGE loaded but the guard is NOT wired to PreToolUse — this "
                  "session is NOT enforced. Run /forge:forge-doctor.", file=sys.stderr)
            return 0
        state = arm_session_run()
        if state == "existing":
            extra = "run active — scope + done-gate live"
        elif state == "armed":
            extra = ("session run armed — ceiling + loop cap live; "
                     "scope + done-gate need /forge <task>")
        else:
            extra = "run state unavailable — only the deny-list is live"
        print(f"\U0001f528 FORGE active — deny-list armed \u00b7 {extra}. "
              "Verify: /forge:forge-doctor", file=sys.stderr)
    except Exception:  # noqa: BLE001,S110 — deliberate: never wedge startup
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
