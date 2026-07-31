"""Behavior tests for status/forge_dashboard.py — the collect+certify+render driver.

The slow read-only collector and the self-audit subprocess are replaced with a
prebuilt status (both have their own suites); everything this driver actually
owns — trace discovery, run-id slug sanitisation, pipeline-page emission and
index linking — runs for REAL against tmp_path projects and real HTML output.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_P = _ROOT / "status" / "forge_dashboard.py"
_spec = importlib.util.spec_from_file_location("forge_dashboard_under_test", _P)
assert _spec and _spec.loader
fd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fd)

SAMPLE = (_ROOT / "traces" / "sample-run.jsonl").read_text()


def _prebuilt_status(d: str) -> dict[str, Any]:
    d = os.path.abspath(d)
    return {
        "project": os.path.basename(d),
        "path": d,
        "collected_at": "2026-07-18T09:00:00+00:00",
        "git": {
            "branch": "main",
            "last_commit": "init",
            "last_commit_ago": "1h",
            "uncommitted_files": 0,
            "has_remote": False,
            "remote": None,
        },
        "github": {
            "connected": True,
            "open_prs": 0,
            "pr_titles": [],
            "latest_ci": "success",
            "ci_commit": "abcdef123456",
        },
        "secrets": {
            "tool": "gitleaks",
            "scope": "full history",
            "findings": 0,
            "noise_excluded": 0,
            "clean": True,
            "allowlist": True,
            "pre_push_gate": True,
            "note": "n",
        },
        "enforcement": {
            "pre_commit_config": True,
            "pre_commit_installed": True,
            "pre_push_gate": True,
            "ci_workflow": True,
            "gitleaks_allowlist": True,
            "plan_mode_first": True,
        },
        "tests": {"test_files": 1, "coverage": "not measured"},
        "deps": {"manifest": None, "known_vulns": "no python manifest"},
        "forge": {"installed": True, "governed_runs": 1, "note": None},
    }


@pytest.fixture(autouse=True)
def _fast_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        fd.forge_status, "collect", lambda d, history=False: _prebuilt_status(d)
    )
    monkeypatch.setattr(fd.forge_certify, "_self_audit_ok", lambda: (True, "ok"))


def _project_with_trace(
    tmp_path: Path,
    name: str = "Proj",
    trace: str = SAMPLE,
    fname: str = "2026-07-18-084238-refund.jsonl",
) -> Path:
    proj = tmp_path / name
    runs = proj / ".forge" / "runs"
    runs.mkdir(parents=True)
    (runs / fname).write_text(trace)
    return proj


# ---------------------------------------------------------------------------
# _slug — trace-supplied ids never choose path separators
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("../../evil", "evil"),
        ("..\\..\\win", "win"),
        ("a/b/c", "a_b_c"),
        ("2026-07-18-084238-refund", "2026-07-18-084238-refund"),
        ("", "run"),
        ("../..", "run"),
        ("run id with spaces", "run_id_with_spaces"),
    ],
)
def test_slug_sanitises(raw: str, expected: str) -> None:
    out = fd._slug(raw)
    assert out == expected
    assert "/" not in out and "\\" not in out and ".." not in out


# ---------------------------------------------------------------------------
# discover_runs — real traces only
# ---------------------------------------------------------------------------
def test_discover_runs_finds_real_trace(tmp_path: Path) -> None:
    proj = _project_with_trace(tmp_path)
    runs = proj / ".forge" / "runs"
    (runs / "no-start.jsonl").write_text(
        json.dumps({"event": "tool", "name": "edit"}) + "\n"
    )  # not a run
    (runs / "notes.txt").write_text("irrelevant\n")  # wrong extension
    found = fd.discover_runs(str(proj))
    assert len(found) == 1
    run = found[0]
    assert run["run_id"] == "2026-07-18-084238-refund"
    assert run["task"] == "Add refund endpoint"
    assert run["outcome"] == "escalated"
    assert run["events"] == 16
    assert run["trace_text"].startswith('{"ts"')


def test_discover_runs_empty_and_missing(tmp_path: Path) -> None:
    assert fd.discover_runs(str(tmp_path)) == []  # no .forge at all
    (tmp_path / ".forge" / "runs").mkdir(parents=True)
    assert fd.discover_runs(str(tmp_path)) == []  # empty runs dir


def test_trace_summary_requires_run_start() -> None:
    assert fd._trace_summary([{"event": "tool"}]) is None
    s = fd._trace_summary(
        [{"event": "run_start", "run_id": "r", "task": "t", "ts": "T"}]
    )
    assert s is not None
    assert s["outcome"] == ""  # no run_end -> honest empty string


# ---------------------------------------------------------------------------
# directory mode — pipeline pages emitted and linked from the index
# ---------------------------------------------------------------------------
def test_directory_mode_emits_and_links_pipeline_page(tmp_path: Path) -> None:
    proj = _project_with_trace(tmp_path)
    outdir = tmp_path / "out"
    assert fd.main([str(proj), "-o", str(outdir)]) == 0

    index = (outdir / "index.html").read_text()
    pages = sorted(p.name for p in outdir.glob("pipeline-*.html"))
    assert pages == ["pipeline-Proj-2026-07-18-084238-refund.html"]
    assert f'href="{pages[0]}"' in index  # dashboard links the page
    assert "Add refund endpoint" in index

    page = (outdir / pages[0]).read_text()
    assert "Add refund endpoint" in page  # rendered from the real trace
    assert 'href="index.html"' in page  # links back to the dashboard
    assert ".forge/runs" in page  # provenance: the trace path


def test_zero_runs_is_honest_and_emits_no_pipeline_file(tmp_path: Path) -> None:
    proj = tmp_path / "Empty"
    proj.mkdir()
    outdir = tmp_path / "out"
    assert fd.main([str(proj), "-o", str(outdir)]) == 0
    assert list(outdir.glob("pipeline-*.html")) == []
    index = (outdir / "index.html").read_text()
    assert "No governed runs yet" in index


def test_run_id_path_traversal_is_contained(tmp_path: Path) -> None:
    trace = (
        json.dumps(
            {
                "ts": "2026-07-18T08:00:00+00:00",
                "run_id": "../../evil",
                "event": "run_start",
                "task": "sneaky",
            }
        )
        + "\n"
    )
    proj = _project_with_trace(tmp_path, name="P", trace=trace, fname="t.jsonl")
    outdir = tmp_path / "out"
    before = {p for p in tmp_path.rglob("*")}
    assert fd.main([str(proj), "-o", str(outdir)]) == 0
    created = {p for p in tmp_path.rglob("*")} - before
    # every new file lives INSIDE outdir; nothing escaped via ../..
    assert created and all(outdir in p.parents or p == outdir for p in created)
    pages = [p.name for p in outdir.glob("pipeline-*.html")]
    assert pages == ["pipeline-P-evil.html"]
    assert not (tmp_path / "evil").exists()
    assert not (tmp_path.parent / "evil").exists()


def test_duplicate_run_ids_get_unique_filenames(tmp_path: Path) -> None:
    line = (
        json.dumps(
            {
                "ts": "2026-07-18T08:00:00+00:00",
                "run_id": "same-id",
                "event": "run_start",
                "task": "twin",
            }
        )
        + "\n"
    )
    proj = tmp_path / "Twin"
    runs = proj / ".forge" / "runs"
    runs.mkdir(parents=True)
    (runs / "a.jsonl").write_text(line)
    (runs / "b.jsonl").write_text(line)
    outdir = tmp_path / "out"
    assert fd.main([str(proj), "-o", str(outdir)]) == 0
    pages = sorted(p.name for p in outdir.glob("pipeline-*.html"))
    assert pages == ["pipeline-Twin-same-id-2.html", "pipeline-Twin-same-id.html"]


# ---------------------------------------------------------------------------
# single-file mode — runs listed, no pages fabricated
# ---------------------------------------------------------------------------
def test_single_file_mode_lists_runs_without_pages(tmp_path: Path) -> None:
    proj = _project_with_trace(tmp_path)
    out = tmp_path / "dash.html"
    assert fd.main([str(proj), "-o", str(out)]) == 0
    html = out.read_text()
    assert "Add refund endpoint" in html
    assert "pipeline page not emitted" in html
    assert list(tmp_path.glob("pipeline-*.html")) == []


def test_no_valid_dirs_fails(tmp_path: Path) -> None:
    assert fd.main([str(tmp_path / "nope")]) == 2


def test_build_project_merges_certificate(tmp_path: Path) -> None:
    proj = tmp_path / "Merge"
    proj.mkdir()
    rec = fd.build_project(str(proj))
    assert rec["project"] == "Merge"
    cert = rec["certificate"]
    # all-green prebuilt status + 1 governed run -> the real certify logic says L3
    assert cert["level"] == "L3"
    assert next(c["name"] for c in cert["claims"]) == "enforcement-armed"
