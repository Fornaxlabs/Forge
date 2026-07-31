"""Behavior tests for status/forge_status.py — the read-only status collector.

Pure logic (_NOISE_RE, _is_valid_trace) is tested directly. Probes that shell
out (gitleaks, pip-audit, gh) are exercised through the REAL subprocess path by
placing controlled fake executables on PATH — the parsing/degradation code under
test is the genuine module code, never a mock of it. Nothing here needs network.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

_P = Path(__file__).resolve().parent.parent / "status" / "forge_status.py"
_spec = importlib.util.spec_from_file_location("forge_status_under_test", _P)
assert _spec and _spec.loader
fs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fs)

# System dirs that must stay on PATH so git/python3 keep working while the
# fake tools shadow (or hide) gitleaks/gh/pip-audit.
_SYS_PATH = "/usr/bin:/bin"


def _fake_tool(bindir: Path, name: str, body: str) -> None:
    """Write an executable python script `name` into bindir."""
    bindir.mkdir(parents=True, exist_ok=True)
    p = bindir / name
    p.write_text("#!/usr/bin/env python3\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _fake_gitleaks(
    bindir: Path, findings: list[dict[str, str]] | str, exit_code: int = 0
) -> None:
    """A gitleaks stand-in that writes the given findings to --report-path.
    Pass a raw string to produce a malformed report; exit_code mimics the real
    tool (0 = clean, 1 = leaks found / scan error)."""
    payload = findings if isinstance(findings, str) else json.dumps(findings)
    _fake_tool(
        bindir,
        "gitleaks",
        "import sys\n"
        "args = sys.argv[1:]\n"
        "rep = args[args.index('--report-path') + 1]\n"
        f"open(rep, 'w').write({json.dumps(payload)})\n"
        f"sys.exit({int(exit_code)})\n",
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _make_repo(d: Path, commit: bool = True) -> None:
    _git(d, "init", "-q")
    if commit:
        (d / "f.txt").write_text("hello\n")
        _git(d, "add", ".")
        _git(d, "commit", "-qm", "init commit")


# ---------------------------------------------------------------------------
# _NOISE_RE — vendored/data/binary noise vs real source
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "node_modules/lib/index.js",
        "vendor/pkg/mod.go",
        "dist/bundle.js",
        "data/dataset.csv",
        "fixtures/sample.json",
        "app/static/app.min.js",
        "img/logo.png",
        "docs/report.pdf",
        "Cargo.lock",
        "a/b/__pycache__/m.pyc",
        ".venv/lib/python3.11/site-packages/x.py",
    ],
)
def test_noise_re_matches_vendored_and_binary(path: str) -> None:
    assert fs._NOISE_RE.search(path) is not None


@pytest.mark.parametrize(
    "path",
    [
        "src/app.py",
        "hooks/guard.py",
        "config/settings.yaml",
        "README.md",
        "mydata_loader.py",  # "data" only matches as a path segment
        "distribution/notes.txt",  # "dist" only matches as a path segment
    ],
)
def test_noise_re_passes_real_source(path: str) -> None:
    assert fs._NOISE_RE.search(path) is None


# ---------------------------------------------------------------------------
# _is_valid_trace — a governed run needs run_start AND run_end
# ---------------------------------------------------------------------------
def test_is_valid_trace_full(tmp_path: Path) -> None:
    p = tmp_path / "run.jsonl"
    p.write_text(
        json.dumps({"event": "run_start", "task": "t"})
        + "\n"
        + json.dumps({"event": "stage", "stage": "BUILD"})
        + "\n"
        + json.dumps({"event": "run_end", "outcome": "green"})
        + "\n"
    )
    assert fs._is_valid_trace(str(p)) is True


def test_is_valid_trace_partial_and_empty(tmp_path: Path) -> None:
    only_start = tmp_path / "start.jsonl"
    only_start.write_text(json.dumps({"event": "run_start"}) + "\n")
    assert fs._is_valid_trace(str(only_start)) is False

    empty = tmp_path / "empty.jsonl"  # `touch fake.jsonl` must not count
    empty.write_text("")
    assert fs._is_valid_trace(str(empty)) is False


def test_is_valid_trace_malformed_and_missing(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"event": "run_start"}\nnot json at all\n')
    assert fs._is_valid_trace(str(bad)) is False  # ValueError -> invalid
    assert fs._is_valid_trace(str(tmp_path / "nope.jsonl")) is False


# ---------------------------------------------------------------------------
# probe_enforcement — gate files on a real tmp directory
# ---------------------------------------------------------------------------
def test_probe_enforcement_empty_dir(tmp_path: Path) -> None:
    enf = fs.probe_enforcement(str(tmp_path))
    assert set(enf) == {
        "pre_commit_config",
        "pre_commit_installed",
        "pre_push_gate",
        "ci_workflow",
        "gitleaks_allowlist",
        "plan_mode_first",
    }
    assert not any(enf.values())


def test_probe_enforcement_fully_armed(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\n")
    (hooks / "pre-push").write_text("#!/bin/sh\n")
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: ci\n")
    (tmp_path / ".gitleaks.toml").write_text("[allowlist]\n")
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"permissions": {"defaultMode": "plan"}})
    )
    enf = fs.probe_enforcement(str(tmp_path))
    assert all(enf.values()), enf


def test_probe_enforcement_workflow_dir_without_yml(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "README.md").write_text("no workflows\n")
    assert fs.probe_enforcement(str(tmp_path))["ci_workflow"] is False


def test_probe_enforcement_plan_mode_not_plan_or_corrupt(tmp_path: Path) -> None:
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"permissions": {"defaultMode": "acceptEdits"}})
    )
    assert fs.probe_enforcement(str(tmp_path))["plan_mode_first"] is False
    (claude / "settings.json").write_text("{corrupt")
    assert fs.probe_enforcement(str(tmp_path))["plan_mode_first"] is False


# ---------------------------------------------------------------------------
# probe_forge — counts only VALID traces in .forge/runs
# ---------------------------------------------------------------------------
def test_probe_forge_not_installed(tmp_path: Path) -> None:
    out = fs.probe_forge(str(tmp_path))
    assert out["installed"] is False
    assert out["governed_runs"] == 0
    assert out["note"]  # honest empty-state note present


def test_probe_forge_counts_only_valid_traces(tmp_path: Path) -> None:
    runs = tmp_path / ".forge" / "runs"
    runs.mkdir(parents=True)
    (runs / "good.jsonl").write_text(
        json.dumps({"event": "run_start"})
        + "\n"
        + json.dumps({"event": "run_end"})
        + "\n"
    )
    (runs / "fake.jsonl").write_text("")  # touched file
    (runs / "partial.jsonl").write_text(
        json.dumps({"event": "run_start"}) + "\n"
    )  # no run_end
    (runs / "notes.txt").write_text("not a trace\n")  # wrong extension
    out = fs.probe_forge(str(tmp_path))
    assert out["installed"] is True
    assert out["governed_runs"] == 1
    assert out["note"] is None


# ---------------------------------------------------------------------------
# probe_tests — counting test files, skipping vendored trees
# ---------------------------------------------------------------------------
def test_probe_tests_counts_and_skips_vendored(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("")
    (tmp_path / "b_test.py").write_text("")
    (tmp_path / "helper.py").write_text("")
    skipped = tmp_path / "node_modules" / "pkg"
    skipped.mkdir(parents=True)
    (skipped / "test_vendored.py").write_text("")
    out = fs.probe_tests(str(tmp_path))
    assert out["test_files"] == 2
    assert "not measured" in out["coverage"]  # honest: collector never runs tests


# ---------------------------------------------------------------------------
# probe_git — real git repos in tmp dirs
# ---------------------------------------------------------------------------
def test_probe_git_no_remote(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    g = fs.probe_git(str(tmp_path))
    assert g["has_remote"] is False
    assert g["remote"] is None
    assert g["branch"]  # real branch name from git
    assert g["last_commit"] == "init commit"
    assert g["uncommitted_files"] == 0


def test_probe_git_remote_and_uncommitted(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    _git(tmp_path, "remote", "add", "origin", "git@example.invalid:x/y.git")
    (tmp_path / "dirty.txt").write_text("wip\n")
    g = fs.probe_git(str(tmp_path))
    assert g["has_remote"] is True
    assert g["remote"] == "git@example.invalid:x/y.git"
    assert g["uncommitted_files"] == 1


def test_probe_git_non_repo_dir_reports_blanks_not_stderr(tmp_path: Path) -> None:
    """Outside a git repo every git call fails; the probe must report clean
    blank/zero values — never git's stderr text as data."""
    g = fs.probe_git(str(tmp_path))
    assert g["branch"] == ""
    assert g["last_commit"] == ""
    assert g["last_commit_ago"] == ""
    assert g["uncommitted_files"] == 0
    assert g["has_remote"] is False
    assert g["remote"] is None
    assert not any("fatal" in str(v) for v in g.values())


