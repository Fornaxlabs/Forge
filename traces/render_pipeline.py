#!/usr/bin/env python3
"""FORGE pipeline renderer — turn a run-trace JSONL into a self-contained,
interactive CI/CD-style pipeline page.

Usage:
    python3 render_pipeline.py <trace.jsonl> [-o out.html]
    cat trace.jsonl | python3 render_pipeline.py [-o out.html]

Honesty contract:
  * Renders ONLY events present in the trace — nothing is fabricated.
  * Empty or missing trace -> an explicit "No run to show" page.
  * Every trace-supplied string is escaped with html.escape before it
    touches the document (trace content is untrusted data).
  * The page is fully self-contained: zero external requests.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

STAGES = ("TRIAGE", "PLAN", "BUILD", "REVIEW", "GATES")
STAGE_COL = {
    "TRIAGE": "--tool",
    "PLAN": "--tool",
    "BUILD": "--ember",
    "REVIEW": "--review",
    "GATES": "--allow",
}
# stage visual states
DIM, ACTIVE, WORKED, DONE = 0, 1, 2, 3

VB_W, VB_H = 1200, 556
SPINE_Y = 330
STAGE_CX = (140, 370, 600, 830, 1060)
STAGE_HALF_W, STAGE_TOP, STAGE_H = 85, 282, 96

SAMPLE_BANNER = (
    "Sample run recorded by forge_trace — real trace tooling, "
    "demonstration scenario, not a live coding session."
)


def esc(value: object, limit: int = 200) -> str:
    """Escape ANY trace-supplied value for safe HTML interpolation."""
    text = value if isinstance(value, str) else str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text, quote=True)


def _s(ev: dict[str, object], key: str) -> str | None:
    val = ev.get(key)
    return val if isinstance(val, str) else None


def _i(ev: dict[str, object], key: str) -> int | None:
    val = ev.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        return None
    return val


def parse_trace(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj: object = json.loads(line)
        except ValueError:
            print(f"render_pipeline: skipping malformed line {lineno}", file=sys.stderr)
            continue
        if not isinstance(obj, dict):
            continue
        ev: dict[str, object] = {}
        for k, v in obj.items():
            if isinstance(k, str):
                ev[k] = v
        events.append(ev)
    return events


def _parse_ts(ev: dict[str, object]) -> datetime | None:
    ts = _s(ev, "ts")
    if ts is None:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def fmt_duration(seconds: float) -> str:
    total = round(seconds)
    if total <= 0:
        return "0s"
    minutes, secs = divmod(total, 60)
    if minutes and secs:
        return f"{minutes}m {secs}s"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


@dataclass
class ToolCall:
    idx: int
    name: str
    target: str
    result: str
    stage: str


@dataclass
class Row:
    t: str
    label: str
    col: str


@dataclass
class Model:
    n: int = 0
    run_id: str = ""
    task: str = "(untitled run)"
    triage: str = ""
    git_ref: str = ""
    outcome: str = ""
    iterations: int | None = None
    tool_calls: int | None = None
    duration: str = "0s"
    rows: list[Row] = field(default_factory=list)
    dwell: list[int] = field(default_factory=list)
    matrix: list[list[int]] = field(default_factory=list)
    stage_agent: dict[str, str] = field(default_factory=dict)
    stage_enters: dict[str, int] = field(default_factory=dict)
    approved: dict[str, str] = field(default_factory=dict)
    retry_at: list[tuple[int, int]] = field(default_factory=list)
    tools: list[ToolCall] = field(default_factory=list)
    blocker_id: str = ""
    blk_counts: list[tuple[int, int]] = field(default_factory=list)
    loop_start: int = -1
    cap_idx: int = -1
    cap_attr: str = ""
    esc_idx: int = -1
    esc_to: str = ""
    esc_reason: str = ""
    end_idx: int = -1


def _stage_label(ev: dict[str, object], stage: str, col: str) -> tuple[str, str]:
    status = _s(ev, "status") or "enter"
    agent = _s(ev, "agent")
    retry = _i(ev, "retry")
    approved = _s(ev, "approved_by")
    if status == "done":
        label = f"{esc(stage)} done"
    elif retry:
        label = f"{esc(stage)} retry {retry}"
    else:
        label = f"{esc(stage)} entered"
    if agent:
        label += f" — agent {esc(agent)}"
    if approved:
        label += f" · approved by {esc(approved)}"
    return label, col


def build_model(events: list[dict[str, object]]) -> Model:
    m = Model(n=len(events))
    states: dict[str, int] = dict.fromkeys(STAGES, DIM)
    active: str | None = None
    blockers: dict[str, list[tuple[int, int]]] = {}
    times: list[datetime | None] = [_parse_ts(ev) for ev in events]
    known = [t for t in times if t is not None]
    if known:
        m.duration = fmt_duration((known[-1] - known[0]).total_seconds())

    for idx, ev in enumerate(events):
        name = _s(ev, "event") or "event"
        dt = times[idx]
        tstr = dt.strftime("%H:%M:%S") if dt else esc(_s(ev, "ts") or "—", 24)
        label, col = f"{esc(name)}", "--faint"

        if name == "run_start":
            m.run_id = esc(_s(ev, "run_id") or "")
            m.task = esc(_s(ev, "task") or "(untitled run)")
            m.triage = esc(_s(ev, "triage") or "")
            m.git_ref = esc(_s(ev, "git_ref") or "")
            label = f"run start — {m.task}"
            if m.triage:
                label += f" · triage {m.triage}"
            col = "--tool"
        elif name == "stage":
            stage = _s(ev, "stage") or ""
            if stage in STAGES:
                status = _s(ev, "status") or "enter"
                agent = _s(ev, "agent")
                if agent:
                    m.stage_agent[stage] = esc(agent)
                approved = _s(ev, "approved_by")
                if approved:
                    m.approved[stage] = esc(approved)
                retry = _i(ev, "retry")
                if retry is not None and stage == "BUILD":
                    m.retry_at.append((idx, retry))
                if status == "done":
                    states[stage] = DONE
                    if active == stage:
                        active = None
                else:
                    if active and active != stage and states[active] == ACTIVE:
                        states[active] = WORKED
                    states[stage] = ACTIVE
                    active = stage
                    m.stage_enters[stage] = m.stage_enters.get(stage, 0) + 1
                label, col = _stage_label(ev, stage, STAGE_COL[stage])
            else:
                label = f"stage {esc(stage)}"
        elif name == "tool":
            tool = ToolCall(
                idx=idx,
                name=esc(_s(ev, "name") or "tool"),
                target=esc(_s(ev, "target") or ""),
                result=esc(_s(ev, "result") or ""),
                stage=active or "",
            )
            m.tools.append(tool)
            label = f"tool {tool.name}"
            if tool.target:
                label += f" — {tool.target}"
            if tool.result:
                label += f" → {tool.result}"
            col = "--tool"
        elif name == "blocker":
            bid = _s(ev, "blocker_id") or "blocker"
            count = _i(ev, "count") or (len(blockers.get(bid, [])) + 1)
            blockers.setdefault(bid, []).append((idx, count))
            label = f"BLOCKER {esc(bid)} ×{count}"
            col = "--block"
        elif name == "loop_cap":
            m.cap_idx = idx
            m.cap_attr = esc(_s(ev, "attribution") or "")
            cap_count = _i(ev, "count")
            label = f"LOOP CAP — {esc(_s(ev, 'blocker') or '')}"
            if cap_count is not None:
                label += f" ×{cap_count}"
            if m.cap_attr:
                label += f" · attribution {m.cap_attr}"
            col = "--ember"
        elif name == "escalate":
            m.esc_idx = idx
            m.esc_to = esc(_s(ev, "to") or "human")
            m.esc_reason = esc(_s(ev, "reason") or "")
            label = f"ESCALATE → {m.esc_to}"
            if m.esc_reason:
                label += f" — {m.esc_reason}"
            col = "--escalate"
        elif name == "run_end":
            m.end_idx = idx
            m.outcome = esc(_s(ev, "outcome") or "")
            m.iterations = _i(ev, "iterations")
            m.tool_calls = _i(ev, "tool_calls")
            label = f"run end — {m.outcome or 'finished'}"
            if m.iterations is not None:
                label += f" · {m.iterations} iterations"
            if m.tool_calls is not None:
                label += f" · {m.tool_calls} tool calls"
            col = "--escalate" if m.outcome == "escalated" else "--allow"

        m.rows.append(Row(t=tstr, label=label, col=col))
        m.matrix.append([states[s] for s in STAGES])

    # dominant repeating blocker -> the loop
    best: tuple[str, list[tuple[int, int]]] | None = None
    for bid, hits in blockers.items():
        if best is None or max(c for _, c in hits) > max(c for _, c in best[1]):
            best = (bid, hits)
    if best is not None:
        m.blocker_id = esc(best[0])
        m.blk_counts = best[1]
        repeats = [i for i, c in best[1] if c >= 2]
        if repeats:
            m.loop_start = repeats[0]

    # playback dwell (ms) from real timestamps; equal/missing ts -> even pace
    offs: list[float] = []
    base: float | None = None
    prev = 0.0
    for dt in times:
        if dt is not None:
            if base is None:
                base = dt.timestamp()
            prev = dt.timestamp() - base
        offs.append(prev)
    span = (offs[-1] - offs[0]) if offs else 0.0
    m.dwell = [0]
    for i in range(1, m.n):
        if span <= 0:
            m.dwell.append(650)
        else:
            scaled = (offs[i] - offs[i - 1]) * (9000.0 / span)
            m.dwell.append(int(min(1500.0, max(140.0, scaled))))
    return m


# --------------------------------------------------------------------------
# SVG pipeline
# --------------------------------------------------------------------------


def _first_lit(m: Model, stage_idx: int) -> int:
    for p in range(m.n):
        if m.matrix[p][stage_idx] != DIM:
            return p
    return -1


def _check_mark(cx: int) -> str:
    x = cx + 70
    return (
        f'<g class="stg-check"><circle cx="{x}" cy="282" r="11"/>'
        f'<path d="M {x - 5} 282 l 3.5 3.5 l 7 -7"/></g>'
    )


def _stage_svg(m: Model, i: int) -> str:
    name = STAGES[i]
    cx = STAGE_CX[i]
    x = cx - STAGE_HALF_W
    agent = m.stage_agent.get(name, "")
    enters = m.stage_enters.get(name, 0)
    stage_tools = [t for t in m.tools if t.stage == name]
    final = m.matrix[-1][i] if m.matrix else DIM
    status = {DIM: "not reached", ACTIVE: "active at end of trace",
              WORKED: "worked", DONE: "done"}[final]
    desc = status
    if agent:
        desc += f" · agent {agent}"
    if enters > 1:
        desc += f" · entered ×{enters}"
    if stage_tools:
        desc += f" · {len(stage_tools)} tool event{'s' if len(stage_tools) > 1 else ''}"
    if name in m.approved:
        desc += f" · approved by {m.approved[name]}"
    ticks = []
    if stage_tools:
        start = cx - (len(stage_tools) - 1) * 11
        for k, t in enumerate(stage_tools):
            tip = f"tool {t.name}"
            body = " · ".join(v for v in (t.target, t.result) if v) or "tool event"
            ticks.append(
                f'<rect class="tick rv" data-rt="{t.idx}" tabindex="0" data-t="{tip}" '
                f'data-d="{body}" x="{start + k * 22 - 4}" y="358" '
                f'width="8" height="8" rx="2"/>'
            )
    agent_line = agent if agent else ("—" if final != DIM else "")
    return (
        f'<g class="stage-node st{final}" id="stg-{i}" data-stage="{name}" tabindex="0" '
        f'data-t="{name}" data-d="{desc}">'
        f'<rect class="stg-glow" x="{x}" y="{STAGE_TOP}" width="{STAGE_HALF_W * 2}" '
        f'height="{STAGE_H}" rx="18"/>'
        f'<rect class="stg-rect" x="{x}" y="{STAGE_TOP}" width="{STAGE_HALF_W * 2}" '
        f'height="{STAGE_H}" rx="18"/>'
        f'<text class="stg-name" x="{cx}" y="320" text-anchor="middle">{name}</text>'
        f'<text class="stg-agent" x="{cx}" y="344" text-anchor="middle">{agent_line}</text>'
        f"{_check_mark(cx)}"
        f'{"".join(ticks)}</g>'
    )


def _viewbox(m: Model) -> tuple[int, int, int, int]:
    """Fit the drawing to what the trace actually contains."""
    if m.loop_start >= 0 or m.esc_idx >= 0:
        return (0, 58, VB_W, 498)
    bottom = 484 if m.blk_counts else 402
    return (0, 234, VB_W, bottom - 234)


def build_svg(m: Model) -> tuple[str, list[dict[str, object]]]:
    parts: list[str] = []
    fx_edges: list[dict[str, object]] = []
    aria = f"Pipeline run graph for {m.task}."
    if m.loop_start >= 0:
        aria += (
            f" BUILD and REVIEW cycled on blocker {m.blocker_id}"
            f" ×{max(c for _, c in m.blk_counts)}."
        )
    if m.esc_idx >= 0:
        aria += f" Escalated to {m.esc_to}."
    vx, vy, vw, vh = _viewbox(m)
    parts.append(
        f'<svg class="pipe" viewBox="{vx} {vy} {vw} {vh}" role="img" '
        f'aria-label="{aria}"><defs>'
        '<marker id="arw" markerUnits="userSpaceOnUse" markerWidth="14" markerHeight="14" '
        'refX="10" refY="5" orient="auto"><path d="M1,1 L11,5 L1,9 Z"/></marker>'
        "</defs>"
    )
    # start chip
    rev0 = _first_lit(m, 0)
    parts.append(
        f'<g class="startchip rv" data-rt="{max(rev0, 0)}">'
        f'<circle cx="26" cy="{SPINE_Y}" r="7"/>'
        f'<text x="26" y="{SPINE_Y + 26}" text-anchor="middle">run</text></g>'
        f'<path class="edge spine rv" data-rt="{max(rev0, 0)}" '
        f'd="M 35,{SPINE_Y} L 48,{SPINE_Y}" marker-end="url(#arw)"/>'
    )
    # spine connectors
    for i in range(4):
        x1 = STAGE_CX[i] + STAGE_HALF_W + 4
        x2 = STAGE_CX[i + 1] - STAGE_HALF_W - 6
        rev = _first_lit(m, i + 1)
        cls = "edge spine rv" if rev >= 0 else "edge spine future"
        rt = f' data-rt="{rev}"' if rev >= 0 else ""
        parts.append(
            f'<path class="{cls}"{rt} d="M {x1},{SPINE_Y} L {x2},{SPINE_Y}" '
            'marker-end="url(#arw)"/>'
        )
        if rev >= 0:
            fx_edges.append(
                {"k": "L", "p": [x1, SPINE_Y, x2, SPINE_Y], "c": "--tool",
                 "rev": rev, "loop": False, "v": 0.55}
            )
    # loop cycle BUILD <-> REVIEW
    if m.loop_start >= 0:
        fwd = "M 636,282 C 690,148 740,148 794,282"
        ret = "M 794,378 C 740,512 690,512 636,378"
        maxc = max(c for _, c in m.blk_counts)
        cap_note = f" · attribution {m.cap_attr}" if m.cap_attr else ""
        parts.append(
            f'<path id="loop-f" class="edge loop rv" data-rt="{m.loop_start}" d="{fwd}" '
            'marker-end="url(#arw)"/>'
            f'<path id="loop-r" class="edge loop rv" data-rt="{m.loop_start}" d="{ret}" '
            'marker-end="url(#arw)"/>'
            f'<g id="loop-badge" class="loopbadge rv" data-rt="{m.loop_start}" tabindex="0" '
            f'data-t="loop — {m.blocker_id}" '
            f'data-d="same blocker repeated ×{maxc}{cap_note}">'
            f'<text class="loop-id" x="715" y="140" text-anchor="middle">{m.blocker_id}</text>'
            '<circle cx="715" cy="181" r="21"/>'
            f'<text id="loopx" class="loop-x" x="715" y="186" text-anchor="middle">'
            f"×{maxc}</text></g>"
        )
        fx_edges.append({"k": "C", "p": [636, 282, 690, 148, 740, 148, 794, 282],
                         "c": "--ember", "rev": m.loop_start, "loop": True, "v": 0.6})
        fx_edges.append({"k": "C", "p": [794, 378, 740, 512, 690, 512, 636, 378],
                         "c": "--ember", "rev": m.loop_start, "loop": True, "v": 0.6})
    # blocker chip
    if m.blk_counts:
        first_blk = m.blk_counts[0][0]
        maxc = max(c for _, c in m.blk_counts)
        parts.append(
            f'<g id="blk-chip" class="blkchip rv" data-rt="{first_blk}" tabindex="0" '
            f'data-t="reviewer blocker" data-d="{m.blocker_id} recorded ×{maxc}">'
            '<rect x="785" y="436" width="200" height="32" rx="9"/>'
            f'<text x="885" y="457" text-anchor="middle">BLOCKER {m.blocker_id} '
            f'<tspan id="blkx">×{maxc}</tspan></text></g>'
        )
    # retry badge over BUILD
    if m.retry_at:
        last_retry = m.retry_at[-1][1]
        parts.append(
            f'<g id="retry-badge" class="retrybadge rv" data-rt="{m.retry_at[0][0]}">'
            '<rect x="509" y="250" width="94" height="24" rx="7"/>'
            f'<text id="retryx" x="556" y="266" text-anchor="middle">↻ retry ×{last_retry}'
            "</text></g>"
        )
    # escalation break-out
    if m.esc_idx >= 0:
        reason = m.esc_reason or f"escalated to {m.esc_to}"
        parts.append(
            f'<path id="brk" class="edge brk rv" data-rt="{m.esc_idx}" '
            'd="M 736,175 C 830,138 880,118 930,114" marker-end="url(#arw)"/>'
            f'<g id="esc-node" class="escnode rv" data-rt="{m.esc_idx}" tabindex="0" '
            f'data-t="ESCALATE → {m.esc_to}" data-d="{reason}">'
            '<rect class="esc-glow" x="940" y="76" width="200" height="76" rx="16"/>'
            '<rect class="esc-rect" x="940" y="76" width="200" height="76" rx="16"/>'
            '<text class="esc-name" x="1040" y="108" text-anchor="middle">ESCALATE</text>'
            f'<text class="esc-sub" x="1040" y="132" text-anchor="middle">→ YOU '
            f"({m.esc_to})</text></g>"
        )
        fx_edges.append({"k": "C", "p": [736, 175, 830, 138, 880, 118, 930, 114],
                         "c": "--block", "rev": m.esc_idx, "loop": False, "v": 0.5})
    # approval chips
    for i, name in enumerate(STAGES):
        if name in m.approved and not (name == "BUILD" and m.retry_at):
            cx = STAGE_CX[i]
            rev = _first_lit(m, i)
            parts.append(
                f'<g class="okchip rv" data-rt="{max(rev, 0)}">'
                f'<rect x="{cx - 78}" y="250" width="156" height="24" rx="7"/>'
                f'<text x="{cx}" y="266" text-anchor="middle">✓ approved: '
                f"{m.approved[name]}</text></g>"
            )
    for i in range(5):
        parts.append(_stage_svg(m, i))
    parts.append("</svg>")
    return "".join(parts), fx_edges


# --------------------------------------------------------------------------
# page assembly
# --------------------------------------------------------------------------

CSS = """
:root {
  --bg:#0E1116; --panel:#161B22; --elevated:#1C232D; --hairline:#262E3A;
  --ink:#E6EDF3; --muted:#8B98A9; --faint:#5A6676;
  --ember:#F0743A; --allow:#3FB950; --tool:#58A6FF; --review:#D29922;
  --block:#F85149; --escalate:#BC8CFF;
  --grid:rgba(255,255,255,.04);
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --shadow:0 1px 0 rgba(255,255,255,.03), 0 8px 30px rgba(0,0,0,.45);
}
@media (prefers-color-scheme: light) {
  :root {
    --bg:#F5F6F8; --panel:#FFFFFF; --elevated:#FBFCFD; --hairline:#E2E6EC;
    --ink:#1A2029; --muted:#5C6675; --faint:#8A94A3;
    --ember:#D4581F; --allow:#1A7F37; --tool:#0969DA; --review:#9A6700;
    --block:#CF222E; --escalate:#8250DF;
    --grid:rgba(10,20,40,.05);
    --shadow:0 1px 0 rgba(255,255,255,.6), 0 10px 30px rgba(20,30,50,.10);
  }
}
:root[data-theme="dark"] {
  --bg:#0E1116; --panel:#161B22; --elevated:#1C232D; --hairline:#262E3A;
  --ink:#E6EDF3; --muted:#8B98A9; --faint:#5A6676;
  --ember:#F0743A; --allow:#3FB950; --tool:#58A6FF; --review:#D29922;
  --block:#F85149; --escalate:#BC8CFF;
  --grid:rgba(255,255,255,.04);
  --shadow:0 1px 0 rgba(255,255,255,.03), 0 8px 30px rgba(0,0,0,.45);
}
:root[data-theme="light"] {
  --bg:#F5F6F8; --panel:#FFFFFF; --elevated:#FBFCFD; --hairline:#E2E6EC;
  --ink:#1A2029; --muted:#5C6675; --faint:#8A94A3;
  --ember:#D4581F; --allow:#1A7F37; --tool:#0969DA; --review:#9A6700;
  --block:#CF222E; --escalate:#8250DF;
  --grid:rgba(10,20,40,.05);
  --shadow:0 1px 0 rgba(255,255,255,.6), 0 10px 30px rgba(20,30,50,.10);
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font-family:var(--sans);
  line-height:1.5;
  background-image:linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size:34px 34px; }
