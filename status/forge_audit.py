#!/usr/bin/env python3
"""FORGE audit exporter — turn run traces into a compliance-grade audit report.

Reads `.forge/runs/*.jsonl` and produces a lineage-backed record of governed runs:
per run — task, triage tier, declared file scope, human approvals, scope changes,
review blockers, verification evidence, and outcome — plus a portfolio summary.

Aimed at the evidence auditors and procurement now ask for (EU AI Act "lineage-backed
auditability", ISO 42001, human-oversight attestation): show that AI-assisted changes
were planned, human-approved where required, scoped, reviewed, and verified — with a
trail, not an assertion.

    python3 status/forge_audit.py [ROOT]            # Markdown report to stdout
    python3 status/forge_audit.py [ROOT] --json     # machine-readable manifest
    python3 status/forge_audit.py [ROOT] --out FILE # write instead of stdout

ROOT defaults to $FORGE_HOME's parent, else the current dir. Read-only.

HONEST LIMITS: this reports what the TRACE recorded. Guard blocks (destructive-command
deny / ceiling / scope) halt a tool call at the hook and are attested as *controls
active*, not counted per run, unless the guard is configured to log them. Traces are
self-reported by the run, so this shows governed *discipline* and its evidence — it is
not, by itself, a tamper-proof ledger (the self-audit + signing address that separately).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

_VERIFY_EVENTS = frozenset({
    "verify", "verified", "test", "tests", "review", "reviewed",
    "checks", "lint", "typecheck", "eval",
})


@dataclass
class RunAudit:
    run_id: str
    task: str
    triage: str
    git_ref: str
    scope: list[str]
    started_at: float
    ended_at: float | None
    outcome: str | None
    completed: bool
    human_approved: bool
    retriaged: bool
    scope_changes: int
    review_blockers: int
    verifications: int
    researched: int
    forced_close: bool
    event_count: int
    agent_count: int
    agents: dict[str, int]

    @property
    def duration_s(self) -> float | None:
        if self.ended_at and self.started_at:
            return round(self.ended_at - self.started_at, 1)
        return None

    @property
    def verified(self) -> bool:
        return self.verifications > 0 and not self.forced_close


def _read_events(path: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def _agent_map(end: dict[str, Any] | None) -> dict[str, int]:
    """Per-agent mutating-call counts from run_end, defensively typed."""
    raw = end.get("agents") if end else None
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def audit_run(events: list[dict[str, Any]]) -> RunAudit | None:
    start = next((e for e in events if e.get("event") == "run_start"), None)
    if start is None:
        return None

    def _ts(rec: dict[str, Any]) -> float:
        t = rec.get("ts", "")
        try:
            return time.mktime(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            return 0.0

    end = next((e for e in events if e.get("event") == "run_end"), None)
    raw_scope = start.get("scope")
    scope = raw_scope if isinstance(raw_scope, list) else []
    human_approved = any(
        e.get("event") == "stage" and e.get("approved_by") == "human" for e in events
    )
    # Effective risk tier: a mid-run re-triage (scope-flip) raises it — the audit must
    # reflect the tier the run ENDED at, not the one it optimistically started at.
    triage = str(start.get("triage", "?"))
    retriages = [e for e in events if e.get("event") == "retriage" and e.get("to")]
    if retriages:
        triage = str(retriages[-1]["to"])
    return RunAudit(
        run_id=str(start.get("run_id", "?")),
        task=str(start.get("task", "")),
        triage=triage,
        git_ref=str(start.get("git_ref", "")),
        scope=[str(s) for s in scope],
        started_at=_ts(start),
        ended_at=_ts(end) if end else None,
        outcome=str(end.get("outcome")) if end else None,
        completed=end is not None,
        human_approved=human_approved,
        retriaged=any(e.get("event") == "retriage" for e in events),
        scope_changes=sum(1 for e in events if e.get("event") == "scope"),
        review_blockers=sum(1 for e in events if e.get("event") == "blocker"),
        verifications=sum(1 for e in events if e.get("event") in _VERIFY_EVENTS),
        researched=sum(1 for e in events if e.get("event") == "research"),
        forced_close=any(e.get("event") == "unverified_close" for e in events),
        event_count=len(events),
        agent_count=int(end.get("agent_count", 0)) if end else 0,
        agents=_agent_map(end),
    )


def collect(runs_dir: str) -> list[RunAudit]:
    runs: list[RunAudit] = []
    try:
        names = sorted(os.listdir(runs_dir))
    except OSError:
        return runs
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        rec = audit_run(_read_events(os.path.join(runs_dir, name)))
        if rec is not None:
            runs.append(rec)
    return runs


def summarize(runs: list[RunAudit]) -> dict[str, Any]:
    return {
        "runs": len(runs),
        "completed": sum(1 for r in runs if r.completed),
        "human_approved": sum(1 for r in runs if r.human_approved),
        "verified_closes": sum(1 for r in runs if r.verified),
        "forced_unverified_closes": sum(1 for r in runs if r.forced_close),
        "retriaged": sum(1 for r in runs if r.retriaged),
        "large_tier": sum(1 for r in runs if r.triage == "LARGE"),
        "multi_agent": sum(1 for r in runs if r.agent_count > 1),
    }


def render_markdown(runs: list[RunAudit], summ: dict[str, Any], project: str, now: float) -> str:
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))
    L = [
        f"# FORGE governance audit — {project}",
        "",
        f"Generated {when} · {summ['runs']} governed run(s) on record.",
        "",
        "This report is lineage-backed evidence that AI-assisted changes ran under a "
        "governed process: triaged, planned, human-approved where required, scoped, "
        "reviewed, and verified. Each row traces to `.forge/runs/<run>.jsonl`.",
        "",
        "## Controls attested",
        "",
        "| Control | Evidence in trace |",
        "|---|---|",
        "| Human oversight | `human_approved` per run (LARGE requires human approval) |",
        "| Change scoping | declared file scope + logged scope changes |",
        "| Verification-before-done | run cannot close success without a verify event |",
        "| Loop discipline | repeated-blocker count capped and recorded |",
        "| Multi-agent accountability | per-agent action counts recorded; fan-out capped |",
        "| Deterministic guard (deny/ceiling/scope) | wired at PreToolUse — verify with "
        "`forge_doctor.py`; enforced, not counted here |",
        "",
        "## Portfolio summary",
        "",
        f"- Runs: **{summ['runs']}** ({summ['completed']} completed)",
        f"- Human-approved: **{summ['human_approved']}**",
        f"- Verified closes: **{summ['verified_closes']}**",
        f"- Forced (unverified) closes: **{summ['forced_unverified_closes']}** "
        "— each is logged as an explicit assumption, not silent",
        f"- Re-triaged mid-run (scope-flip caught): **{summ['retriaged']}**",
        f"- LARGE-tier (high-risk) runs: **{summ['large_tier']}**",
        f"- Multi-agent runs (>1 agent): **{summ['multi_agent']}**",
        "",
        "## Runs",
        "",
        "| Run | Task | Tier | Approved | Scope | Reviews | Verified | Outcome |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in runs:
        task = (r.task[:40] + "…") if len(r.task) > 41 else r.task
        L.append(
            f"| `{r.run_id}` | {task} | {r.triage} | "
            f"{'✅' if r.human_approved else '—'} | {len(r.scope)} glob(s) | "
            f"{r.review_blockers} | {'✅' if r.verified else ('⚠ forced' if r.forced_close else '—')} | "
            f"{r.outcome or 'open'} |"
        )
    L += [
        "",
        "## Honest limits",
        "- Traces are self-reported by each run; this attests governed *discipline* and "
        "its evidence, not a tamper-proof ledger. Integrity of the enforcement layer is "
        "attested separately by `forge_doctor.py` (self-audit) and the signed certificate.",
        "- Guard blocks (destructive-command deny / tool-call ceiling / out-of-scope edit) "
        "are enforced at the hook and halt the action; they are attested as *controls "
        "active* above, not counted per run unless block-logging is enabled.",
        "",
    ]
    return "\n".join(L)


def _resolve_runs_dir(root: str) -> str:
    return os.path.join(root, ".forge", "runs")


def main(argv: list[str] | None = None, now: float | None = None) -> int:
    now = time.time() if now is None else now
    p = argparse.ArgumentParser(prog="forge_audit", description="Compliance audit export from traces")
    p.add_argument("root", nargs="?", default=None)
    p.add_argument("--json", action="store_true", help="emit JSON manifest instead of Markdown")
    p.add_argument("--out", help="write to FILE instead of stdout")
    args = p.parse_args(argv)

    if args.root:
        root = args.root
    else:
        fh = os.environ.get("FORGE_HOME")
        root = os.path.dirname(fh) if fh else "."
    project = os.path.basename(os.path.abspath(root)) or "project"

    runs = collect(_resolve_runs_dir(root))
    summ = summarize(runs)

    if args.json:
        payload: dict[str, Any] = {
            "project": project,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "summary": summ,
            "runs": [{**asdict(r), "verified": r.verified, "duration_s": r.duration_s}
                     for r in runs],
        }
        text = json.dumps(payload, indent=2)
    else:
        text = render_markdown(runs, summ, project, now)

    if args.out:
        with open(args.out, "w") as fh2:
            fh2.write(text + "\n")
        print(f"wrote {args.out} ({summ['runs']} runs)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