def test_probe_git_repo_without_commits(tmp_path: Path) -> None:
    """A freshly-initialised repo has no commits: git log fails, but that is
    'no commit yet', not data — and an untracked file still counts as dirty."""
    _make_repo(tmp_path, commit=False)
    (tmp_path / "new.txt").write_text("wip\n")
    g = fs.probe_git(str(tmp_path))
    assert g["last_commit"] == ""  # never "fatal: ... no commits yet"
    assert g["last_commit_ago"] == ""
    assert "fatal" not in g["branch"]  # the unborn branch name, or blank
    assert g["uncommitted_files"] == 1  # git status works pre-first-commit
    assert g["has_remote"] is False


# ---------------------------------------------------------------------------
# _run — degradation contract (never raises)
# ---------------------------------------------------------------------------
def test_run_tool_not_installed(tmp_path: Path) -> None:
    assert fs._run(["definitely-not-a-real-tool-xyz"], str(tmp_path)) == (
        127,
        "tool-not-installed",
    )


def test_run_timeout(tmp_path: Path) -> None:
    rc, out = fs._run(["sleep", "2"], str(tmp_path), timeout=0.05)
    assert (rc, out) == (124, "timeout")


# ---------------------------------------------------------------------------
# _gitleaks_scan — real-vs-noise split via a controlled fake gitleaks
# ---------------------------------------------------------------------------
def test_gitleaks_scan_splits_real_from_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_gitleaks(
        bindir,
        [
            {"File": "src/config.py"},  # real
            {"File": "node_modules/lib/blob.js"},  # noise
            {"File": "data\\fixtures.csv"},  # noise (backslash path)
            {"File": "assets/logo.png"},  # noise
        ],
    )
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    out = fs._gitleaks_scan(["gitleaks", "git"], str(tmp_path), timeout=30)
    assert out == {"real": 1, "noise": 3}