.wrap { min-height:100vh; padding:26px clamp(14px,3.5vw,48px) 56px; }
.maxw { max-width:1280px; margin:0 auto; }
.mast { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }
.wordmark { font-family:var(--mono); font-weight:700; font-size:15px;
  letter-spacing:.12em; text-transform:uppercase; display:inline-flex;
  align-items:center; gap:8px; }
.spark { width:10px; height:10px; border-radius:2px; background:var(--ember);
  box-shadow:0 0 10px var(--ember); transform:rotate(45deg); }
.mast .sub { font-family:var(--mono); font-size:12px; color:var(--faint);
  letter-spacing:.04em; overflow-wrap:anywhere; }
h1 { font-size:clamp(22px,3.2vw,34px); line-height:1.1; margin:12px 0 4px;
  letter-spacing:-.02em; font-weight:680; overflow-wrap:anywhere; }
h1 .hot { color:var(--ember); }
.card { background:var(--panel); border:1px solid var(--hairline);
  border-radius:14px; box-shadow:var(--shadow); }
.runbar { padding:13px 18px; display:flex; align-items:center; gap:18px 26px;
  flex-wrap:wrap; margin:16px 0 10px; }
.stat { display:flex; flex-direction:column; gap:2px; }
.stat .k { font-family:var(--mono); font-size:10.5px; letter-spacing:.09em;
  text-transform:uppercase; color:var(--faint); }
