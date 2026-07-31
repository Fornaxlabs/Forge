"""Behavior tests for status/render_dashboard.py — the 3-tab HTML dashboard.

render() is called on synthetic collector-shaped records and the REAL output
HTML is asserted: verdict wording, escaping of every attacker-influenced string
field, honest empty/uncomputed states, and the zero-external-request contract.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

_P = Path(__file__).resolve().parent.parent / "status" / "render_dashboard.py"
_spec = importlib.util.spec_from_file_location("render_dashboard_under_test", _P)
assert _spec and _spec.loader
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)

NOW = "2026-07-18T09:00:00+00:00"
XSS = "<script>alert('pwn')</script>\"><img src=x onerror=alert(2)>"


def _proj(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "project": "myproj",
        "path": "/home/u/myproj",
        "collected_at": NOW,
        "git": {
            "branch": "main",
            "last_commit": "feat: add thing",
            "last_commit_ago": "2 hours ago",
            "uncommitted_files": 0,
            "has_remote": True,
            "remote": "git@example.invalid:u/myproj.git",
        },
        "github": {"connected": False, "reason": "gh not installed"},
        "secrets": {
            "tool": "gitleaks",
            "scope": "full history",
            "findings": 0,
            "noise_excluded": 0,
            "clean": True,
            "allowlist": True,
            "pre_push_gate": True,
            "note": "quick scan note",
        },
        "enforcement": {
            "pre_commit_config": True,
            "pre_commit_installed": True,
            "pre_push_gate": True,
            "ci_workflow": True,
            "gitleaks_allowlist": True,
            "plan_mode_first": True,
        },
        "tests": {"test_files": 4, "coverage": "not measured"},
        "deps": {"manifest": None, "known_vulns": "no python manifest"},
        "forge": {"installed": True, "governed_runs": 1, "note": None},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k] = {**p[k], **v}
        else:
            p[k] = v
    return p


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------
def test_renders_all_projects_and_fleet() -> None:
    out = rd.render(
        [_proj(project="alpha", path="/a"), _proj(project="beta", path="/b")], NOW
    )
    assert "alpha" in out and "beta" in out
    assert '<option value="0">' in out and '<option value="1">' in out
    assert "All projects (fleet)" in out
    assert NOW in out  # collected-at stamp shown


def test_audit_tab_present_and_honest_when_no_runs() -> None:
    """The Audit tab must exist (the UI must tell the same story as forge_audit)
    and must NOT invent evidence when a project has no governed runs."""
    html = rd.render([_proj()], NOW)
    assert 'id="tab-audit"' in html and 'id="panel-audit"' in html
    assert "No governed runs recorded yet" in html


def test_audit_tab_reports_real_run_evidence() -> None:
    runs = [
        {
            "task": "add auth",
            "triage": "LARGE",
            "human_approved": True,
            "verified": True,
            "forced_close": False,
            "outcome": "green",
            "run_id": "r1",
        },
        {
            "task": "hotfix",
            "triage": "SMALL",
            "human_approved": False,
            "verified": False,
            "forced_close": True,
            "outcome": "green",
            "run_id": "r2",
        },
    ]
    html = rd.render([_proj(audit_runs=runs)], NOW)
    assert "governance evidence (2 runs)" in html
    assert "add auth" in html and "hotfix" in html
    assert "FORCED" in html  # an unverified close is surfaced, never hidden
    assert "forge_audit.py" in html  # points at the CLI export for auditors


def test_audit_tab_escapes_run_fields() -> None:
    runs = [
        {
            "task": "<img src=x onerror=alert(1)>",
            "triage": '"><b>',
            "human_approved": True,
            "verified": True,
            "forced_close": False,
            "outcome": "green",
            "run_id": "r",
        }
    ]
    html = rd.render([_proj(audit_runs=runs)], NOW)
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_empty_input_is_honest() -> None:
    out = rd.render([], NOW)
    assert "no projects collected" in out


# ---------------------------------------------------------------------------
# escaping — XSS payload in every attacker-influenced string field
# ---------------------------------------------------------------------------
def test_xss_escaped_in_every_string_field() -> None:
    p = _proj(
        project=XSS,
        path=XSS,
        git={
            "branch": XSS,
            "last_commit": XSS,
            "last_commit_ago": XSS,
            "remote": XSS,
            "has_remote": True,
        },
        github={"connected": False, "reason": XSS},
        secrets={"scope": XSS, "note": XSS},
        deps={"manifest": XSS, "known_vulns": XSS},
        forge={"installed": True, "governed_runs": 0, "note": XSS},
    )
    p["certificate"] = {
        "level": "L1",
        "commit": XSS,
        "governed_runs": 0,
        "generated_at": NOW,
        "honest_note": XSS,
        "claims": [{"name": XSS, "passed": False, "evidence": XSS, "reproduce": XSS}],
    }
    p["runs"] = [
        {
            "run_id": XSS,
            "task": XSS,
            "started": XSS,
            "outcome": XSS,
            "events": 2,
            "href": XSS,
        }
    ]
    out = rd.render([p], XSS)
    assert "<script>alert" not in out
    assert "<img src=x" not in out
    assert "&lt;script&gt;alert" in out  # payload present, but escaped


def test_xss_escaped_in_connected_github_fields() -> None:
    """PR titles are attacker-influenced (anyone can open a PR); the CI value
    and bound commit come from `gh` output. All must be escaped on the
    connected-GitHub render path too."""
    p = _proj(
        github={
            "connected": True,
            "open_prs": 1,
            "pr_titles": [XSS],
            "latest_ci": XSS,
            "ci_commit": XSS,
        }
    )
    out = rd.render([p], NOW)
    assert "<script>alert" not in out
    assert "<img src=x" not in out
    assert "&lt;script&gt;alert" in out  # payload present, but escaped


def test_xss_never_breaks_out_of_attributes() -> None:
    p = _proj()
    p["runs"] = [
        {
            "run_id": "r",
            "task": "t",
            "started": "",
            "outcome": "green",
            "events": 2,
            "href": '"><script>alert(3)</script>',
        }
    ]
    out = rd.render([p], NOW)
    assert '"><script>alert(3)' not in out
    assert "&quot;&gt;&lt;script&gt;alert(3)" in out


# ---------------------------------------------------------------------------
# verdict logic — findings > gates > healthy
# ---------------------------------------------------------------------------
def test_verdict_needs_attention_on_findings() -> None:
    out = rd.render([_proj(secrets={"findings": 2, "clean": False})], NOW)
    assert "Needs attention" in out
    assert "2 possible secret(s) in committed history" in out  # top fix


def test_verdict_under_protected_without_pre_push() -> None:
    out = rd.render([_proj(enforcement={"pre_push_gate": False})], NOW)
    assert "Under-protected" in out
    assert "Pre-push secret gate is not installed" in out


def test_verdict_healthy_when_armed_and_clean() -> None:
    out = rd.render([_proj()], NOW)
    assert "Protected" in out
    assert "Needs attention" not in out
    assert "nothing needs you" in out  # no fixes fabricated


# ---------------------------------------------------------------------------
# honesty
# ---------------------------------------------------------------------------
def test_honest_labels_present() -> None:
    out = rd.render([_proj()], NOW)
    assert "Not built yet" in out  # unbuilt features never faked
    assert "full history" in out  # secrets scope always shown
    assert "not measured" in out  # coverage honesty
    assert "--redact" in out  # no secret values read


def test_certificate_not_computed_never_fakes_a_level() -> None:
    out = rd.render([_proj()], NOW)  # no "certificate" key at all
    assert "not computed" in out
    assert "Certificate not computed" in out
    assert "Forge Verified — Gated" not in out
    assert "Forge Verified — Verified" not in out
    assert "Forge Verified — Provenanced" not in out


def test_certificate_levels_render() -> None:
    base = _proj()
    base["certificate"] = {
        "level": "L3",
        "claims": [
            {
                "name": "enforcement-armed",
                "passed": True,
                "evidence": "e",
                "reproduce": "r",
            }
        ],
        "governed_runs": 2,
        "commit": "abc123",
        "generated_at": NOW,
        "honest_note": "note",
    }
    out = rd.render([base], NOW)
    assert "Forge Verified — Provenanced" in out
    assert "1/1 claims pass" in out

    none = _proj()
    none["certificate"] = {
        "level": "none",
        "claims": [],
        "governed_runs": 0,
        "commit": "abc",
        "generated_at": NOW,
        "honest_note": "n",
    }
    out2 = rd.render([none], NOW)
    assert "Not certified" in out2


# ---------------------------------------------------------------------------
# runs card — real traces only, honest empty states
# ---------------------------------------------------------------------------
def test_runs_absent_vs_empty_vs_linked() -> None:
    absent = rd.render([_proj()], NOW)  # no "runs" key: discovery never ran
    assert "not discovered" in absent

    empty = _proj()
    empty["runs"] = []
    out_empty = rd.render([empty], NOW)
    assert "No governed runs yet" in out_empty

    linked = _proj()
    linked["runs"] = [
        {
            "run_id": "2026-07-18-084238-refund",
            "task": "Add refund endpoint",
            "started": NOW,
            "outcome": "escalated",
            "events": 16,
            "href": "pipeline-myproj-refund.html",
        }
    ]
    out = rd.render([linked], NOW)
    assert 'href="pipeline-myproj-refund.html"' in out
    assert "view pipeline" in out
    assert "escalated" in out

    unlinked = _proj()
    unlinked["runs"] = [
        {"run_id": "r1", "task": "t", "started": "", "outcome": "", "events": 1}
    ]
    out2 = rd.render([unlinked], NOW)
    assert "pipeline page not emitted" in out2
    assert "no run_end" in out2  # missing end shown honestly, not invented


# ---------------------------------------------------------------------------
# gates meter
# ---------------------------------------------------------------------------
def test_gates_meter_counts_and_missing_labels() -> None:
    out = rd.render([_proj()], NOW)
    assert "6 of 6 enforcement gates armed" in out

    two_off = rd.render(
        [_proj(enforcement={"ci_workflow": False, "plan_mode_first": False})], NOW
    )
    assert "4 of 6 enforcement gates armed" in two_off
    assert "CI workflow" in two_off
    assert "plan-mode first" in two_off


# ---------------------------------------------------------------------------
# guard tester — drift protection for the hand-ported JS deny rules
# ---------------------------------------------------------------------------
def test_guard_tester_js_covers_every_guard_deny_concept() -> None:
    """The Configure tab's tester is a hand-written JS port of hooks/guard.py's
    deny rules. This pins the port to its source: every literal token of every
    _STATIC_DENY pattern, plus the structural-rule keywords, must appear in the
    rendered page's script — so a new guard rule the JS forgot fails here."""
    guard_path = Path(__file__).resolve().parent.parent / "hooks" / "guard.py"
    spec = importlib.util.spec_from_file_location("guard_for_drift_check", guard_path)
    assert spec and spec.loader
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)

    out = rd.render([_proj()], NOW)
    js = out[out.rindex("<script>") :]  # the body script (tabs, tester, ...)

    assert guard._STATIC_DENY, "guard deny list unexpectedly empty"
    for pattern in guard._STATIC_DENY:
        # Strip regex escapes (\b, \s, \d, ...) then take the literal words the
        # rule is about — e.g. \bdrop\s+(table|database)\b -> drop/table/database.
        tokens = re.findall(r"[a-z]{2,}", re.sub(r"\\[a-zA-Z]", " ", pattern))
        for token in tokens:
            assert token in js, (
                f"guard.py deny pattern {pattern!r} token {token!r} is missing "
                "from the dashboard tester JS — port has drifted"
            )
    # Structural (multi-condition) rules in guard._segment_denied:
    for token in (
        "rm",
        "--force",
        "--recursive",
        "git",
        "push",
        "--force-with-lease",
        "chmod",
        "777",
        "fork bomb",
        "--no-preserve-root",
    ):
        assert token in js, f"structural guard concept {token!r} missing from tester JS"


# ---------------------------------------------------------------------------
# zero external requests
# ---------------------------------------------------------------------------
def test_no_external_references() -> None:
    out = rd.render(
        [
            _proj(project="alpha", path="/a"),
            _proj(project="beta", path="/b", secrets={"findings": 1, "clean": False}),
        ],
        NOW,
    )
    assert "http://" not in out
    assert "https://" not in out
    assert 'src="' not in out
    assert "@import" not in out
    assert "url(" not in out