def test_gitleaks_scan_not_installed_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert fs._gitleaks_scan(["gitleaks", "git"], str(tmp_path), timeout=5) is None


def test_gitleaks_scan_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(bindir, "gitleaks", "import time\ntime.sleep(5)\n")
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    assert (
        fs._gitleaks_scan(["gitleaks", "git"], str(tmp_path), timeout=0.2) == "timeout"
    )


def test_gitleaks_scan_malformed_report_with_error_rc_is_never_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan FAILED (rc != 0) and left no readable report: that must surface
    as an error status — reporting {"real": 0} here would fail open into the
    certificate's secrets-clean claim."""
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, "{not json", exit_code=1)
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    out = fs._gitleaks_scan(["gitleaks", "git"], str(tmp_path), timeout=30)
    assert out == "error (rc 1)"  # honest degradation, NOT a clean zero count


def test_gitleaks_scan_malformed_report_with_rc_zero_counts_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rc == 0 is gitleaks' own 'no leaks found' verdict; an unreadable report
    then yields zero counts (the tool succeeded, there is nothing to count)."""
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, "{not json", exit_code=0)
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    assert fs._gitleaks_scan(["gitleaks", "git"], str(tmp_path), timeout=30) == {
        "real": 0,
        "noise": 0,
    }


def test_gitleaks_scan_rc_one_with_readable_report_counts_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rc == 1 with a valid report is the normal 'leaks found' path — counted,
    not treated as an error."""
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, [{"File": "src/leaked.py"}], exit_code=1)
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    assert fs._gitleaks_scan(["gitleaks", "git"], str(tmp_path), timeout=30) == {
        "real": 1,
        "noise": 0,
    }