.stat .v { font-family:var(--mono); font-size:15px; font-weight:600;
  font-variant-numeric:tabular-nums; }
.grow { flex:1; }
.pill { font-family:var(--mono); font-size:12px; font-weight:700;
  letter-spacing:.05em; padding:6px 12px; border-radius:999px;
  display:inline-flex; align-items:center; gap:7px; text-transform:uppercase;
  transition:opacity .3s ease, filter .3s ease; }
.pill .dot { width:7px; height:7px; border-radius:50%; background:currentColor; }
.pill.p-escalate { color:var(--escalate);
  background:color-mix(in srgb, var(--escalate) 15%, transparent);
  border:1px solid color-mix(in srgb, var(--escalate) 40%, transparent); }
.pill.p-allow { color:var(--allow);
  background:color-mix(in srgb, var(--allow) 15%, transparent);
  border:1px solid color-mix(in srgb, var(--allow) 40%, transparent); }
.pill.p-none { color:var(--muted); background:var(--elevated);
  border:1px solid var(--hairline); }
.pill.p-tool { color:var(--tool);
  background:color-mix(in srgb, var(--tool) 14%, transparent);
  border:1px solid color-mix(in srgb, var(--tool) 38%, transparent); }
.pill.off { opacity:.28; filter:saturate(.3); }
.banner { font-family:var(--mono); font-size:11.5px; color:var(--muted);
  border:1px dashed color-mix(in srgb, var(--ember) 45%, var(--hairline));
  background:color-mix(in srgb, var(--ember) 5%, transparent);
  border-radius:10px; padding:8px 14px; margin:0 0 18px; }
