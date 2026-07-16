#!/usr/bin/env python3
"""Render the FORGE dashboard from REAL collector data — no mockup.

Reads forge_status.py JSON (one or more projects) and emits a single, fully
self-contained HTML dashboard: inline CSS, inline vanilla JS, zero external
requests. Everything shown is real, collected read-only from the actual repos.
Capabilities Forge has not built yet (live workers, pipeline runs, engine
tiering, certification) are shown as honest "not built yet" text — never faked.

Every dynamic string that reaches the HTML goes through html.escape (commit
messages, branch names, PR titles, paths, notes — all attacker-influenced).
The only unescaped interpolations are integers we cast ourselves.

Usage:
  python3 forge_status.py <dirs...> --json | python3 render_dashboard.py > dashboard.html
  python3 render_dashboard.py status.json > dashboard.html
"""
from __future__ import annotations

import html
import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Design tokens — shared with the other Forge surfaces (dark/light aware).
# Mono for telemetry, semantic status colors (allow/review/block), ember used
# sparingly as the brand accent (wordmark spark, focus ring, active filter).
# ---------------------------------------------------------------------------
_CSS = """
:root{--bg:#0E1116;--panel:#161B22;--elevated:#1C232D;--hairline:#262E3A;--ink:#E6EDF3;
--muted:#8B98A9;--faint:#5A6676;--ember:#F0743A;--allow:#3FB950;--tool:#58A6FF;
--review:#D29922;--block:#F85149;--escalate:#BC8CFF;--grid:rgba(255,255,255,.04);
--mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--shadow:0 1px 0 rgba(255,255,255,.03),0 8px 30px rgba(0,0,0,.45);}
@media(prefers-color-scheme:light){:root{--bg:#F5F6F8;--panel:#FFFFFF;--elevated:#FBFCFD;
--hairline:#E2E6EC;--ink:#1A2029;--muted:#5C6675;--faint:#8A94A3;--ember:#D4581F;
--allow:#1A7F37;--tool:#0969DA;--review:#9A6700;--block:#CF222E;--escalate:#8250DF;
--grid:rgba(10,20,40,.05);--shadow:0 1px 0 rgba(255,255,255,.6),0 10px 30px rgba(20,30,50,.10);}}
:root[data-theme=dark]{--bg:#0E1116;--panel:#161B22;--elevated:#1C232D;--hairline:#262E3A;
--ink:#E6EDF3;--muted:#8B98A9;--faint:#5A6676;--ember:#F0743A;--allow:#3FB950;--tool:#58A6FF;
--review:#D29922;--block:#F85149;--escalate:#BC8CFF;--grid:rgba(255,255,255,.04);
--shadow:0 1px 0 rgba(255,255,255,.03),0 8px 30px rgba(0,0,0,.45);}
:root[data-theme=light]{--bg:#F5F6F8;--panel:#FFFFFF;--elevated:#FBFCFD;--hairline:#E2E6EC;
--ink:#1A2029;--muted:#5C6675;--faint:#8A94A3;--ember:#D4581F;--allow:#1A7F37;--tool:#0969DA;
--review:#9A6700;--block:#CF222E;--escalate:#8250DF;--grid:rgba(10,20,40,.05);
--shadow:0 1px 0 rgba(255,255,255,.6),0 10px 30px rgba(20,30,50,.10);}

*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;
background-image:linear-gradient(var(--grid) 1px,transparent 1px),
linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:34px 34px}
.wrap{min-height:100vh;padding:26px clamp(14px,3vw,40px) 60px}
.maxw{max-width:1100px;margin:0 auto}
:focus-visible{outline:2px solid var(--ember);outline-offset:2px;border-radius:6px}

/* masthead */
.mast{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:4px}
.wordmark{font-family:var(--mono);font-weight:700;font-size:15px;letter-spacing:.12em;
text-transform:uppercase;display:inline-flex;align-items:center;gap:8px}
.spark{width:10px;height:10px;border-radius:2px;background:var(--ember);
box-shadow:0 0 10px var(--ember);transform:rotate(45deg)}
.sub{font-family:var(--mono);font-size:12px;color:var(--faint)}
h1{font-size:clamp(22px,3vw,30px);margin:14px 0 6px;letter-spacing:-.02em;font-weight:680}
.lede{color:var(--muted);max-width:66ch;margin:0 0 20px;font-size:14.5px}
.lede code{font-family:var(--mono);font-size:12.5px;background:var(--elevated);
border:1px solid var(--hairline);border-radius:5px;padding:1px 5px}

/* filter chips (also the summary bar) */
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px}
.fchip{font-family:var(--mono);font-size:12px;font-weight:700;padding:7px 13px;
border-radius:999px;border:1px solid var(--hairline);background:var(--panel);color:var(--muted);
display:inline-flex;gap:8px;align-items:center;cursor:pointer;transition:border-color .15s,color .15s}
.fchip .d{width:8px;height:8px;border-radius:50%;flex:none}
.fchip .n{color:var(--ink)}
.fchip:hover{border-color:var(--faint)}
.fchip[aria-pressed=true]{border-color:var(--ember);color:var(--ink);
box-shadow:inset 0 0 0 1px var(--ember)}

/* project cards */
.card{background:var(--panel);border:1px solid var(--hairline);border-left:3px solid var(--vc);
border-radius:14px;box-shadow:var(--shadow);margin-bottom:14px;overflow:hidden}
.v-bad{--vc:var(--block)}.v-warn{--vc:var(--review)}.v-ok{--vc:var(--allow)}
.chead{display:flex;align-items:center;gap:14px;flex-wrap:wrap;width:100%;
padding:15px 18px;background:none;border:0;color:inherit;font:inherit;text-align:left;
cursor:pointer}
.chead:hover{background:var(--elevated)}
.cid{min-width:150px}
.cname{font-size:16.5px;font-weight:700;display:block}
.cpath{font-family:var(--mono);font-size:10.5px;color:var(--faint);display:block;margin-top:1px;
word-break:break-all}
.hsigs{display:flex;gap:6px 16px;flex-wrap:wrap;flex:1;min-width:220px}
.hsig{font-family:var(--mono);font-size:11.5px;color:var(--muted);white-space:nowrap}
.hsig b{font-weight:700}
.mwrap{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);
font-size:11px;color:var(--muted)}
.meter{display:inline-flex;gap:3px}
.meter i{width:13px;height:6px;border-radius:2px;background:var(--hairline)}
.meter i.on{background:var(--gc)}
.g-ok{--gc:var(--allow)}.g-warn{--gc:var(--review)}.g-bad{--gc:var(--block)}
.badge{font-family:var(--mono);font-size:11px;font-weight:700;padding:4px 11px;
border-radius:999px;color:var(--vc);background:color-mix(in srgb,var(--vc) 13%,transparent);
white-space:nowrap}
.chev{color:var(--faint);flex:none;transition:transform .18s ease}
.chead[aria-expanded=true] .chev{transform:rotate(180deg)}

/* expanded detail */
.cbody{padding:4px 18px 16px;border-top:1px solid var(--hairline)}
.cbody[hidden]{display:none}
.secgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px;
margin-top:12px}
.sec{background:var(--elevated);border:1px solid var(--hairline);border-radius:10px;
padding:11px 13px}
.sk{font-family:var(--mono);font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;
color:var(--faint);margin-bottom:7px}
.kv{display:flex;justify-content:space-between;gap:12px;padding:2.5px 0;font-size:12.5px}
.kk{font-family:var(--mono);font-size:11px;color:var(--faint);flex:none}
.kx{text-align:right;min-width:0;overflow-wrap:anywhere}
.kx.mono,.hsig{font-family:var(--mono)}
.kx.mono{font-size:11.5px}
.note{margin-top:7px;font-size:11px;color:var(--faint);line-height:1.45}
.commitmsg{margin-top:7px;font-family:var(--mono);font-size:11.5px;color:var(--muted);
background:var(--panel);border:1px solid var(--hairline);border-radius:7px;padding:6px 9px;
overflow-wrap:anywhere}
.gline{display:flex;justify-content:space-between;gap:12px;padding:2.5px 0;
font-size:12px;font-family:var(--mono)}
.gmark{font-weight:700}
.planned{margin-top:12px;border-top:1px dashed var(--hairline);padding-top:10px;
font-size:11.5px;color:var(--faint);font-family:var(--mono);line-height:1.55}
.planned b{color:var(--muted)}
.ok{color:var(--allow)}.warn{color:var(--review)}.bad{color:var(--block)}.dim{color:var(--faint)}

.emptymsg{font-family:var(--mono);font-size:12.5px;color:var(--faint);border:1px dashed
var(--hairline);border-radius:12px;padding:22px;text-align:center}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--hairline);
color:var(--faint);font-size:12px;font-family:var(--mono);line-height:1.6}

@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;
animation:none!important}}
@media(max-width:640px){.hsigs{order:5;width:100%}.chead{gap:10px}
.hsig{white-space:normal}}
"""