# ---------------------------------------------------------------------------
# probe_secrets — commit-scoped scan behavior
# ---------------------------------------------------------------------------
def test_probe_secrets_tool_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert fs.probe_secrets(str(tmp_path), history=False) == {
        "tool": "gitleaks",
        "status": "not installed",
    }


def test_probe_secrets_no_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, [])
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    _make_repo(tmp_path, commit=False)
    out = fs.probe_secrets(str(tmp_path), history=False)
    assert out["status"] == "no commits to scan"


def test_probe_secrets_findings_and_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_gitleaks(
        bindir,
        [
            {"File": "src/leaked.py"},
            {"File": "vendor/x.js"},
        ],
    )
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    _make_repo(tmp_path)
    (tmp_path / ".gitleaks.toml").write_text("[allowlist]\n")
    out = fs.probe_secrets(str(tmp_path), history=False)
    assert out["scope"] == "full history"  # 1 commit <= 50
    assert out["findings"] == 1
    assert out["noise_excluded"] == 1
    assert out["clean"] is False
    assert out["allowlist"] is True
    assert out["pre_push_gate"] is False


def test_probe_secrets_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, [])
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    _make_repo(tmp_path)
    out = fs.probe_secrets(str(tmp_path), history=False)
    assert out["findings"] == 0
    assert out["clean"] is True


def test_probe_secrets_scan_error_is_status_not_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gitleaks exits non-zero AND leaves an unreadable report: probe_secrets
    must degrade to a status record with NO 'clean' key — never a clean scan."""
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, "{corrupt", exit_code=2)
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    _make_repo(tmp_path)
    out = fs.probe_secrets(str(tmp_path), history=False)
    assert "clean" not in out
    assert "findings" not in out
    assert "error (rc 2)" in out["status"]


# ---------------------------------------------------------------------------
# probe_deps — manifest detection + pip-audit result parsing
# ---------------------------------------------------------------------------
def test_probe_deps_no_manifest(tmp_path: Path) -> None:
    assert fs.probe_deps(str(tmp_path)) == {
        "manifest": None,
        "known_vulns": "no python manifest",
    }


def test_probe_deps_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(bindir, "pip-audit", "print('No known vulnerabilities found')\n")
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    (tmp_path / "requirements.txt").write_text("requests==2.0.0\n")
    out = fs.probe_deps(str(tmp_path))
    assert out == {"manifest": "requirements.txt", "known_vulns": 0}


def test_probe_deps_vulns_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(
        bindir,
        "pip-audit",
        "import sys\nprint('somepkg 1.0.0 CVE-2024-0001')\nsys.exit(1)\n",
    )
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    out = fs.probe_deps(str(tmp_path))
    assert out["manifest"] == "pyproject.toml"
    assert out["known_vulns"] == "see pip-audit"


def test_probe_deps_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(bindir, "pip-audit", "import sys\nprint('error!')\nsys.exit(1)\n")
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    (tmp_path / "requirements.txt").write_text("ghost-pkg==0.0.1\n")
    assert fs.probe_deps(str(tmp_path))["known_vulns"] == "could not resolve"


# ---------------------------------------------------------------------------
# probe_github — CI bound to HEAD, not "latest run anywhere"
# ---------------------------------------------------------------------------
def test_probe_github_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert fs.probe_github(str(tmp_path)) == {
        "connected": False,
        "reason": "gh not installed",
    }


_FAKE_GH_CONNECTED = """\
import json, subprocess, sys
args = sys.argv[1:]
if args and args[0] == "pr":
    print(json.dumps([{"number": 1, "title": "add auth"}]))