.banner b { color:var(--ember); font-weight:700; }

/* ---- pipeline card ---- */
.pipecard { padding:16px 16px 8px; overflow:hidden; }
.caption { display:flex; justify-content:space-between; align-items:center;
  gap:10px 18px; flex-wrap:wrap; margin-bottom:4px; }
.caption h2 { font-size:13px; font-family:var(--mono); text-transform:uppercase;
  letter-spacing:.08em; color:var(--muted); margin:0; font-weight:600; }
.hud { display:flex; gap:16px; align-items:baseline; font-family:var(--mono);
  font-size:11.5px; color:var(--muted); font-variant-numeric:tabular-nums; }
.hud .hk { color:var(--faint); text-transform:uppercase; font-size:10px;
  letter-spacing:.08em; }
.hud .hv { font-weight:700; }
.hud .hloop { color:var(--faint); transition:color .3s ease; }
.hud .hloop.lit { color:var(--ember); }
.hud .hloop.capped { color:var(--block); }
.pipescroll { overflow-x:auto; }
.stagewrap { position:relative; min-width:820px; }
svg.pipe { width:100%; height:auto; display:block; }
#fx { position:absolute; inset:0; width:100%; height:100%;
  pointer-events:none; }

/* svg pieces */
.startchip circle { fill:var(--faint); }
.startchip text { font-family:var(--mono); font-size:10px; fill:var(--faint); }
.edge { fill:none; stroke:var(--hairline); stroke-width:2.5; }
#arw path { fill:var(--faint); }
.edge.spine { stroke:var(--faint); stroke-dasharray:3 9;
  animation:flow 1.1s linear infinite; }
.edge.future { stroke:var(--hairline); stroke-dasharray:none; animation:none;
  opacity:.6; }
.edge.loop { stroke:var(--ember); stroke-width:3; stroke-dasharray:4 10;
  animation:flow .9s linear infinite;
  filter:drop-shadow(0 0 6px color-mix(in srgb, var(--ember) 75%, transparent)); }
.edge.loop.capped, .edge.brk { stroke:var(--block);
  filter:drop-shadow(0 0 6px color-mix(in srgb, var(--block) 70%, transparent)); }
.edge.brk { stroke-width:3; stroke-dasharray:4 10;
  animation:flow .9s linear infinite; }
@keyframes flow { to { stroke-dashoffset:-13; } }
.stage-node .stg-rect { fill:var(--elevated); stroke:var(--hairline);
  stroke-width:1.5; transition:stroke .3s ease, fill .3s ease; }
.stage-node .stg-glow { fill:none; stroke:transparent; stroke-width:10;
  transition:stroke .3s ease; }
.stage-node .stg-name { font-family:var(--mono); font-size:16px;
  font-weight:700; letter-spacing:.1em; fill:var(--ink);
  transition:fill .3s ease; }
.stage-node .stg-agent { font-family:var(--mono); font-size:11.5px;
  fill:var(--muted); }
.stage-node[data-stage="TRIAGE"], .stage-node[data-stage="PLAN"] { --acc:var(--tool); }
.stage-node[data-stage="BUILD"] { --acc:var(--ember); }
.stage-node[data-stage="REVIEW"] { --acc:var(--review); }
.stage-node[data-stage="GATES"] { --acc:var(--allow); }
.stage-node { cursor:pointer; transition:opacity .35s ease; }
.stage-node.st0 { opacity:.35; }
.stage-node.st1 .stg-rect { stroke:var(--acc); stroke-width:2.5;
  fill:color-mix(in srgb, var(--acc) 7%, var(--elevated)); }
.stage-node.st1 .stg-glow {
  stroke:color-mix(in srgb, var(--acc) 22%, transparent);
  animation:breathe 2.2s ease-in-out infinite; }
.stage-node.st1 .stg-name { fill:var(--acc); }
.stage-node.st2 .stg-rect, .stage-node.st3 .stg-rect {
  fill:color-mix(in srgb, var(--acc) 10%, var(--elevated));
  stroke:color-mix(in srgb, var(--acc) 65%, var(--hairline)); }
@keyframes breathe { 0%,100% { opacity:.45; } 50% { opacity:1; } }
.stg-check { opacity:0; transition:opacity .3s ease; }
.stage-node.st3 .stg-check { opacity:1; }
.stg-check circle { fill:color-mix(in srgb, var(--allow) 22%, var(--panel));
  stroke:var(--allow); stroke-width:1.5; }
.stg-check path { fill:none; stroke:var(--allow); stroke-width:2.4;
  stroke-linecap:round; stroke-linejoin:round; }
.tick { fill:var(--tool); opacity:.9; cursor:pointer; }
.tick:hover, .tick:focus-visible { fill:var(--ink); }
.loopbadge circle { fill:color-mix(in srgb, var(--ember) 16%, var(--panel));
  stroke:var(--ember); stroke-width:2;
  animation:breathe 2.2s ease-in-out infinite; }
.loopbadge .loop-x { font-family:var(--mono); font-weight:700; font-size:14px;
  fill:var(--ember); }