# Vanilla, dependency-free, no external requests. Buttons give keyboard access
# for free; state lives in aria-pressed / aria-expanded so AT stays in sync.
_JS = """
(function () {
  "use strict";
  var chips = Array.prototype.slice.call(document.querySelectorAll(".fchip"));
  var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
  var empty = document.getElementById("noneMsg");
  function applyFilter(val) {
    var shown = 0;
    cards.forEach(function (c) {
      var show = val === "all" || c.getAttribute("data-verdict") === val;
      c.hidden = !show;
      if (show) { shown += 1; }
    });
    chips.forEach(function (ch) {
      ch.setAttribute("aria-pressed", ch.getAttribute("data-filter") === val ? "true" : "false");
    });
    if (empty) { empty.hidden = shown !== 0; }
  }
  chips.forEach(function (ch) {
    ch.addEventListener("click", function () {
      applyFilter(ch.getAttribute("data-filter"));
    });
  });
  Array.prototype.slice.call(document.querySelectorAll(".chead")).forEach(function (btn) {
    var body = document.getElementById(btn.getAttribute("aria-controls"));
    if (!body) { return; }
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      body.hidden = open;
    });
  });
  applyFilter("all");
})();
"""

_GATE_LABELS: dict[str, str] = {
    "pre_commit_config": "pre-commit config",
    "pre_commit_installed": "pre-commit installed",
    "pre_push_gate": "pre-push gate",
    "ci_workflow": "CI workflow",
    "gitleaks_allowlist": "gitleaks allowlist",
    "plan_mode_first": "plan-mode first",
}

