"""Behavior tests for traces/render_pipeline.py — the run-trace pipeline page.

Renders the REAL shipped sample trace (traces/sample-run.jsonl) plus crafted
traces and asserts on the actual HTML: the 5 stages, the BUILD<->REVIEW loop
with its x3 count, the escalate node, real tool/iteration counts, honest empty
states, escaping of trace-supplied strings, and zero external requests.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_P = _ROOT / "traces" / "render_pipeline.py"
_spec = importlib.util.spec_from_file_location("render_pipeline_under_test", _P)
assert _spec and _spec.loader
rp = importlib.util.module_from_spec(_spec)
sys.modules["render_pipeline_under_test"] = rp  # dataclasses need the module registered
_spec.loader.exec_module(rp)

SAMPLE = (_ROOT / "traces" / "sample-run.jsonl").read_text()


def _trace(*events: dict[str, Any]) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


# ---------------------------------------------------------------------------
# the real sample trace
# ---------------------------------------------------------------------------
def test_sample_renders_all_five_stages() -> None:
    out = rp.render(SAMPLE)
    for stage in ("TRIAGE", "PLAN", "BUILD", "REVIEW", "GATES"):
        assert f'data-stage="{stage}"' in out


def test_sample_loop_x3_and_escalate() -> None:
    out = rp.render(SAMPLE)
    assert "authz-missing" in out          # the repeating blocker id
    assert "×3" in out                     # loop count on badge/chip
    assert "ESCALATE" in out               # break-out node
    assert "escalated" in out              # outcome pill
    assert "LOOP CAP" in out
    assert "CONTEXT" in out                # loop-cap attribution


def test_sample_real_counts_and_task() -> None:
    out = rp.render(SAMPLE)
    assert "Add refund endpoint" in out
    assert "3/3" in out                    # 3 real tool events in the trace
    assert ">9<" in out                    # reported tool_calls from run_end
    assert "3 iterations" in out
    assert "retry ×2" in out               # last BUILD retry badge
    assert "MEDIUM" in out                 # triage pill
    # every ts in the sample is identical -> honest 0s duration
    assert ">0s<" in out


def test_sample_provenance_banner_modes() -> None:
    standalone = rp.render(SAMPLE)
    assert "SAMPLE" in standalone          # honest sample banner by default
    sourced = rp.render(SAMPLE, back_href="index.html",
                        source="/p/.forge/runs/r.jsonl")
    assert "/p/.forge/runs/r.jsonl" in sourced
    assert 'href="index.html"' in sourced  # back link to the dashboard
    assert "Sample run recorded" not in sourced


# ---------------------------------------------------------------------------
# empty / invalid traces — honest, never fabricated, never a crash
# ---------------------------------------------------------------------------
def test_empty_trace_renders_no_run_page() -> None:
    for text in ("", "   \n\n", "not json\ngarbage {{{\n", '"just a string"\n[1,2]\n'):
        out = rp.render(text)
        assert "No run to show" in out
        assert '<g class="stage-node' not in out  # no fabricated pipeline SVG
        assert "Run pipeline" not in out


def test_no_run_end_is_reported_honestly() -> None:
    out = rp.render(_trace(
        {"ts": "2026-07-18T08:00:00+00:00", "event": "run_start", "task": "t"},
        {"ts": "2026-07-18T08:00:01+00:00", "event": "stage", "stage": "BUILD",
         "status": "enter", "agent": "smith"},
    ))
    assert "no run_end in trace" in out


# ---------------------------------------------------------------------------
# duration derived from real timestamps
# ---------------------------------------------------------------------------
def test_duration_from_timestamps() -> None:
    out = rp.render(_trace(
        {"ts": "2026-07-18T08:00:00+00:00", "event": "run_start", "task": "t"},
        {"ts": "2026-07-18T08:01:35+00:00", "event": "run_end",
         "outcome": "green", "iterations": 1, "tool_calls": 2},
    ))
    assert "1m 35s" in out


def test_fmt_duration_units() -> None:
    assert rp.fmt_duration(0) == "0s"
    assert rp.fmt_duration(59) == "59s"
    assert rp.fmt_duration(60) == "1m"
    assert rp.fmt_duration(90) == "1m 30s"


# ---------------------------------------------------------------------------
# escaping — trace content is untrusted data
# ---------------------------------------------------------------------------
def test_xss_in_task_and_tool_target_escaped() -> None:
    xss = "<script>alert('pwn')</script>"
    out = rp.render(_trace(
        {"ts": "2026-07-18T08:00:00+00:00", "event": "run_start", "task": xss,
         "triage": xss, "git_ref": xss},
        {"ts": "2026-07-18T08:00:01+00:00", "event": "stage", "stage": "BUILD",
         "status": "enter", "agent": xss},
        {"ts": "2026-07-18T08:00:02+00:00", "event": "tool", "name": xss,
         "target": '<img src=x onerror=alert(2)>', "result": xss},
        {"ts": "2026-07-18T08:00:03+00:00", "event": "blocker",
         "blocker_id": xss, "count": 1},
        {"ts": "2026-07-18T08:00:04+00:00", "event": "escalate", "to": xss,
         "reason": xss},
        {"ts": "2026-07-18T08:00:05+00:00", "event": "run_end", "outcome": xss},
    ))
    assert "<script>alert" not in out
    assert "<img src=x" not in out
    assert "&lt;script&gt;alert" in out


def test_xss_never_breaks_out_of_attributes() -> None:
    out = rp.render(_trace(
        {"ts": "2026-07-18T08:00:00+00:00", "event": "run_start",
         "task": 'x" onmouseover="alert(1)'},
    ))
    assert '" onmouseover="alert(1)' not in out
    assert "&quot; onmouseover=&quot;alert(1)" in out


# ---------------------------------------------------------------------------
# self-containment
# ---------------------------------------------------------------------------
def test_no_external_references() -> None:
    out = rp.render(SAMPLE)
    assert "http://" not in out
    assert "https://" not in out
    assert 'src="' not in out
    assert "@import" not in out
    # the only url() uses are same-document SVG fragment refs (url(#...))
    assert out.count("url(") == out.count("url(#")


# ---------------------------------------------------------------------------
# parse_trace — tolerant line parsing
# ---------------------------------------------------------------------------
def test_parse_trace_skips_malformed_and_non_objects() -> None:
    events = rp.parse_trace(
        '{"event": "run_start", "task": "t"}\n'
        "\n"
        "not json\n"
        "[1, 2, 3]\n"
        '"a string"\n'
        '{"event": "run_end"}\n'
    )
    assert [e["event"] for e in events] == ["run_start", "run_end"]


def test_build_model_counts_tools_and_blockers() -> None:
    m = rp.build_model(rp.parse_trace(SAMPLE))
    assert m.n == 16                       # every sample line is an event
    assert len(m.tools) == 3
    assert m.tool_calls == 9               # reported by run_end
    assert m.iterations == 3
    assert m.blocker_id == "authz-missing"
    assert max(c for _, c in m.blk_counts) == 3
    assert m.outcome == "escalated"
    assert m.cap_idx >= 0 and m.esc_idx >= 0 and m.end_idx == 15