.loopbadge .loop-id { font-family:var(--mono); font-size:11px;
  fill:var(--ember); letter-spacing:.05em; }
.loopbadge.capped circle { stroke:var(--block);
  fill:color-mix(in srgb, var(--block) 16%, var(--panel)); animation:none; }
.loopbadge.capped .loop-x, .loopbadge.capped .loop-id { fill:var(--block); }
.blkchip rect { fill:color-mix(in srgb, var(--review) 10%, var(--panel));
  stroke:color-mix(in srgb, var(--review) 55%, var(--hairline));
  stroke-width:1.5; }
.blkchip text { font-family:var(--mono); font-size:11.5px; font-weight:700;
  fill:var(--review); letter-spacing:.03em; }
.blkchip.capped rect { stroke:var(--block);
  fill:color-mix(in srgb, var(--block) 10%, var(--panel)); }
.blkchip.capped text { fill:var(--block); }
.retrybadge rect { fill:color-mix(in srgb, var(--ember) 10%, var(--panel));
  stroke:color-mix(in srgb, var(--ember) 50%, var(--hairline)); }
.retrybadge text { font-family:var(--mono); font-size:11px; font-weight:700;
  fill:var(--ember); }
.okchip rect { fill:color-mix(in srgb, var(--allow) 9%, var(--panel));
  stroke:color-mix(in srgb, var(--allow) 45%, var(--hairline)); }
.okchip text { font-family:var(--mono); font-size:10.5px; font-weight:700;
  fill:var(--allow); }
.escnode .esc-rect { fill:color-mix(in srgb, var(--escalate) 13%, var(--panel));
  stroke:var(--escalate); stroke-width:2; }
.escnode .esc-glow { fill:none;
  stroke:color-mix(in srgb, var(--escalate) 22%, transparent); stroke-width:10;
  animation:breathe 2.2s ease-in-out infinite; }
.escnode .esc-name { font-family:var(--mono); font-size:15px; font-weight:700;
  letter-spacing:.12em; fill:var(--escalate); }
.escnode .esc-sub { font-family:var(--mono); font-size:11.5px;
  fill:var(--muted); }
.escnode, .loopbadge, .blkchip { cursor:pointer; }
.gfocus:focus-visible, .stage-node:focus-visible, .loopbadge:focus-visible,
.blkchip:focus-visible, .escnode:focus-visible, .tick:focus-visible {
  outline:2px solid color-mix(in srgb, var(--ember) 65%, transparent);
  outline-offset:3px; border-radius:6px; }
.rv { transition:opacity .35s ease; }
.rv.off { opacity:0 !important; pointer-events:none; }

/* ---- scrubber ---- */
.scrub { display:flex; align-items:center; gap:12px; padding:12px 4px 4px;
  margin-top:8px; border-top:1px solid var(--hairline); flex-wrap:wrap; }
.playbtn { width:38px; height:32px; flex:none; display:inline-flex;
  align-items:center; justify-content:center; background:var(--elevated);
  border:1px solid var(--hairline); border-radius:8px; cursor:pointer;
  color:var(--ember); padding:0; }
.playbtn:hover { border-color:color-mix(in srgb, var(--ember) 50%, var(--hairline)); }
.playbtn svg { width:11px; height:11px; display:block; fill:currentColor; }
.playbtn .ic-pause { display:none; }
.playbtn.playing .ic-play { display:none; }
.playbtn.playing .ic-pause { display:inline; }
.playbtn:focus-visible, .scrub input[type="range"]:focus-visible {
  outline:2px solid var(--ember); outline-offset:2px; }
.scrub input[type="range"] { flex:1; min-width:140px; -webkit-appearance:none;
  appearance:none; height:4px; border-radius:999px; margin:0; cursor:pointer;
  background:linear-gradient(to right, var(--ember) var(--pos,100%),
    var(--hairline) var(--pos,100%)); }
.scrub input[type="range"]::-webkit-slider-thumb { -webkit-appearance:none;
  width:15px; height:15px; border-radius:50%; background:var(--ember);
  border:2px solid var(--panel); box-shadow:0 0 0 1px var(--hairline); }
.scrub input[type="range"]::-moz-range-thumb { width:12px; height:12px;
  border-radius:50%; background:var(--ember); border:2px solid var(--panel); }
.clock { font-family:var(--mono); font-size:11.5px; color:var(--muted);
  font-variant-numeric:tabular-nums; flex:none; }
.clock small { color:var(--faint); font-size:10.5px; }
.ticker { flex-basis:100%; font-family:var(--mono); font-size:12px;
  color:var(--muted); padding:2px 4px 6px; display:flex; gap:9px;
  align-items:baseline; min-height:22px; overflow-wrap:anywhere; }
.ticker .tdot { width:8px; height:8px; border-radius:50%; flex:none;
  transform:translateY(-.5px); }
.ticker .tt { color:var(--faint); font-variant-numeric:tabular-nums; }
.legend { display:flex; flex-wrap:wrap; gap:8px 16px; padding:10px 4px 8px; }
.legend .li { display:inline-flex; align-items:center; gap:7px;
  font-family:var(--mono); font-size:11px; color:var(--muted); }
.legend .sw { width:11px; height:11px; border-radius:3px; }

/* ---- lower grid ---- */
.lower { display:grid; grid-template-columns:1.5fr 1fr; gap:18px;
  margin-top:18px; align-items:start; }
@media (max-width:900px){ .lower { grid-template-columns:1fr; } }
.evcard, .insight { padding:16px 18px; }
.evcard h2, .insight h2 { font-size:13px; font-family:var(--mono);
  text-transform:uppercase; letter-spacing:.08em; color:var(--muted);
  margin:0 0 8px; font-weight:600; }
.evlist { list-style:none; margin:0; padding:0; }
.evlist li { display:grid; grid-template-columns:66px 14px 1fr; gap:10px;
  align-items:baseline; padding:6px 8px; margin:0 -8px;
  border-top:1px solid var(--hairline); font-size:12.5px; border-radius:8px;
  transition:opacity .25s ease, background-color .25s ease;
  font-family:var(--mono); color:var(--muted); overflow-wrap:anywhere; }
.evlist li:first-child { border-top:none; }
.evlist li.dim { opacity:.32; }
.evlist li.now { background:color-mix(in srgb, var(--ember) 9%, transparent);
  color:var(--ink); }
.evlist .t { font-size:11px; color:var(--faint);
  font-variant-numeric:tabular-nums; }
.evlist li.now .t { color:var(--ember); font-weight:700; }
.evlist .mk { width:8px; height:8px; border-radius:50%;
  transform:translateY(-.5px); }
.insight p { margin:0 0 10px; font-size:13.5px; color:var(--muted);
  overflow-wrap:anywhere; }
.insight p b { color:var(--ink); font-weight:600; }
.tag { font-family:var(--mono); font-size:11px; font-weight:700;
  padding:1px 6px; border-radius:5px; white-space:nowrap; }
.tag.loop { color:var(--ember);
  background:color-mix(in srgb, var(--ember) 16%, transparent); }
.tag.attr { color:var(--review);
  background:color-mix(in srgb, var(--review) 16%, transparent); }
.tag.esc { color:var(--escalate);
  background:color-mix(in srgb, var(--escalate) 16%, transparent); }
.tag.blk { color:var(--block);
  background:color-mix(in srgb, var(--block) 16%, transparent); }