_ORDER = {"needs-attention": 0, "under-protected": 1, "healthy": 2}
_VCLASS = {"needs-attention": "v-bad", "under-protected": "v-warn", "healthy": "v-ok"}


def _esc(x: Any) -> str:
    """Escape ANY dynamic value before it reaches HTML (attrs use double quotes)."""
    return html.escape(str(x), quote=True)


def _verdict(p: dict[str, Any]) -> str:
    """Derive an honest per-project verdict from real signals only."""
    enf = p["enforcement"]
    armed = sum(bool(enf[k]) for k in enf)
    if p["secrets"].get("findings"):
        return "needs-attention"
    if armed <= 2 or not enf.get("pre_push_gate"):
        return "under-protected"
    return "healthy"


def _kv(key: str, value_html: str, mono: bool = False) -> str:
    cls = "kx mono" if mono else "kx"
    return f'<div class="kv"><span class="kk">{_esc(key)}</span><span class="{cls}">{value_html}</span></div>'


def _sec(title: str, body: str) -> str:
    return f'<div class="sec"><div class="sk">{_esc(title)}</div>{body}</div>'


def _ci_class(ci: str) -> str:
    if ci == "success":
        return "ok"
    if ci in ("failure", "cancelled", "timed_out"):
        return "bad"
    return "dim"


