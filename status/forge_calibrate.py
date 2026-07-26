#!/usr/bin/env python3
"""FORGE calibrator — tune the guardrails to how this project ACTUALLY works.

Every limit in Forge (tool-call ceiling, fan-out cap, loop cap, stale window) is a
guess until it meets real runs. Models change, projects differ, and a limit that was
right last quarter drifts into one of two failure modes:

  TOO TIGHT  — it fires on honest work, so the user disables it. A guardrail that
               annoys is a guardrail that gets removed. This is how protection dies.
  TOO LOOSE  — it never fires at all, so it protects nothing and only *feels* safe.
               Security theatre is worse than no control, because you stop looking.

This reads the project's own run history (.forge/runs/*.jsonl) and reports which limits
are miscalibrated, with the evidence.

    python3 status/forge_calibrate.py [ROOT] [--json]

SAFETY — this NEVER edits your configuration. It prints recommendations and the exact
command to apply them. Adaptation that silently loosens a control is self-disarmament:
a run that keeps hitting the ceiling might be a runaway, not a big task, and only a
human can tell those apart. Tightening is equally a human call, so the tool proposes
and you decide. Read-only, always.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any

# A limit should sit comfortably above honest work but still catch a runaway. We
# recommend headroom over the observed peak rather than the mean: the peak is the
# honest work that came closest to being blocked.
HEADROOM = 2.0          # recommend ~2x the busiest observed honest run
MIN_RUNS_TO_ADVISE = 3  # below this, the sample is too small to say anything


@dataclass
class Finding:
    control: str
    verdict: str        # "too-tight" | "too-loose" | "ok" | "insufficient-data"
    detail: str
    evidence: str
    suggestion: str = ""


@dataclass
class Calibration:
    runs_analysed: int
    findings: list[Finding] = field(default_factory=list)


def _read_runs(runs_dir: str) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = []
    try:
        names = sorted(os.listdir(runs_dir))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        events: list[dict[str, Any]] = []
        try:
            with open(os.path.join(runs_dir, name)) as fh:
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
            continue
        if events:
            out.append(events)
    return out


def _end(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((e for e in events if e.get("event") == "run_end"), None)


def calibrate(runs: list[list[dict[str, Any]]], ceiling: int, max_agents: int) -> Calibration:
    cal = Calibration(runs_analysed=len(runs))
    if len(runs) < MIN_RUNS_TO_ADVISE:
        cal.findings.append(Finding(
            "all", "insufficient-data",
            f"only {len(runs)} governed run(s) on record",
            f"need >= {MIN_RUNS_TO_ADVISE} to distinguish honest work from a runaway",
            "Run more governed tasks, then re-run the calibrator.",
        ))
        return cal

    calls = [int(e.get("tool_calls", 0) or 0) for ev in runs if (e := _end(ev))]
    agents = [int(e.get("agent_count", 0) or 0) for ev in runs if (e := _end(ev))]
    blockers = [sum(1 for x in ev if x.get("event") == "blocker") for ev in runs]
    verified = sum(1 for ev in runs if any(
        x.get("event") in ("verify", "test", "review") for x in ev))
    forced = sum(1 for ev in runs if any(x.get("event") == "unverified_close" for x in ev))

    # --- tool-call ceiling ---------------------------------------------------
    if calls:
        peak = max(calls)
        near = sum(1 for c in calls if c >= ceiling * 0.9)
        if near:
            cal.findings.append(Finding(
                "ceiling", "too-tight",
                f"{near} run(s) came within 10% of the ceiling ({ceiling})",
                f"observed tool-calls per run: peak={peak}, all={sorted(calls)[-5:]}",
                f"Raise it: FORGE_CEILING={max(int(peak * HEADROOM), ceiling + 10)} "
                "— but first confirm those runs were honest work, not runaways.",
            ))
        elif peak * 4 < ceiling:
            cal.findings.append(Finding(
                "ceiling", "too-loose",
                f"the ceiling ({ceiling}) is {ceiling // max(peak, 1)}x the busiest run ({peak})",
                f"observed tool-calls per run: peak={peak}",
                f"It has never plausibly fired — consider FORGE_CEILING="
                f"{max(int(peak * HEADROOM), 10)} so it can actually catch a runaway.",
            ))
        else:
            cal.findings.append(Finding(
                "ceiling", "ok", f"ceiling {ceiling} sits above the busiest run ({peak})",
                f"peak={peak}, runs={len(calls)}"))

    # --- fan-out cap ---------------------------------------------------------
    if any(agents):
        peak_a = max(agents)
        if peak_a >= max_agents:
            cal.findings.append(Finding(
                "fan-out", "too-tight",
                f"a run engaged {peak_a} agents against a cap of {max_agents}",
                f"agents per run: {sorted(agents)[-5:]}",
                f"Raise it: FORGE_MAX_AGENTS={peak_a * 2}, or consolidate the work.",
            ))
        else:
            cal.findings.append(Finding(
                "fan-out", "ok", f"peak fan-out {peak_a} is under the cap ({max_agents})",
                f"agents per run: {sorted(agents)[-5:]}"))
    else:
        cal.findings.append(Finding(
            "fan-out", "ok", "no multi-agent runs recorded — cap untested here",
            "agent_count is 0 on every run (single-agent, or the harness sends no agent_id)"))

    # --- loop cap ------------------------------------------------------------
    if blockers and max(blockers) >= 3:
        cal.findings.append(Finding(
            "loop-cap", "too-tight",
            f"a run recorded {max(blockers)} blockers on the same review cycle",
            f"blockers per run: {sorted(blockers)[-5:]}",
            "Investigate the repeats before raising the cap — a repeated blocker is "
            "usually a PLAN problem, which is exactly what the cap exists to surface.",
        ))

    # --- the done-gate: is it doing anything? --------------------------------
    if forced:
        cal.findings.append(Finding(
            "done-gate", "too-tight",
            f"{forced} run(s) were force-closed without verification",
            f"forced={forced} of {len(runs)} runs",
            "Each --force is a logged assumption. If this is routine, the verification "
            "step is too costly — fix the tests, don't habituate to overriding the gate.",
        ))
    elif verified == len(runs):
        cal.findings.append(Finding(
            "done-gate", "ok", "every run closed with recorded verification",
            f"verified={verified}/{len(runs)}"))

    return cal


def render(cal: Calibration, project: str) -> str:
    icon = {"too-tight": "⚠ TOO TIGHT", "too-loose": "⚠ TOO LOOSE",
            "ok": "✓ ok", "insufficient-data": "· no data"}
    L = [f"FORGE calibration — {project}",
         f"  {cal.runs_analysed} governed run(s) analysed", ""]
    for f in cal.findings:
        L.append(f"  [{icon.get(f.verdict, f.verdict)}] {f.control}: {f.detail}")
        L.append(f"      evidence: {f.evidence}")
        if f.suggestion:
            L.append(f"      suggest:  {f.suggestion}")
        L.append("")
    L.append("  Nothing was changed. Forge proposes; you decide — a control that")
    L.append("  loosens itself is a control that disarms itself.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="forge_calibrate",
                                description="Tune Forge's limits to real run history")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--json", action="store_true")
    ns = p.parse_args(argv)

    root = ns.root or (os.path.dirname(os.environ["FORGE_HOME"])
                       if os.environ.get("FORGE_HOME") else ".")
    project = os.path.basename(os.path.abspath(root)) or "project"
    runs = _read_runs(os.path.join(root, ".forge", "runs"))

    def _envint(name: str, default: int) -> int:
        try:
            v = int(os.environ.get(name, ""))
            return v if v > 0 else default
        except (TypeError, ValueError):
            return default

    cal = calibrate(runs, _envint("FORGE_CEILING", 40), _envint("FORGE_MAX_AGENTS", 12))
    if ns.json:
        print(json.dumps({"project": project, "runs_analysed": cal.runs_analysed,
                          "findings": [f.__dict__ for f in cal.findings]}, indent=2))
    else:
        print(render(cal, project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