.foot { margin-top:34px; padding-top:16px; border-top:1px solid var(--hairline);
  color:var(--faint); font-size:12px; font-family:var(--mono);
  display:flex; gap:8px 18px; flex-wrap:wrap; }
.foot .b { color:var(--muted); }
#tip { position:fixed; pointer-events:none; z-index:50; opacity:0;
  transition:opacity .1s; background:var(--elevated);
  border:1px solid var(--hairline); border-radius:8px; padding:8px 10px;
  box-shadow:var(--shadow); max-width:260px; font-size:12px; }
#tip .tt { font-family:var(--mono); font-weight:700; font-size:11px;
  letter-spacing:.04em; }
#tip .tb { color:var(--muted); margin-top:3px; font-size:11.5px;
  overflow-wrap:anywhere; }
.backlink { font-family:var(--mono); font-size:12px; color:var(--tool);
  text-decoration:none; display:inline-block; margin:0 0 12px;
  text-underline-offset:3px; }
.backlink:hover { color:var(--ink); text-decoration:underline; }
.backlink:focus-visible { outline:2px solid var(--ember); outline-offset:2px;
  border-radius:6px; }
.empty { padding:56px 28px; text-align:center; margin-top:20px; }
.empty .big { font-family:var(--mono); font-size:19px; font-weight:700;
  margin-bottom:8px; }