def _secrets_headline(sec: dict[str, Any]) -> str:
    if sec.get("findings"):
        return (f'<span class="bad">secrets {int(sec["findings"])} finding(s)'
                f" · {_esc(sec.get('scope', '?'))}</span>")
    if sec.get("clean"):
        gate = "" if sec.get("pre_push_gate") else ' · <span class="warn">no pre-push gate</span>'
        return f'<span class="ok">secrets clean</span> · {_esc(sec.get("scope", "?"))}{gate}'
    return f'<span class="dim">secrets: {_esc(sec.get("status", "?"))}</span>'


def _gates_meter(enf: dict[str, Any]) -> str:
    armed = sum(bool(enf[k]) for k in enf)
    total = len(enf)
    gcls = "g-ok" if armed >= 5 else ("g-warn" if armed >= 3 else "g-bad")
    missing = [_GATE_LABELS.get(k, k) for k in _GATE_LABELS if not enf.get(k)]
    label = f"{armed} of {total} enforcement gates armed"
    if missing:
        label += " — missing: " + ", ".join(missing)
    segs = "".join(
        f'<i class="{"on" if enf.get(k) else ""}"></i>' for k in _GATE_LABELS
    )
    return (f'<span class="mwrap {gcls}" role="img" aria-label="{_esc(label)}" '
            f'title="{_esc(label)}"><span class="meter" aria-hidden="true">{segs}</span>'
            f"{armed}/{total}</span>")


def _sec_git(g: dict[str, Any], collected_at: str) -> str:
    unc = int(g["uncommitted_files"])
    unc_html = (f'<span class="warn">{unc} file(s)</span>' if unc
                else '<span class="ok">clean tree</span>')
    remote = (f'<span class="dim">{_esc(g["remote"])}</span>' if g.get("has_remote") and g.get("remote")
              else '<span class="warn">no remote</span>')
    rows = (
        _kv("branch", _esc(g["branch"]), mono=True)
        + _kv("last commit", _esc(g["last_commit_ago"]), mono=True)
        + _kv("uncommitted", unc_html, mono=True)
        + _kv("remote", remote, mono=True)
        + _kv("collected", _esc(collected_at), mono=True)
    )
    msg = f'<div class="commitmsg">{_esc(g["last_commit"])}</div>' if g.get("last_commit") else ""
    return _sec("git", rows + msg)


def _sec_github(gh: dict[str, Any]) -> str:
    if not gh.get("connected"):
        rows = (_kv("connected", '<span class="dim">no</span>')
                + _kv("reason", f'<span class="dim">{_esc(gh.get("reason", "?"))}</span>'))
        return _sec("github", rows)
    ci = str(gh.get("latest_ci", "unknown"))
    prs = int(gh.get("open_prs", 0))
    rows = (
        _kv("connected", '<span class="ok">yes</span>')
        + _kv("open PRs", f"{prs}", mono=True)
        + _kv("CI (for HEAD)", f'<span class="{_ci_class(ci)}">{_esc(ci)}</span>', mono=True)
        + _kv("bound commit", _esc(gh.get("ci_commit", "?")), mono=True)
    )
    titles = [t for t in gh.get("pr_titles", []) if t]
    note = ""
    if titles:
        items = " · ".join(_esc(t) for t in titles)
        note = f'<div class="note">open: {items}</div>'
    return _sec("github", rows + note)


