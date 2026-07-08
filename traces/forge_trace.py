#!/usr/bin/env python3
"""FORGE trace CLI — makes run_start/run_end real, appendable JSONL events.

Also writes .forge/active_run.json so hooks/guard.py can enforce the tool-call
ceiling for the duration of a run. `end` clears it.

Commands:
  start --task T --triage SMALL|MEDIUM|LARGE --git-ref R [--ceiling N] [--slug S]
  log   --event E [--json '{...}']            append an arbitrary event
  end   --outcome O [--iterations N] [--tool-calls N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Sequence
from typing import Any

VALID_TRIAGE = ("SMALL", "MEDIUM", "LARGE")


def _home() -> str:
    return os.environ.get("FORGE_HOME", ".forge")


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


def start(
    *, task: str, triage: str, git_ref: str, ceiling: int, slug: str | None,
    now: float,
) -> str:
    if triage not in VALID_TRIAGE:
        raise ValueError(f"triage must be one of {VALID_TRIAGE}")
    # Include HHMMSS so two runs with the same day+slug don't collide (which would
    # append one run's events into another's file and clobber active_run.json).
    run_id = f"{_today(now)}-{_hms(now)}-{_slugify(slug or task)}"
    run_path = os.path.join(_home(), "runs", f"{run_id}.jsonl")
    _append(run_path, run_id, "run_start",
            {"task": task, "triage": triage, "git_ref": git_ref}, now)
    os.makedirs(_home(), exist_ok=True)
    with open(_active_path(), "w") as fh:
        json.dump(
            {"run_id": run_id, "path": run_path, "started_at": now,
             "tool_calls": 0, "ceiling": ceiling},
            fh,
        )
    return run_id


def _load_active() -> dict[str, Any]:
    with open(_active_path()) as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "path" not in data or "run_id" not in data:
        raise ValueError("active_run.json is corrupt (missing path/run_id)")
    return data


def log(event: str, extra: dict[str, Any], now: float) -> None:
    if not isinstance(extra, dict):
        raise ValueError("--json payload must be a JSON object")
    active = _load_active()
    _append(active["path"], active["run_id"], event, extra, now)


def end(*, outcome: str, iterations: int, tool_calls: int | None, now: float) -> None:
    active = _load_active()
    tc = active.get("tool_calls", 0) if tool_calls is None else tool_calls
    _append(active["path"], active["run_id"], "run_end",
            {"outcome": outcome, "iterations": iterations, "tool_calls": tc}, now)
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

    pl = sub.add_parser("log")
    pl.add_argument("--event", required=True)
    pl.add_argument("--json", default="{}")

    pe = sub.add_parser("end")
    pe.add_argument("--outcome", required=True)
    pe.add_argument("--iterations", type=int, default=0)
    pe.add_argument("--tool-calls", type=int)

    args = p.parse_args(argv)
    try:
        if args.cmd == "start":
            run_id = start(task=args.task, triage=args.triage, git_ref=args.git_ref,
                           ceiling=args.ceiling, slug=args.slug, now=now)
            print(run_id)
        elif args.cmd == "log":
            log(args.event, json.loads(args.json), now)
        elif args.cmd == "end":
            end(outcome=args.outcome, iterations=args.iterations,
                tool_calls=args.tool_calls, now=now)
    except FileNotFoundError:
        print("error: no active run (call 'start' first)", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
