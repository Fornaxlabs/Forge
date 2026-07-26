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


def main() -> int:
    try:
        sys.stdin.read()  # drain the SessionStart payload; we don't need it
    except Exception:  # noqa: BLE001,S110 — deliberate: a banner must never wedge startup
        pass
    try:
        if guard_wired(_root()):
            print("🔨 FORGE active — guard armed (deny · ceiling · loop · scope). "
                  "Verify anytime: /forge:forge-doctor", file=sys.stderr)
        else:
            print("⚠ FORGE loaded but the guard is NOT wired to PreToolUse — this "
                  "session is NOT enforced. Run /forge:forge-doctor.", file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