.empty p { color:var(--muted); margin:0; }
@media (prefers-reduced-motion: reduce) {
  .edge.spine, .edge.loop, .edge.brk { animation:none; stroke-dasharray:none; }
  .stg-glow, .esc-glow, .loopbadge circle { animation:none !important; }
  .rv, .stage-node, .evlist li, .pill { transition:none; }
  #fx { display:none; }
}
"""

JS = """
(function () {
  'use strict';
  var M = window.__FORGE_RUN__;
  if (!M || !M.n) { return; }
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  var pos = M.n - 1;

  /* ---- tooltips ---- */
  var tip = document.getElementById('tip');
  var tipT = tip.querySelector('.tt');
  var tipB = tip.querySelector('.tb');
  function showTip(el, x, y) {
    var t = el.getAttribute('data-t');
    if (!t) { return; }
    tipT.textContent = t;
    tipB.textContent = el.getAttribute('data-d') || '';
    tip.style.opacity = '1';
    var pad = 14;
    tip.style.left = Math.min(x + pad, window.innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = Math.min(y + pad, window.innerHeight - tip.offsetHeight - 8) + 'px';
  }
  function hideTip() { tip.style.opacity = '0'; }
  Array.prototype.forEach.call(document.querySelectorAll('[data-t]'), function (n) {
    n.addEventListener('mousemove', function (e) { showTip(n, e.clientX, e.clientY); });
    n.addEventListener('mouseleave', hideTip);
    n.addEventListener('focus', function () {
      var r = n.getBoundingClientRect();
      showTip(n, r.left + r.width / 2, r.top + r.height);
    });
    n.addEventListener('blur', hideTip);
  });

  /* ---- element refs ---- */
  var rv = Array.prototype.slice.call(document.querySelectorAll('.rv[data-rt]'));
  var evs = Array.prototype.slice.call(document.querySelectorAll('.evlist li[data-ei]'));
  var stageEls = [];
  var s;
  for (s = 0; s < 5; s++) { stageEls.push(document.getElementById('stg-' + s)); }
  var seek = document.getElementById('seek');
  var playBtn = document.getElementById('play');
  var clockCur = document.getElementById('clock-cur');
  var hudTools = document.getElementById('hud-tools');
  var hudLoop = document.getElementById('hud-loop');
  var hudLoopWrap = document.getElementById('hud-loop-wrap');
  var hudClock = document.getElementById('hud-clock');
  var ticker = document.getElementById('ticker');
  var tickerDot = document.getElementById('ticker-dot');
  var tickerT = document.getElementById('ticker-t');
  var tickerL = document.getElementById('ticker-l');
  var pill = document.getElementById('pill');
  var loopX = document.getElementById('loopx');
  var blkX = document.getElementById('blkx');
  var retryX = document.getElementById('retryx');
  var capEls = ['loop-f', 'loop-r', 'loop-badge', 'blk-chip'].map(function (id) {
    return document.getElementById(id);
  });

  /* ---- state fully derived from position ---- */
  function apply(p) {
    pos = p;
    rv.forEach(function (el) {
      el.classList.toggle('off', p < +el.getAttribute('data-rt'));
    });
    var i;
    for (i = 0; i < 5; i++) {
      if (!stageEls[i]) { continue; }
      var st = M.matrix[p][i];
      stageEls[i].classList.remove('st0', 'st1', 'st2', 'st3');
      stageEls[i].classList.add('st' + st);
    }
    var loops = 0;
    M.blk.forEach(function (bc) { if (bc[0] <= p) { loops = bc[1]; } });
    if (loopX) { loopX.textContent = '\\u00d7' + loops; }
    if (blkX) { blkX.textContent = '\\u00d7' + loops; }
    var retry = 0;
    M.retry.forEach(function (rc) { if (rc[0] <= p) { retry = rc[1]; } });
    if (retryX) { retryX.textContent = '\\u21bb retry \\u00d7' + retry; }
    var capped = M.capIdx >= 0 && p >= M.capIdx;
    capEls.forEach(function (el) { if (el) { el.classList.toggle('capped', capped); } });
    var tc = 0;
    M.toolIdx.forEach(function (ti) { if (ti <= p) { tc++; } });
    if (hudTools) { hudTools.textContent = tc + '/' + M.toolIdx.length; }
    if (hudLoop) {
      hudLoop.textContent = loops >= 2 ? '\\u00d7' + loops : '\\u2014';
      hudLoopWrap.classList.toggle('lit', loops >= 2 && !capped);
      hudLoopWrap.classList.toggle('capped', capped);
    }
    if (hudClock) { hudClock.textContent = M.rows[p].t; }
    if (clockCur) { clockCur.textContent = M.rows[p].t; }
    if (ticker) {
      tickerDot.style.background = 'var(' + M.rows[p].col + ')';
      tickerT.textContent = (p + 1) + '/' + M.n;
      /* label was html-escaped by the renderer before embedding */
      tickerL.innerHTML = M.rows[p].label;
    }
    var now = -1;
    evs.forEach(function (li) {
      var ei = +li.getAttribute('data-ei');
      li.classList.toggle('dim', p < ei);
      if (ei <= p) { now = ei; }
    });
    evs.forEach(function (li) {
      li.classList.toggle('now', +li.getAttribute('data-ei') === now);
    });
    if (pill && M.endIdx >= 0) { pill.classList.toggle('off', p < M.endIdx); }
    seek.value = String(p);
    var pct = M.n > 1 ? (p / (M.n - 1)) * 100 : 100;
    seek.style.setProperty('--pos', pct + '%');
    seek.setAttribute('aria-valuetext',
      'event ' + (p + 1) + ' of ' + M.n + ' \\u00b7 ' + M.rows[p].t);
  }

  /* ---- playback (no autoplay; dwell derived from real timestamps) ---- */
  var playing = false;
  var timer = 0;
  function setBtn() {
    playBtn.classList.toggle('playing', playing);
    playBtn.setAttribute('aria-label',
      playing ? 'Pause playback' : (pos >= M.n - 1 ? 'Replay run' : 'Play run'));
  }
  function stopPlay() { playing = false; clearTimeout(timer); setBtn(); }
  function schedule() {
    if (pos >= M.n - 1) { stopPlay(); return; }
    var next = pos + 1;
    var d = reduced.matches ? 650 : Math.max(140, Math.min(1500, M.dwell[next]));
    timer = setTimeout(function () {
      apply(next);
      schedule();
    }, d);
  }
  function startPlay() {
    if (pos >= M.n - 1) { apply(0); }
    playing = true;
    setBtn();
    schedule();
  }
  playBtn.addEventListener('click', function () {
    if (playing) { stopPlay(); } else { startPlay(); }
  });
  seek.addEventListener('input', function () {
    if (playing) { stopPlay(); }
    apply(Math.max(0, Math.min(M.n - 1, Math.round(+seek.value))));
  });

  /* ---- canvas energy-flow overlay ---- */
  var wrapEl = document.getElementById('stagewrap');
  var cv = document.getElementById('fx');
  var ctx = cv && cv.getContext ? cv.getContext('2d') : null;
  var sx = 1;
  var sy = 1;
  function resize() {
    if (!cv || !wrapEl) { return; }
    var d = window.devicePixelRatio || 1;
    cv.width = Math.max(1, Math.round(wrapEl.clientWidth * d));
    cv.height = Math.max(1, Math.round(wrapEl.clientHeight * d));
    sx = cv.width / M.vw;
    sy = cv.height / M.vh;
  }
  function edgePoint(e, t) {
    var p = e.p;
    if (e.k === 'L') {
      return [p[0] + (p[2] - p[0]) * t, p[1] + (p[3] - p[1]) * t];
    }
    var u = 1 - t;
    var a = u * u * u;
    var b = 3 * u * u * t;
    var c = 3 * u * t * t;
    var dd = t * t * t;
    return [a * p[0] + b * p[2] + c * p[4] + dd * p[6],
            a * p[1] + b * p[3] + c * p[5] + dd * p[7]];
  }
  var raf = 0;
  var t0 = (window.performance && performance.now) ? performance.now() : 0;
  function frame(now) {
    ctx.setTransform(sx, 0, 0, sy, -M.vx * sx, -M.vy * sy);
    ctx.clearRect(M.vx, M.vy, M.vw, M.vh);
    var css = getComputedStyle(document.documentElement);
    var capped = M.capIdx >= 0 && pos >= M.capIdx;
    M.edges.forEach(function (e, ei) {
      if (e.rev < 0 || pos < e.rev) { return; }
      var colVar = (e.loop && capped) ? '--block' : e.c;
      var col = css.getPropertyValue(colVar).trim() || '#888888';
      var count = e.loop ? 3 : 2;
      var i;
      for (i = 0; i < count; i++) {
        var ph = (((now - t0) / 1000) * e.v + i / count + ei * 0.37) % 1;
        var k;
        for (k = 5; k >= 0; k--) {
          var tt = ph - k * 0.014;
          if (tt < 0) { continue; }
          var pt = edgePoint(e, tt);
          ctx.globalAlpha = k === 0 ? 0.95 : Math.max(0.05, 0.3 - k * 0.045);
          ctx.shadowColor = col;
          ctx.shadowBlur = k === 0 ? 13 : 0;
          ctx.fillStyle = col;
          ctx.beginPath();
          ctx.arc(pt[0], pt[1], k === 0 ? 3.1 : 2.1 - k * 0.22, 0, 6.2832);
          ctx.fill();
        }
      }
    });
    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
    raf = requestAnimationFrame(frame);
  }
  function startFx() {
    if (!ctx || reduced.matches || !M.edges.length) { return; }
    resize();
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  }
  function stopFx() { cancelAnimationFrame(raf); }
  if (ctx) {
    window.addEventListener('resize', resize);
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { stopFx(); } else { startFx(); }
    });
    if (reduced.addEventListener) {
      reduced.addEventListener('change', function () {
        if (reduced.matches) {
          stopFx();
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.clearRect(0, 0, cv.width, cv.height);
        } else { startFx(); }
      });
    }
    startFx();
  }

  /* progressive enhancement: reveal the scrubber, land on the end state */
  document.getElementById('scrub-row').hidden = false;
  apply(M.n - 1);
  setBtn();
})();
"""


def _head(title: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
    )


def _back_link(back_href: str | None) -> str:
    """Small escape hatch back to the dashboard index (dashboard-driven renders
    only; the standalone CLI emits no link)."""
    if not back_href:
        return ""
    return f'<a class="backlink" href="{esc(back_href)}">&larr; back to dashboard</a>'


def _provenance(source: str | None) -> str:
    """Footer provenance line. Standalone CLI keeps the honest sample banner;
    dashboard-driven renders state the real trace file instead."""
    if source is None:
        return html.escape(SAMPLE_BANNER)
    return f"trace: {esc(source, 300)} — rendered only from its recorded events"


def render_empty(back_href: str | None = None, source: str | None = None) -> str:
    return (
        _head("FORGE — no run")
        + f'<div class="wrap"><div class="maxw">{_back_link(back_href)}'
        '<div class="mast"><span class="wordmark"><span class="spark"></span> '
        "Forge</span>"
        '<span class="sub">pipeline run recorder</span></div>'
        '<div class="card empty"><div class="big">No run to show</div>'
        "<p>The trace is empty or missing. Start one with "
        "<b>/forge</b> — every governed run records a JSONL trace this page "
        "can replay.</p></div>"
        f'<div class="foot"><span class="b">FORGE run pipeline</span>'
        f"<span>{_provenance(source)}</span></div>"
        "</div></div>\n</body>\n</html>\n"
    )


def _runbar(m: Model) -> str:
    if m.outcome == "escalated":
        pill_cls = "p-escalate"
    elif m.outcome:
        pill_cls = "p-allow"
    else:
        pill_cls = "p-none"
    outcome = m.outcome or "no run_end in trace"
    stats = [
        ("duration", m.duration),
        ("tool calls (reported)", str(m.tool_calls) if m.tool_calls is not None else "—"),
        ("iterations", str(m.iterations) if m.iterations is not None else "—"),
        ("trace events", str(m.n)),
        ("git ref", m.git_ref or "—"),
    ]
    cells = "".join(
        f'<div class="stat"><span class="k">{k}</span><span class="v">{v}</span></div>'
        for k, v in stats
    )
    triage = f'<span class="pill p-tool">triage {m.triage}</span>' if m.triage else ""
    return (
        f'<div class="card runbar" role="group" aria-label="run summary">{triage}'
        f'{cells}<div class="grow"></div>'
        f'<span class="pill {pill_cls}" id="pill"><span class="dot"></span> '
        f"{outcome}</span></div>"
    )


def _scrub(m: Model) -> str:
    last = m.rows[-1].t if m.rows else ""
    return (
        '<div class="scrub" id="scrub-row" role="group" aria-label="Run playback" hidden>'
        '<button class="playbtn" id="play" type="button" aria-label="Replay run">'
        '<svg viewBox="0 0 12 12" aria-hidden="true">'
        '<path class="ic-play" d="M2.5 1.2 L11 6 L2.5 10.8 Z"></path>'
        '<g class="ic-pause"><rect x="2" y="1.5" width="3" height="9" rx="1"></rect>'
        '<rect x="7" y="1.5" width="3" height="9" rx="1"></rect></g></svg></button>'
        f'<input id="seek" type="range" min="0" max="{m.n - 1}" step="1" '
        f'value="{m.n - 1}" aria-label="Scrub run timeline">'
        f'<span class="clock"><span id="clock-cur">{last}</span>'
        f"<small> / {last}</small></span>"
        '<div class="ticker" id="ticker"><span class="tdot" id="ticker-dot"></span>'
        '<span class="tt" id="ticker-t"></span><span id="ticker-l"></span></div>'
        "</div>"
    )


def _evlist(m: Model) -> str:
    items = "".join(
        f'<li data-ei="{i}"><span class="t">{r.t}</span>'
        f'<span class="mk" style="background:var({r.col})"></span>'
        f"<span>{r.label}</span></li>"
        for i, r in enumerate(m.rows)
    )
    return (
        '<div class="card evcard"><h2>Trace events</h2>'
        f'<ul class="evlist">{items}</ul></div>'
    )


def _insight(m: Model) -> str:
    parts: list[str] = []
    if m.loop_start >= 0:
        maxc = max(c for _, c in m.blk_counts)
        line = (
            f'The reviewer raised the <span class="tag blk">same BLOCKER</span> '
            f"<b>{m.blocker_id}</b> ×{maxc}, so the run is drawn as a "
            f'<span class="tag loop">LOOP</span> between BUILD and REVIEW'
        )
        if m.cap_idx >= 0:
            line += " — the loop cap fired"
            if m.cap_attr:
                line += f', attributed <span class="tag attr">{m.cap_attr}</span>'
        if m.esc_idx >= 0:
            line += (
                f', and the run <span class="tag esc">ESCALATED</span> to '
                f"<b>{m.esc_to}</b>"
            )
            if m.esc_reason:
                line += f" — &ldquo;{m.esc_reason}&rdquo;"
        parts.append(f"<p>{line}.</p>")
    if m.end_idx >= 0:
        end = f"<p>Run ended: <b>{m.outcome or 'unknown'}</b>"
        if m.iterations is not None:
            end += f" after {m.iterations} iterations"
        if m.tool_calls is not None:
            end += f" and {m.tool_calls} tool calls"
        parts.append(end + ".</p>")
    if not parts:
        parts.append("<p>No loop, escalation, or run_end recorded in this trace.</p>")
    parts.append(
        '<p style="font-size:12px;color:var(--faint)">Everything above is derived '
        "from the trace events on the left — nothing is fabricated.</p>"
    )
    return '<div class="card insight"><h2>What happened</h2>' + "".join(parts) + "</div>"


def _legend(m: Model) -> str:
    items = [
        ("var(--tool)", "triage / plan / tool"),
        ("var(--ember)", "build · loop (thrash)"),
        ("var(--review)", "review / blocker"),
        ("var(--block)", "loop cap hit"),
        ("var(--escalate)", "escalate to you"),
        ("var(--allow)", "gates / done"),
    ]
    spans = "".join(
        f'<span class="li"><span class="sw" style="background:{c}"></span>{t}</span>'
        for c, t in items
    )
    return f'<div class="legend" aria-hidden="true">{spans}</div>'


def render_page(m: Model, back_href: str | None = None,
                source: str | None = None) -> str:
    svg, fx_edges = build_svg(m)
    vx, vy, vw, vh = _viewbox(m)
    payload: dict[str, object] = {
        "n": m.n,
        "vx": vx,
        "vy": vy,
        "vw": vw,
        "vh": vh,
        "rows": [{"t": r.t, "label": r.label, "col": r.col} for r in m.rows],
        "dwell": m.dwell,
        "matrix": m.matrix,
        "toolIdx": [t.idx for t in m.tools],
        "blk": [list(bc) for bc in m.blk_counts],
        "retry": [list(rc) for rc in m.retry_at],
        "capIdx": m.cap_idx,
        "escIdx": m.esc_idx,
        "endIdx": m.end_idx,
        "edges": fx_edges,
    }
    model_json = json.dumps(payload, ensure_ascii=True)
    sub = f"pipeline · run {m.run_id}" if m.run_id else "pipeline run"
    maxc = max((c for _, c in m.blk_counts), default=0)
    hud_loop = f"×{maxc}" if maxc >= 2 else "—"
    hud_loop_cls = "hloop capped" if m.cap_idx >= 0 else ("hloop lit" if maxc >= 2 else "hloop")
    last_t = m.rows[-1].t if m.rows else ""
    if source is None:
        banner = f'<div class="banner"><b>SAMPLE</b> · {html.escape(SAMPLE_BANNER)}</div>'
    else:
        banner = (
            f'<div class="banner"><b>TRACE</b> · {esc(source, 300)} — every event on '
            "this page comes from that recorded JSONL; nothing is fabricated.</div>"
        )
    body = (
        f'<div class="wrap"><div class="maxw">{_back_link(back_href)}'
        '<div class="mast"><span class="wordmark"><span class="spark"></span> '
        f'Forge</span><span class="sub">{sub}</span></div>'
        f'<h1><span class="hot">run:</span> {m.task}</h1>'
        f"{_runbar(m)}"
        f"{banner}"
        '<div class="card pipecard">'
        '<div class="caption"><h2>Run pipeline</h2>'
        '<div class="hud">'
        f'<span><span class="hk">clock</span> <span class="hv" id="hud-clock">'
        f"{last_t}</span></span>"
        f'<span><span class="hk">tool events</span> <span class="hv" id="hud-tools">'
        f"{len(m.tools)}/{len(m.tools)}</span></span>"
        f'<span id="hud-loop-wrap" class="{hud_loop_cls}"><span class="hk">loop</span> '
        f'<span class="hv" id="hud-loop">{hud_loop}</span></span>'
        "</div></div>"
        f'<div class="pipescroll"><div class="stagewrap" id="stagewrap">{svg}'
        '<canvas id="fx" aria-hidden="true"></canvas></div></div>'
        f"{_scrub(m)}{_legend(m)}</div>"
        f'<div class="lower">{_evlist(m)}{_insight(m)}</div>'
        f'<div class="foot"><span class="b">FORGE run pipeline · rendered by '
        "traces/render_pipeline.py</span>"
        f"<span>{_provenance(source)}</span>"
        "<span>self-contained · zero external requests · press play or scrub</span>"
        "</div></div></div>"
        '<div id="tip" role="status" aria-live="polite"><div class="tt"></div>'
        '<div class="tb"></div></div>'
        f"<script>window.__FORGE_RUN__ = {model_json};</script>"
        f"<script>{JS}</script>"
    )
    return _head(f"FORGE run — {m.task}") + body + "\n</body>\n</html>\n"


def render(text: str, back_href: str | None = None, source: str | None = None) -> str:
    """Import surface (used by status/forge_dashboard.py): render raw trace
    JSONL text to one complete self-contained HTML page.

    Empty/invalid text renders the honest "No run to show" page — never a
    fabricated run. back_href adds a "back to dashboard" link; source (the real
    trace path) replaces the sample banner with a provenance line.
    """
    events = parse_trace(text)
    if not events:
        return render_empty(back_href, source)
    return render_page(build_model(events), back_href=back_href, source=source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a FORGE run trace (JSONL) as an interactive pipeline page."
    )
    parser.add_argument("trace", nargs="?", default="-",
                        help="trace .jsonl path, or - for stdin (default)")
    parser.add_argument("-o", "--output", default=None,
                        help="output .html path (default: stdout)")
    args = parser.parse_args(argv)

    text = ""
    if args.trace == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.trace)
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            print(f"render_pipeline: trace not found: {path}", file=sys.stderr)

    events = parse_trace(text)
    if not events:
        doc = render_empty()
        print("render_pipeline: empty trace — rendered honest empty state",
              file=sys.stderr)
    else:
        doc = render_page(build_model(events))

    if args.output:
        Path(args.output).write_text(doc, encoding="utf-8")
        print(f"render_pipeline: wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
