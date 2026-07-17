#!/usr/bin/env python3
"""FORGE dashboard driver — collect + certify each project ONCE, render one HTML page.

For every project directory given it runs the read-only collector
(forge_status.collect) and the certificate assembler (forge_certify.certify) —
the collected status is passed into certify so the slow probes run exactly once
per project — then merges the certificate into the status record and hands the
whole list to render_dashboard.render().

Everything downstream is REAL data: no mocked activity, no invented signals.

Usage:
  python3 forge_dashboard.py <project_dir> [more_dirs...] [-o out.html]

Without -o the HTML is written to stdout (progress goes to stderr).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge_certify  # noqa: E402  (sibling module in status/)
import forge_status  # noqa: E402
import render_dashboard  # noqa: E402


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
    ap.add_argument("-o", "--output", default=None, help="write HTML here (default: stdout)")
    ns = ap.parse_args(argv)

    projects: list[dict[str, Any]] = []
    for d in ns.dirs:
        if not os.path.isdir(d):
            print(f"skipping (not a directory): {d}", file=sys.stderr)
            continue
        print(f"collecting {os.path.abspath(d)} ...", file=sys.stderr)
        projects.append(build_project(d))
    if not projects:
        print("no valid project directories given", file=sys.stderr)
        return 2

    collected_at = str(projects[0].get("collected_at", ""))
    page = render_dashboard.render(projects, collected_at)
    if ns.output:
        with open(ns.output, "w") as fh:
            fh.write(page)
        print(f"wrote {ns.output} ({len(page)} bytes, {len(projects)} project(s))", file=sys.stderr)
    else:
        sys.stdout.write(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
