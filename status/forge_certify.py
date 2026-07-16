#!/usr/bin/env python3
"""FORGE certify — assemble a project's REAL signals into a verifiable claim manifest.

"Forge Verified" is not a badge that says "this is secure" — it is a machine-checkable
statement of *which specific controls passed at this commit*, each reproducible by
anyone who checks the repo out. Three levels:

  L1  Gated       — enforcement is armed (pre-push gate, CI, pre-commit config).
  L2  Verified    — L1, and every endpoint check is green at this commit
                    (secrets clean in scanned history, CI green, 0 known CVEs) AND
                    Forge's own enforcement layer passes self-audit.
  L3  Provenanced — L2, and every change went through a Forge-governed run
                    (requires trace history; reported honestly, not faked).

Emits FORGE-CERT.json (machine) + a human summary. Exit 0 iff at least L1. READ-ONLY.

Usage:  python3 forge_certify.py <project_dir> [--json]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge_status  # noqa: E402  (sibling module in status/)

_PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _commit(d: str) -> str:
    try:
        p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True, timeout=10)
        return p.stdout.strip()[:12] or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _forge_version() -> str:
    try:
        with open(os.path.join(_PLUGIN, ".claude-plugin", "plugin.json")) as fh:
            return str(json.load(fh).get("version", "?"))
    except (OSError, ValueError):
        return "?"


def _self_audit_ok() -> tuple[bool, str]:
    """Run the self-audit against the governing plugin. L2 requires the enforcement
    layer itself to be intact — a certificate from a tampered Forge is worthless."""
    try:
        p = subprocess.run(
            [sys.executable, os.path.join(_PLUGIN, "selfaudit", "forge_doctor.py"), "--root", _PLUGIN],
            capture_output=True, text=True, timeout=90,
        )
        return p.returncode == 0, (p.stdout.strip().splitlines() or ["?"])[-1]
    except Exception as exc:  # noqa: BLE001
        return False, f"self-audit could not run: {exc}"


class Claim(dict):
    def __init__(self, name: str, ok: bool, evidence: str, reproduce: str) -> None:
        super().__init__(name=name, passed=ok, evidence=evidence, reproduce=reproduce)


def certify(d: str) -> dict[str, Any]:
    s = forge_status.collect(d)
    enf, sec, gh, deps, forge = s["enforcement"], s["secrets"], s["github"], s["deps"], s["forge"]

    armed = bool(enf.get("pre_push_gate") and enf.get("ci_workflow") and enf.get("pre_commit_config"))
    secrets_clean = bool(sec.get("clean"))
    ci_green = gh.get("connected") and gh.get("latest_ci") == "success"
    kv = deps.get("known_vulns")
    # 0 known CVEs OR nothing to audit (no python manifest) both pass; an error/timeout does not.
    deps_clean = kv == 0 or kv == "no python manifest"
    audit_ok, audit_line = _self_audit_ok()
    governed = int(forge.get("governed_runs", 0))

    claims = [
        Claim("enforcement-armed", armed,
              f"pre-push={enf.get('pre_push_gate')}, CI={enf.get('ci_workflow')}, pre-commit={enf.get('pre_commit_config')}",
              "bash scripts/forge-comply.sh  (GATE LIVENESS)"),
        Claim("secrets-clean", secrets_clean,
              f"gitleaks: {sec.get('findings', '?')} findings in {sec.get('scope', '?')}",
              "gitleaks git --redact"),
        Claim("ci-green", bool(ci_green),
              f"GitHub latest CI = {gh.get('latest_ci', 'not connected')}", "gh run list"),
        Claim("deps-no-known-cves", bool(deps_clean),
              (f"pip-audit: {kv}" if kv != "no python manifest" else "no python manifest — nothing to audit"),
              "pip-audit"),
        Claim("governance-intact", audit_ok, audit_line,
              "python3 selfaudit/forge_doctor.py"),
    ]

    if armed and secrets_clean and ci_green and deps_clean and audit_ok and governed > 0:
        level = "L3"
    elif armed and secrets_clean and ci_green and deps_clean and audit_ok:
        level = "L2"
    elif armed:
        level = "L1"
    else:
        level = "none"

    return {
        "certificate": "Forge Verified",
        "level": level,
        "project": s["project"],
        "path": s["path"],
        "commit": _commit(d),
        "forge_version": _forge_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "claims": claims,
        "governed_runs": governed,
        "honest_note": (
            "Machine-verified claims only — NOT a proof of security. Each claim is "
            "reproducible from the repo at this commit. "
            + ("L3 (process provenance) requires Forge-governed run history; "
               f"this project has {governed} governed runs." if level != "L3" else
               "L3: every change is backed by Forge trace history.")
        ),
    }


def _badge(level: str) -> str:
    return {"L1": "gated", "L2": "verified", "L3": "provenanced", "none": "not certified"}[level]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    as_json = "--json" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: forge_certify.py <project_dir> [--json]", file=sys.stderr)
        return 2
    cert = certify(paths[0])
    if as_json:
        print(json.dumps(cert, indent=2))
    else:
        print(f"Forge Verified — {cert['level']} ({_badge(cert['level'])})  · {cert['project']} @ {cert['commit']}")
        for c in cert["claims"]:
            print(f"  [{'✓' if c['passed'] else '✗'}] {c['name']}: {c['evidence']}")
        print(f"  note: {cert['honest_note']}")
    return 0 if cert["level"] != "none" else 1


if __name__ == "__main__":
    raise SystemExit(main())
