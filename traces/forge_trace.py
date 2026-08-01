#!/usr/bin/env python3
"""FORGE trace CLI — makes run_start/run_end real, appendable JSONL events.

Also writes .forge/active_run.json so hooks/guard.py can enforce the tool-call
ceiling for the duration of a run. `end` clears it.

Commands:
  start   --task T --triage SMALL|MEDIUM|LARGE --git-ref R [--ceiling N] [--slug S]
          [--scope 'glob,glob'] declare the files the plan will touch; the assumption
                                guard (hooks/guard.py) then blocks edits outside them
  log     --event E [--json '{...}']          append an arbitrary event
  blocker --id SLUG                           record a review BLOCKER; once the same
                                              id exceeds the iteration cap, guard.py
                                              blocks the next tool call (loop discipline)
  scope   --add 'glob,glob' | --set 'glob,glob'   declare/widen the run's file scope
                                              (widening is a deliberate, logged act)
  end     --outcome O [--iterations N] [--tool-calls N] [--force --note '<why>']
          A success outcome (done/complete/pass/...) is REFUSED unless the run logged
          verification (a verify/test/review event) — 'done' must be checked, not
          assumed. --force overrides but LOGS the unverified close as an assumption.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from collections.abc import Sequence
from typing import Any

VALID_TRIAGE = ("SMALL", "MEDIUM", "LARGE")


def _home() -> str:
    """Same resolution as hooks/guard.py::_forge_home — anchor run state to a
    CWD-independent path so the guard (fired from any agent, any dir) finds the SAME
    active_run.json. Precedence: FORGE_HOME > $CLAUDE_PROJECT_DIR/.forge > ./.forge."""
    home = os.environ.get("FORGE_HOME")
    if home:
        return home
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        return os.path.join(proj, ".forge")
    return ".forge"


def _active_path() -> str:
    return os.path.join(_home(), "active_run.json")


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s or "run")[:40]


def _today(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _iso(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now))


def _hms(now: float) -> str:
    return time.strftime("%H%M%S", time.gmtime(now))


def _append(run_path: str, run_id: str, event: str, payload: dict[str, Any], now: float) -> None:
    rec = {"ts": _iso(now), "run_id": run_id, "event": event, **payload}
    os.makedirs(os.path.dirname(run_path), exist_ok=True)
    with open(run_path, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def _parse_scope(raw: str | None) -> list[str]:
    """Split a comma/space/newline-separated scope string into a clean glob list."""
    if not raw:
        return []
    parts = re.split(r"[,\n]", raw)
    return [p.strip() for p in parts if p.strip()]


def start(
    *, task: str, triage: str, git_ref: str, ceiling: int, slug: str | None,
    now: float, scope: list[str] | None = None,
) -> str:
    if triage not in VALID_TRIAGE:
        raise ValueError(f"triage must be one of {VALID_TRIAGE}")
    # Include HHMMSS so two runs with the same day+slug don't collide (which would
    # append one run's events into another's file and clobber active_run.json).
    run_id = f"{_today(now)}-{_hms(now)}-{_slugify(slug or task)}"
    run_path = os.path.join(_home(), "runs", f"{run_id}.jsonl")
    scope = scope or []
    _append(run_path, run_id, "run_start",
            {"task": task, "triage": triage, "git_ref": git_ref, "scope": scope}, now)
    os.makedirs(_home(), exist_ok=True)
    with open(_active_path(), "w") as fh:
        json.dump(
            {"run_id": run_id, "path": run_path, "started_at": now,
             "tool_calls": 0, "ceiling": ceiling, "scope": scope},
            fh,
        )
    return run_id


def set_scope(globs: list[str], *, replace: bool, now: float) -> list[str]:
    """Declare (or widen) the active run's file scope — the assumption guard reads it.
    `replace` overwrites; otherwise the globs are added to what's already declared.
    Returns the resulting scope. Widening scope is a deliberate, logged act: it's how
    a run says 'yes, I really do mean to touch these too' instead of assuming it."""
    globs = [g.strip() for g in globs if g.strip()]
    path = _active_path()
    with open(path, "r+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
        except OSError:
            pass
        run = json.load(fh)
        if not isinstance(run, dict) or "path" not in run or "run_id" not in run:
            raise ValueError("active_run.json is corrupt (missing path/run_id)")
        current = run.get("scope")
        current = current if isinstance(current, list) else []
        if replace:
            result = list(dict.fromkeys(globs))
        else:
            result = list(dict.fromkeys([*current, *globs]))
        run["scope"] = result
        fh.seek(0)
        json.dump(run, fh)
        fh.truncate()
    _append(run["path"], run["run_id"], "scope",
            {"scope": result, "added": globs, "replace": replace}, now)
    return result


def _load_active() -> dict[str, Any]:
    with open(_active_path()) as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "path" not in data or "run_id" not in data:
        raise ValueError("active_run.json is corrupt (missing path/run_id)")
    return data


def log(event: str, extra: dict[str, Any], now: float) -> None:
    if not isinstance(extra, dict):  # noqa: TRY004 — CLI contract: ValueError -> exit 1
        raise ValueError("--json payload must be a JSON object")
    active = _load_active()
    _append(active["path"], active["run_id"], event, extra, now)


def record_blocker(blocker_id: str, now: float) -> int:
    """Increment the count for this blocker on the active run and log it. Returns the
    new count. Once it exceeds the run's iteration_cap, hooks/guard.py blocks the next
    tool call — this is what turns 'max 3 iterations' from prose into enforcement.

    Read-modify-write under an exclusive flock so concurrent reviewer calls can't lose
    an increment (which would let the cap be silently exceeded)."""
    blocker_id = blocker_id.strip()
    if not blocker_id:
        raise ValueError("blocker --id must be non-empty")
    path = _active_path()
    with open(path, "r+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX)
        except OSError:
            pass  # locking unsupported → still correct single-threaded
        run = json.load(fh)
        if not isinstance(run, dict) or "path" not in run or "run_id" not in run:
            raise ValueError("active_run.json is corrupt (missing path/run_id)")
        blockers = run.get("blockers")
        if not isinstance(blockers, dict):
            blockers = {}
        count = int(blockers.get(blocker_id, 0)) + 1
        blockers[blocker_id] = count
        run["blockers"] = blockers
        run["iterations"] = int(run.get("iterations", 0)) + 1
        fh.seek(0)
        json.dump(run, fh)
        fh.truncate()
    _append(run["path"], run["run_id"], "blocker", {"blocker_id": blocker_id, "count": count}, now)
    return count


# --- verification independence (Forge original, 2026-07-30) -------------------
# Prior art LABELS a same-model verification. Forge can REFUSE it: independence is
# recorded per verify event and the done-gate can require it. A verifier that shares
# the author's model family inherits the author's blind spots, so "verified" by the
# same family is weaker evidence — and weak evidence presented as proof is the exact
# failure this project exists to stop.
_FAMILIES = {
    "claude": "anthropic", "opus": "anthropic", "sonnet": "anthropic",
    "haiku": "anthropic", "fable": "anthropic", "mythos": "anthropic",
    "gpt": "openai", "codex": "openai", "o1": "openai", "o3": "openai",
    "gemini": "google", "kimi": "moonshot", "grok": "xai", "llama": "meta",
}


def model_family(model: str) -> str:
    """Map a model id/name to its vendor family; '' when unrecognised.
    Substring match so 'claude-opus-5' and 'gpt-5.6-codex' both resolve."""
    m = (model or "").strip().lower()
    for token, fam in _FAMILIES.items():
        if token in m:
            return fam
    return ""


def _effective_triage(events: list[dict[str, Any]]) -> str:
    """The tier the run ENDED at — a mid-run re-triage raises it."""
    start = next((e for e in events if e.get("event") == "run_start"), None)
    tier = str(start.get("triage", "")) if start else ""
    for e in events:
        if e.get("event") == "retriage" and e.get("to"):
            tier = str(e["to"])
    return tier


def verification_independence(events: list[dict[str, Any]]) -> str:
    """Strongest independence achieved by any verify event in this run:
      "cross-family" — a different vendor's model reproduced the evidence
      "same-family"  — verified, but by the author's own family (weaker)
      "unlabelled"   — verified, but the run never said who verified
      "none"         — no verification at all
    Returns the BEST result, because one genuinely independent check is enough."""
    best = "none"
    rank = {"none": 0, "unlabelled": 1, "same-family": 2, "cross-family": 3}
    for rec in events:
        if rec.get("event") not in _VERIFY_EVENTS:
            continue
        if rec.get("passed") is False or rec.get("ok") is False:
            continue
        v, a = model_family(str(rec.get("verifier", ""))), model_family(str(rec.get("author", "")))
        if v and a:
            got = "cross-family" if v != a else "same-family"
        else:
            got = "unlabelled"
        if rank[got] > rank[best]:
            best = got
    return best


# Outcomes that assert the work succeeded — these MUST be backed by verification.
# "green" is Forge's own pipeline word for success (see commands/forge.md); include it
# so the done-gate actually bites on Forge's canonical outcome. "escalated"/"abandoned"
# are deliberately absent — they don't claim success, so they need no verification.
_SUCCESS_OUTCOMES = frozenset({
    "success", "done", "complete", "completed", "shipped",
    "pass", "passed", "ok", "green",
})
# Events that count as real verification evidence (research/checks actually ran).
_VERIFY_EVENTS = frozenset({
    "verify", "verified", "test", "tests", "review", "reviewed",
    "checks", "lint", "typecheck", "eval",
})


def _read_events(run_path: str) -> list[dict[str, Any]]:
    """Best-effort read of a run's JSONL events. Missing/garbled lines are skipped —
    reading evidence must never itself raise."""
    events: list[dict[str, Any]] = []
    try:
        with open(run_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    events.append(rec)
    except OSError:
        pass
    return events


def has_verification(run_path: str) -> bool:
    """True iff this run logged at least one verification event that did NOT record a
    failure — the evidence that 'done' is a checked fact, not an assumption. A verify
    event with an explicit {"passed": false} does not count (a failed check is not
    proof of success)."""
    for rec in _read_events(run_path):
        if rec.get("event") not in _VERIFY_EVENTS:
            continue
        if rec.get("passed") is False or rec.get("ok") is False:
            continue
        return True
    return False


def end(
    *, outcome: str, iterations: int, tool_calls: int | None, now: float,
    force: bool = False, note: str | None = None,
) -> None:
    active = _load_active()
    tc = active.get("tool_calls", 0) if tool_calls is None else tool_calls
    # Definition-of-done gate — the assumption guard at close time: a run may not
    # claim success without recorded verification. "No evidence = didn't happen" made
    # enforceable. --force still lets a human override, but the unverified close is
    # LOGGED as an explicit assumption, never silent.
    events = _read_events(active["path"])
    independence = verification_independence(events)
    # Research gate (2026-08-01, from a field RCA): a LARGE run decides architecture —
    # an ADR, an auth or network choice — and those are built on external facts. The
    # research rule existed in prose, an eval and an audit counter, and bound in none
    # of them: an agent asserted a CLI flag from memory inside a LARGE decision and
    # nothing stopped it, because advisory rules lose to a model that feels certain.
    # Deliberately narrow: LARGE only, so a local refactor never trips it.
    if (outcome.strip().lower() in _SUCCESS_OUTCOMES and not force
            and _effective_triage(events) == "LARGE"
            and not any(e.get("event") == "research" for e in events)):
        raise ValueError(
            "cannot close a LARGE run as "
            f"'{outcome}' with zero research events. A LARGE run decides architecture, "
            "and those decisions rest on external facts (CLI flags, API behaviour, "
            "versions) that training memory gets wrong without announcing it. Log what "
            "you actually checked: `log --event research --json "
            "'{\"claim\":\"...\",\"source\":\"<url>\",\"version\":\"...\"}'`. "
            "If the decision genuinely rested on no external fact, say so with --force "
            "--note '<why>' and it is recorded as an assumption."
        )
    # Opt-in strict mode: a success close REQUIRES genuinely independent verification.
    if (outcome.strip().lower() in _SUCCESS_OUTCOMES
            and os.environ.get("FORGE_REQUIRE_CROSS_FAMILY") == "1"
            and independence != "cross-family" and not force):
        raise ValueError(
            f"cannot close as '{outcome}': verification independence is "
            f"'{independence}', but FORGE_REQUIRE_CROSS_FAMILY=1 demands a verifier "
            "from a different model family than the author. Log it as "
            "`log --event verify --json '{\"passed\":true,\"author\":\"<model>\","
            "\"verifier\":\"<other-family-model>\"}'`, or drop the strict flag."
        )
    if outcome.strip().lower() in _SUCCESS_OUTCOMES and not has_verification(active["path"]):
        if not force:
            raise ValueError(
                f"cannot close as '{outcome}' without verification — no verify/test/"
                "review event was logged this run. Run the checks, then "
                "`forge_trace log --event verify --json '{\"passed\": true}'`. If you "
                "must close anyway, pass --force --note '<why>' (logged as an assumption)."
            )
        _append(active["path"], active["run_id"], "unverified_close",
                {"outcome": outcome, "note": note or ""}, now)
    # Preserve the multi-agent roster the guard built up (agent id -> mutating calls)
    # before active_run.json is deleted — otherwise "who did what" is lost at close and
    # the audit can only report totals.
    agents = active.get("agents")
    payload: dict[str, Any] = {"outcome": outcome, "iterations": iterations,
                               "tool_calls": tc, "independence": independence}
    if isinstance(agents, dict) and agents:
        payload["agents"] = agents
        payload["agent_count"] = len(agents)
    _append(active["path"], active["run_id"], "run_end", payload, now)
    os.remove(_active_path())


def main(argv: Sequence[str] | None = None, now: float | None = None) -> int:
    now = time.time() if now is None else now
    p = argparse.ArgumentParser(prog="forge_trace", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("start")
    ps.add_argument("--task", required=True)
    ps.add_argument("--triage", required=True, choices=VALID_TRIAGE)
    ps.add_argument("--git-ref", required=True)
    ps.add_argument("--ceiling", type=int, default=40)
    ps.add_argument("--slug")
    ps.add_argument("--scope", help="comma-separated file globs the plan will touch "
                    "(assumption guard blocks edits outside them)")

    pl = sub.add_parser("log")
    pl.add_argument("--event", required=True)
    pl.add_argument("--json", default="{}")

    pb = sub.add_parser("blocker", help="record a review BLOCKER (enforces the loop cap)")
    pb.add_argument("--id", required=True, dest="blocker_id",
                    help="stable slug identifying the blocker (same finding → same id)")

    psc = sub.add_parser("scope", help="declare/widen the run's file scope (assumption guard)")
    psc.add_argument("--add", help="comma-separated globs to add to the scope")
    psc.add_argument("--set", dest="set_globs",
                     help="comma-separated globs that REPLACE the scope")

    pe = sub.add_parser("end")
    pe.add_argument("--outcome", required=True)
    pe.add_argument("--iterations", type=int, default=0)
    pe.add_argument("--tool-calls", type=int)
    pe.add_argument("--force", action="store_true",
                    help="close even without verification (logged as an assumption)")
    pe.add_argument("--note", help="reason, required with --force on a success outcome")

    args = p.parse_args(argv)
    try:
        if args.cmd == "start":
            run_id = start(task=args.task, triage=args.triage, git_ref=args.git_ref,
                           ceiling=args.ceiling, slug=args.slug,
                           scope=_parse_scope(args.scope), now=now)
            print(run_id)
        elif args.cmd == "log":
            log(args.event, json.loads(args.json), now)
        elif args.cmd == "blocker":
            count = record_blocker(args.blocker_id, now)
            print(count)
        elif args.cmd == "scope":
            if args.set_globs is not None:
                result = set_scope(_parse_scope(args.set_globs), replace=True, now=now)
            elif args.add is not None:
                result = set_scope(_parse_scope(args.add), replace=False, now=now)
            else:
                raise ValueError("scope needs --add or --set")
            print(",".join(result))
        elif args.cmd == "end":
            end(outcome=args.outcome, iterations=args.iterations,
                tool_calls=args.tool_calls, force=args.force, note=args.note, now=now)
    except FileNotFoundError:
        print("error: no active run (call 'start' first)", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