def _sec_secrets(sec: dict[str, Any]) -> str:
    if "findings" not in sec:
        rows = (_kv("tool", _esc(sec.get("tool", "gitleaks")), mono=True)
                + _kv("status", f'<span class="dim">{_esc(sec.get("status", "?"))}</span>'))
        return _sec("secrets", rows)
    findings = int(sec["findings"])
    f_html = (f'<span class="bad">{findings}</span>' if findings
              else '<span class="ok">0 — clean</span>')
    rows = (
        _kv("tool", _esc(sec.get("tool", "gitleaks")) + " (--redact)", mono=True)
        + _kv("scope", _esc(sec.get("scope", "?")), mono=True)
        + _kv("findings", f_html, mono=True)
        + _kv("noise excluded", f"{int(sec.get('noise_excluded', 0))}", mono=True)
        + _kv("allowlist", _yn(bool(sec.get("allowlist"))), mono=True)
        + _kv("pre-push gate", _yn(bool(sec.get("pre_push_gate"))), mono=True)
    )
    note = f'<div class="note">{_esc(sec["note"])}</div>' if sec.get("note") else ""
    return _sec("secrets", rows + note)


def _yn(v: bool) -> str:
    return '<span class="ok">yes</span>' if v else '<span class="warn">MISSING</span>'


def _sec_gates(enf: dict[str, Any]) -> str:
    lines = []
    for key, label in _GATE_LABELS.items():
        on = bool(enf.get(key))
        mark = ('<span class="gmark ok">&#10003; armed</span>' if on
                else '<span class="gmark bad">&#10007; missing</span>')
        lines.append(f'<div class="gline"><span>{_esc(label)}</span>{mark}</div>')
    return _sec("enforcement gates", "".join(lines))


def _sec_tests_deps(tests: dict[str, Any], deps: dict[str, Any]) -> str:
    kv = deps.get("known_vulns")
    if isinstance(kv, int):
        vulns = (f'<span class="bad">{kv} known CVEs</span>' if kv
                 else '<span class="ok">0 known CVEs</span>')
    else:
        vulns = f'<span class="dim">{_esc(kv)}</span>'
    rows = (
        _kv("test files", f"{int(tests['test_files'])}", mono=True)
        + _kv("coverage", f'<span class="dim">{_esc(tests.get("coverage", "not measured"))}</span>')
        + _kv("manifest", _esc(deps.get("manifest") or "no python manifest"), mono=True)
        + _kv("vulnerabilities", vulns, mono=True)
    )
    return _sec("tests & deps", rows)


def _sec_forge(forge: dict[str, Any]) -> str:
    runs = int(forge["governed_runs"])
    rows = (
        _kv("installed", '<span class="ok">yes</span>' if forge.get("installed")
            else '<span class="dim">no</span>', mono=True)
        + _kv("governed runs", f"{runs}", mono=True)
    )
    note = f'<div class="note">{_esc(forge["note"])}</div>' if forge.get("note") else ""
    return _sec("forge", rows + note)