elif args and args[0] == "run":
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    print(json.dumps([
        {"headSha": "aaaa000", "status": "completed", "conclusion": "failure"},
        {"headSha": head, "status": "completed", "conclusion": "success"},
    ]))
"""


def test_probe_github_binds_ci_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(bindir, "gh", _FAKE_GH_CONNECTED)
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    _make_repo(tmp_path)
    out = fs.probe_github(str(tmp_path))
    assert out["connected"] is True
    assert out["open_prs"] == 1
    assert out["pr_titles"] == ["add auth"]
    # the failure run on another sha must NOT vouch — HEAD's own run wins
    assert out["latest_ci"] == "success"
    assert len(out["ci_commit"]) == 12


def test_probe_github_no_run_for_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(
        bindir,
        "gh",
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "print(json.dumps([] if args and args[0] == 'pr' else "
        "[{'headSha': 'not-head', 'conclusion': 'success'}]))\n",
    )
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    _make_repo(tmp_path)
    out = fs.probe_github(str(tmp_path))
    assert out["connected"] is True
    assert out["latest_ci"] == "no run for HEAD"  # green elsewhere never vouches


def test_probe_github_gh_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    _fake_tool(bindir, "gh", "import sys\nsys.exit(1)\n")
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")
    out = fs.probe_github(str(tmp_path))
    assert out["connected"] is False


# ---------------------------------------------------------------------------
# collect + main — the full record and CLI surface
# ---------------------------------------------------------------------------
def _fake_all_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = tmp_path / "bin"
    _fake_gitleaks(bindir, [])
    _fake_tool(bindir, "pip-audit", "print('No known vulnerabilities found')\n")
    _fake_tool(bindir, "gh", _FAKE_GH_CONNECTED)
    monkeypatch.setenv("PATH", f"{bindir}:{_SYS_PATH}")


def test_collect_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_all_tools(tmp_path, monkeypatch)
    _make_repo(tmp_path)
    s = fs.collect(str(tmp_path))
    assert s["project"] == tmp_path.name
    assert s["path"] == str(tmp_path)
    for key in ("git", "github", "secrets", "enforcement", "tests", "deps", "forge"):
        assert key in s
    assert s["secrets"]["clean"] is True
    assert s["forge"]["governed_runs"] == 0


def test_main_json_and_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_all_tools(tmp_path, monkeypatch)
    _make_repo(tmp_path)
    assert fs.main([str(tmp_path), "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["project"] == tmp_path.name

    assert fs.main([str(tmp_path)]) == 0
    text = capsys.readouterr().out
    assert tmp_path.name in text
    assert "gates" in text

    assert fs.main([]) == 2  # usage error


def test_fmt_findings_line() -> None:
    s: dict[str, Any] = {
        "project": "p",
        "path": "/p",
        "git": {
            "branch": "main",
            "last_commit": "x",
            "last_commit_ago": "1h",
            "uncommitted_files": 0,
            "has_remote": False,
            "remote": None,
        },
        "github": {"connected": False, "reason": "gh not installed"},
        "secrets": {
            "tool": "gitleaks",
            "scope": "full history",
            "findings": 3,
            "noise_excluded": 0,
            "clean": False,
            "allowlist": False,
            "pre_push_gate": False,
        },
        "enforcement": dict.fromkeys(
            (
                "pre_commit_config",
                "pre_commit_installed",
                "pre_push_gate",
                "ci_workflow",
                "gitleaks_allowlist",
                "plan_mode_first",
            ),
            False,
        ),
        "tests": {"test_files": 0, "coverage": "not measured"},
        "deps": {"manifest": None, "known_vulns": "no python manifest"},
        "forge": {"installed": False, "governed_runs": 0, "note": "empty"},
    }
    text = fs._fmt(s)
    assert "3 finding(s) in full history" in text
    assert "0/6 armed" in text
