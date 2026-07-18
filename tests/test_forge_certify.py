"""Behavior tests for status/forge_certify.py — the claim-manifest assembler.

certify() is fed a synthetic pre-collected status dict (its documented API for
skipping the slow probes), so every level decision below is the real logic.
Only _self_audit_ok is monkeypatched — it subprocesses the full self-audit,
which is covered by its own test suite.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_P = Path(__file__).resolve().parent.parent / "status" / "forge_certify.py"
_spec = importlib.util.spec_from_file_location("forge_certify_under_test", _P)
assert _spec and _spec.loader
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

_REAL_SELF_AUDIT = fc._self_audit_ok  # kept before the autouse fixture patches it

_CLAIM_NAMES = ["enforcement-armed", "secrets-clean", "ci-green",
                "deps-no-known-cves", "governance-intact"]


def _status(*, armed: bool = True, clean: bool = True, ci: str = "success",
            kv: object = 0, runs: int = 0, connected: bool = True) -> dict[str, Any]:
    return {
        "project": "proj", "path": "/tmp/proj",
        "collected_at": "2026-07-18T00:00:00+00:00",
        "git": {"branch": "main", "last_commit": "x", "last_commit_ago": "1h",
                "uncommitted_files": 0, "has_remote": True,
                "remote": "git@example.invalid:x/y.git"},
        "github": ({"connected": True, "open_prs": 0, "pr_titles": [],
                    "latest_ci": ci, "ci_commit": "abcdef123456"}
                   if connected else {"connected": False, "reason": "gh not installed"}),
        "secrets": {"tool": "gitleaks", "scope": "full history",
                    "findings": 0 if clean else 2, "noise_excluded": 0,
                    "clean": clean, "allowlist": True, "pre_push_gate": armed},
        "enforcement": {"pre_commit_config": armed, "pre_commit_installed": armed,
                        "pre_push_gate": armed, "ci_workflow": armed,
                        "gitleaks_allowlist": armed, "plan_mode_first": armed},
        "tests": {"test_files": 1, "coverage": "not measured"},
        "deps": {"manifest": None if kv == "no python manifest" else "pyproject.toml",
                 "known_vulns": kv},
        "forge": {"installed": True, "governed_runs": runs, "note": None},
    }


@pytest.fixture(autouse=True)
def _audit_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fc, "_self_audit_ok", lambda: (True, "self-audit: all gates OK"))


def test_l2_all_green_no_governed_runs(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status())
    assert cert["level"] == "L2"
    assert cert["certificate"] == "Forge Verified"
    assert cert["governed_runs"] == 0
    assert all(c["passed"] for c in cert["claims"])
    assert "0 governed runs" in cert["honest_note"]  # honest: why not L3


def test_l3_requires_governed_runs(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status(runs=3))
    assert cert["level"] == "L3"
    assert cert["governed_runs"] == 3
    assert "trace history" in cert["honest_note"]


def test_l1_armed_but_secrets_dirty(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status(clean=False))
    assert cert["level"] == "L1"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["enforcement-armed"]["passed"] is True
    assert by_name["secrets-clean"]["passed"] is False
    assert "2 findings" in by_name["secrets-clean"]["evidence"]


def test_secrets_scan_error_blocks_l2(tmp_path: Path) -> None:
    """A failed/unknown secrets scan (status record, no 'clean' key) must never
    count as secrets-clean: the certificate stays at L1, not L2."""
    status = _status()
    status["secrets"] = {"tool": "gitleaks",
                         "status": "error (rc 1) (scope: full history)",
                         "scope": "full history"}
    cert = fc.certify(str(tmp_path), status=status)
    assert cert["level"] == "L1"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["secrets-clean"]["passed"] is False


def test_none_when_not_armed(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status(armed=False))
    assert cert["level"] == "none"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["enforcement-armed"]["passed"] is False


def test_ci_failure_blocks_l2(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status(ci="failure"))
    assert cert["level"] == "L1"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["ci-green"]["passed"] is False


def test_github_not_connected_blocks_l2(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status(connected=False))
    assert cert["level"] == "L1"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["ci-green"]["passed"] is False
    assert "not connected" in by_name["ci-green"]["evidence"]


def test_deps_no_manifest_passes(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status(kv="no python manifest"))
    assert cert["level"] == "L2"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["deps-no-known-cves"]["passed"] is True
    assert "nothing to audit" in by_name["deps-no-known-cves"]["evidence"]


@pytest.mark.parametrize("kv", [
    "pip-audit not installed",
    "timed out (deps not resolvable offline)",
    "see pip-audit",
    "could not resolve",
    3,
])
def test_deps_error_or_vulns_fail(tmp_path: Path, kv: object) -> None:
    cert = fc.certify(str(tmp_path), status=_status(kv=kv))
    assert cert["level"] == "L1"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["deps-no-known-cves"]["passed"] is False


def test_tampered_governance_blocks_l2(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fc, "_self_audit_ok",
                        lambda: (False, "TAMPERED: guard hook missing"))
    cert = fc.certify(str(tmp_path), status=_status())
    assert cert["level"] == "L1"
    by_name = {c["name"]: c for c in cert["claims"]}
    assert by_name["governance-intact"]["passed"] is False
    assert by_name["governance-intact"]["evidence"] == "TAMPERED: guard hook missing"


def test_claims_list_names_and_reproduce_commands(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status())
    assert [c["name"] for c in cert["claims"]] == _CLAIM_NAMES
    for c in cert["claims"]:
        assert c["reproduce"]  # every claim carries a reproduce command
        assert c["evidence"]


def test_commit_unknown_outside_a_repo(tmp_path: Path) -> None:
    cert = fc.certify(str(tmp_path), status=_status())
    assert cert["commit"] == "unknown"  # honest, never fabricated


def test_badge_mapping() -> None:
    assert fc._badge("L1") == "gated"
    assert fc._badge("L2") == "verified"
    assert fc._badge("L3") == "provenanced"
    assert fc._badge("none") == "not certified"


def test_forge_version_read_from_plugin_manifest() -> None:
    v = fc._forge_version()
    assert v and v != "?"  # the real plugin.json ships a version


def test_real_self_audit_passes_on_the_shipped_checkout() -> None:
    """The unpatched self-audit runs the real forge_doctor subprocess against
    the real plugin checkout. The shipped checkout IS healthy — forge_doctor
    passing here is the contract, so a mere isinstance check would be vacuous
    (it would pass on a failing audit or a wrong plugin path)."""
    ok, line = _REAL_SELF_AUDIT()
    assert ok is True, f"self-audit failed on the shipped checkout: {line}"
    assert "verdict: OK" in line


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------
def test_main_json_and_human(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(fc.forge_status, "collect",
                        lambda d, history=False: _status())
    assert fc.main([str(tmp_path), "--json"]) == 0
    cert = json.loads(capsys.readouterr().out)
    assert cert["level"] == "L2"

    assert fc.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Forge Verified — L2 (verified)" in out
    assert "[✓] enforcement-armed" in out

    assert fc.main([]) == 2  # usage error


def test_main_exit_one_when_not_certified(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(fc.forge_status, "collect",
                        lambda d, history=False: _status(armed=False))
    assert fc.main([str(tmp_path)]) == 1
    assert "not certified" in capsys.readouterr().out