def _card(p: dict[str, Any], idx: int) -> str:
    g, gh, sec, enf = p["git"], p["github"], p["secrets"], p["enforcement"]
    verdict = _verdict(p)
    vcls = _VCLASS[verdict]

    # collapsed headline: the real signals at a glance
    unc = int(g["uncommitted_files"])
    git_h = (f'<span class="hsig"><b>{_esc(g["branch"])}</b> · {_esc(g["last_commit_ago"])} · '
             + (f'<span class="warn">{unc} uncommitted</span>' if unc
                else '<span class="ok">clean tree</span>') + "</span>")
    sec_h = f'<span class="hsig">{_secrets_headline(sec)}</span>'
    if gh.get("connected"):
        ci = str(gh.get("latest_ci", "unknown"))
        gh_h = (f'<span class="hsig">CI <span class="{_ci_class(ci)}">{_esc(ci)}</span> '
                f'@ {_esc(gh.get("ci_commit", "?"))}</span>')
    else:
        gh_h = '<span class="hsig dim">github not connected</span>'

    detail = (
        _sec_git(g, str(p.get("collected_at", "")))
        + _sec_github(gh)
        + _sec_secrets(sec)
        + _sec_gates(enf)
        + _sec_tests_deps(p["tests"], p["deps"])
        + _sec_forge(p["forge"])
    )
    runs = int(p["forge"]["governed_runs"])
    planned = (
        '<div class="planned"><b>Not built yet</b> (honest): live workers · pipeline runs · '
        "engine tiering · certification. These light up only once Forge governs a real run "
        f"here — currently {runs} governed run(s).</div>"
    )
    return (
        f'<article class="card {vcls}" data-verdict="{_esc(verdict)}">'
        f'<button type="button" class="chead" id="h{idx}" aria-expanded="false" aria-controls="d{idx}">'
        f'<span class="cid"><span class="cname">{_esc(p["project"])}</span>'
        f'<span class="cpath">{_esc(p["path"])}</span></span>'
        f'<span class="hsigs">{git_h}{sec_h}{gh_h}</span>'
        f"{_gates_meter(enf)}"
        f'<span class="badge">{_esc(verdict)}</span>'
        f'<span class="chev" aria-hidden="true">&#9662;</span></button>'
        f'<div class="cbody" id="d{idx}" role="region" aria-labelledby="h{idx}" hidden>'
        f'<div class="secgrid">{detail}</div>{planned}</div></article>'
    )


def _chip(flt: str, label: str, count: int, dot: str) -> str:
    return (f'<button type="button" class="fchip" data-filter="{_esc(flt)}" aria-pressed="false">'
            f'<span class="d" style="background:{dot}" aria-hidden="true"></span>'
            f'{_esc(label)} <span class="n">{count}</span></button>')


def render(projects: list[dict[str, Any]], collected_at: str) -> str:
    ordered = sorted(projects, key=lambda p: _ORDER[_verdict(p)])
    counts = {v: sum(1 for p in projects if _verdict(p) == v) for v in _ORDER}
    chips = (
        _chip("all", "all", len(projects), "var(--faint)")
        + _chip("needs-attention", "needs attention", counts["needs-attention"], "var(--block)")
        + _chip("under-protected", "under-protected", counts["under-protected"], "var(--review)")
        + _chip("healthy", "healthy", counts["healthy"], "var(--allow)")
    )
    cards = "".join(_card(p, i) for i, p in enumerate(ordered))
    if not cards:
        cards = '<div class="emptymsg">no projects collected</div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forge — Real Project Status</title>
<style>{_CSS}</style>
<noscript><style>.cbody[hidden]{{display:block}}.chev{{display:none}}</style></noscript>
</head>
<body><div class="wrap"><div class="maxw">
<header class="mast"><span class="wordmark"><span class="spark" aria-hidden="true"></span> Forge</span>
<span class="sub">real project status · collected {_esc(collected_at)}</span></header>
<h1>Your projects, as Forge actually sees them.</h1>
<p class="lede">Every number below is collected live from the real repositories by
<code>status/forge_status.py</code> (read-only). Nothing is representative or mocked.
Click a card for the full detail; filter by verdict.</p>
<div class="filters" role="group" aria-label="filter projects by verdict">{chips}</div>
<main>{cards}
<div class="emptymsg" id="noneMsg" hidden>no projects match this filter</div></main>
<footer class="foot">real data · read-only collection · secrets scanned with --redact
(no secret values read), scope shown per project · "not built yet" means exactly that —
no faked workers, pipelines, or activity.</footer>
</div></div>
<script>{_JS}</script>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    raw = open(argv[0]).read() if argv else sys.stdin.read()
    data = json.loads(raw)
    projects = data if isinstance(data, list) else [data]
    collected = str(projects[0].get("collected_at", "")) if projects else ""
    sys.stdout.write(render(projects, collected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
