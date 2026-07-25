#!/usr/bin/env python3
"""FORGE dashboard driver — collect + certify each project ONCE, render one product.

For every project directory given it runs the read-only collector
(forge_status.collect) and the certificate assembler (forge_certify.certify) —
the collected status is passed into certify so the slow probes run exactly once
per project — then merges the certificate into the status record, discovers any
REAL run traces at <project>/.forge/runs/*.jsonl, and hands the whole list to
render_dashboard.render().

Everything downstream is REAL data: no mocked activity, no invented signals,
and never a fabricated run — a project with no traces shows an honest empty
state in the dashboard's Runs card.

Usage:
  python3 forge_dashboard.py <project_dir> [more_dirs...] [-o out.html | -o outdir]

Output modes:
  -o <dir>       linked product: <dir>/index.html (the dashboard, single entry
                 point) plus one <dir>/pipeline-<project>-<runid>.html per
                 discovered trace, rendered by traces/render_pipeline.py; the
                 dashboard's Runs card links to each pipeline page and every
                 pipeline page links back to index.html.
  -o <*.html>    single-file dashboard (runs are still listed; pipeline pages
                 are not emitted, so run rows carry no links).
  (no -o)        single-file dashboard to stdout (progress goes to stderr).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "traces"))
import forge_audit  # noqa: E402  (sibling module in status/)
import forge_certify  # noqa: E402
import forge_status  # noqa: E402
import render_dashboard  # noqa: E402
import render_pipeline  # noqa: E402  (sibling package dir traces/)


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(s: str) -> str:
    """Filename-safe slug — trace-supplied ids never choose path separators."""
    return _UNSAFE.sub("_", s).strip("._") or "run"


def _trace_summary(events: list[dict[str, object]]) -> dict[str, Any] | None:
    """RAW (unescaped) facts about one parsed trace, or None when it has no
    run_start event (not a governed-run trace). Escaping is render_dashboard's
    job — passing pre-escaped text would double-escape."""
    start = next((ev for ev in events if ev.get("event") == "run_start"), None)
    if start is None:
        return None
    end = next((ev for ev in reversed(events) if ev.get("event") == "run_end"), None)

    def _s(ev: dict[str, object] | None, key: str) -> str:
        val = ev.get(key) if ev is not None else None
        return val if isinstance(val, str) else ""

    return {
        "run_id": _s(start, "run_id"),
        "task": _s(start, "task"),
        "started": _s(start, "ts"),
        "outcome": _s(end, "outcome"),  # "" = no run_end recorded (shown honestly)
        "events": len(events),
    }


def discover_runs(d: str) -> list[dict[str, Any]]:
    """REAL traces only: <project>/.forge/runs/*.jsonl that parse and contain a
    run_start. Never fabricates a run — an empty list means exactly that."""
    runs_dir = os.path.join(d, ".forge", "runs")
    found: list[dict[str, Any]] = []
    if not os.path.isdir(runs_dir):
        return found
    for fn in sorted(os.listdir(runs_dir)):
        if not fn.endswith(".jsonl"):
            continue
        path = os.path.join(runs_dir, fn)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        summary = _trace_summary(render_pipeline.parse_trace(text))
        if summary is None:
            continue
        summary["trace_path"] = path
        summary["trace_text"] = text  # consumed (popped) before rendering the index
        found.append(summary)
    return found


def build_project(d: str) -> dict[str, Any]:
    """Collect once, certify from that same collection, merge."""
    status = forge_status.collect(d)
    cert = forge_certify.certify(d, status=status)
    return {
        **status,
        "certificate": {
            "level": cert["level"],
            "claims": cert["claims"],
            "governed_runs": cert["governed_runs"],
            "commit": cert["commit"],
            "generated_at": cert["generated_at"],
            "honest_note": cert["honest_note"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="forge_dashboard.py",
        description="Collect real status + certificate for each project and render "
        "the 3-tab Forge dashboard as self-contained HTML.",
    )
    ap.add_argument("dirs", nargs="+", metavar="project_dir")
    ap.add_argument(
        "-o", "--output", default=None,
        help="a *.html path = single-file dashboard; a directory = index.html plus "
        "one pipeline-*.html per discovered run trace (default: stdout)",
    )
    ns = ap.parse_args(argv)

    projects: list[dict[str, Any]] = []
    for d in ns.dirs:
        if not os.path.isdir(d):
            print(f"skipping (not a directory): {d}", file=sys.stderr)
            continue
        print(f"collecting {os.path.abspath(d)} ...", file=sys.stderr)
        proj = build_project(d)
        proj["runs"] = discover_runs(d)
        # Governance evidence for the Audit tab — same source/definitions as the
        # forge_audit CLI export, so the UI and the auditor's file always agree.
        proj["audit_runs"] = [
            {"task": r.task, "triage": r.triage, "human_approved": r.human_approved,
             "verified": r.verified, "forced_close": r.forced_close,
             "outcome": r.outcome, "run_id": r.run_id}
            for r in forge_audit.collect(os.path.join(d, ".forge", "runs"))
        ]
        projects.append(proj)
    if not projects:
        print("no valid project directories given", file=sys.stderr)
        return 2

    outdir: str | None = None
    if ns.output is not None and (os.path.isdir(ns.output) or not ns.output.endswith(".html")):
        outdir = ns.output
        os.makedirs(outdir, exist_ok=True)

    # Render one pipeline page per REAL discovered trace (directory mode only).
    used_names: set[str] = set()
    for proj in projects:
        for run in proj["runs"]:
            text = str(run.pop("trace_text"))
            if outdir is None:
                continue  # single-file mode: runs listed in the dashboard, no pages
            rid = str(run["run_id"]) or os.path.splitext(
                os.path.basename(str(run["trace_path"])))[0]
            base = f"pipeline-{_slug(str(proj['project']))}-{_slug(rid)}"
            name, k = base + ".html", 2
            while name in used_names:
                name, k = f"{base}-{k}.html", k + 1
            used_names.add(name)
            page = render_pipeline.render(
                text, back_href="index.html", source=str(run["trace_path"]))
            fp = os.path.join(outdir, name)
            with open(fp, "w") as fh:
                fh.write(page)
            run["href"] = name
            print(f"wrote {fp} ({len(page)} bytes)", file=sys.stderr)

    collected_at = str(projects[0].get("collected_at", ""))
    page = render_dashboard.render(projects, collected_at)
    if outdir is not None:
        out = os.path.join(outdir, "index.html")
        with open(out, "w") as fh:
            fh.write(page)
        print(f"wrote {out} ({len(page)} bytes, {len(projects)} project(s))", file=sys.stderr)
    elif ns.output:
        with open(ns.output, "w") as fh:
            fh.write(page)
        print(f"wrote {ns.output} ({len(page)} bytes, {len(projects)} project(s))", file=sys.stderr)
    else:
        sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
