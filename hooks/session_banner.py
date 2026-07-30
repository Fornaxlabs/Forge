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


def _env_int(name: str, fallback: int) -> int:
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _forge_home() -> str:
    """Same resolution as hooks/guard.py::_forge_home."""
    home = os.environ.get("FORGE_HOME")
    if home:
        return home
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    return os.path.join(proj, ".forge") if proj else ".forge"


def arm_session_run() -> str:
    """Auto-arm a per-SESSION ad-hoc run so the ceiling and loop cap bind immediately.

    Returns "armed" | "existing" (a real /forge run is active — never clobber it) |
    "skipped" (not a project dir) | "" (failure; fail open).

    THREE RULES LEARNED THE HARD WAY (field bug, 2026-07-30). The first version of this
    function permanently wedged a user: it armed a run in $HOME, ad-hoc runs are never
    closed by a task boundary, so ONE counter accumulated across every session until it
    crossed the ceiling and halted every future session.
      1. Never arm outside a project. $HOME (or any dir with no .git) is not a run.
      2. A new session REPLACES a previous ad-hoc run — the counter is per session, not
         an immortal global tally. A real /forge run is never touched.
      3. Ad-hoc runs get a generous ceiling: they have no plan and no boundary, so they
         are a runaway backstop only, not a budget for a scoped task.
    """
    try:
        home = _forge_home()
        parent = os.path.dirname(os.path.abspath(home))
        # RULE 1: only arm inside something that looks like a project.
        if parent == os.path.expanduser("~") or not os.path.isdir(os.path.join(parent, ".git")):
            return "skipped"
        path = os.path.join(home, "active_run.json")
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    existing = json.load(fh)
                if not (isinstance(existing, dict) and existing.get("ad_hoc")):
                    return "existing"          # a real /forge run — leave it alone
            except (OSError, ValueError):
                pass                            # corrupt -> replace it below
            # RULE 2: stale ad-hoc run from a previous session -> start a fresh counter.
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
            # RULE 3: generous ceiling — a backstop, not a budget.
            json.dump({"run_id": run_id, "path": run_path, "started_at": now,
                       "tool_calls": 0, "scope": [], "ad_hoc": True,
                       "ceiling": _env_int("FORGE_ADHOC_CEILING", 500)}, fh)
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
        if state == "skipped":
            extra = "no project run (not a git project) — deny-list only"
        elif state == "existing":
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
