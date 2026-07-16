#!/usr/bin/env python3
"""Render the FORGE dashboard from REAL collector data — no mockup.

Reads forge_status.py JSON (one or more projects) and emits a self-contained HTML
dashboard. Everything shown is real, collected from the actual repos. Features that
Forge has not built yet (live workers, certification, engine tiering) are shown as
honest "not built yet" placeholders — never faked.

Usage:
  python3 forge_status.py <dirs...> --json | python3 render_dashboard.py > dashboard.html
  python3 render_dashboard.py status.json > dashboard.html
"""
from __future__ import annotations

import html
import json
import sys
from typing import Any

# Design tokens shared with the rest of the Forge surfaces (dark/light aware).
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
--review:#D29922;--block:#F85149;--escalate:#BC8CFF;--grid:rgba(255,255,255,.04);}
:root[data-theme=light]{--bg:#F5F6F8;--panel:#FFFFFF;--elevated:#FBFCFD;--hairline:#E2E6EC;
--ink:#1A2029;--muted:#5C6675;--faint:#8A94A3;--ember:#D4581F;--allow:#1A7F37;--tool:#0969DA;
--review:#9A6700;--block:#CF222E;--escalate:#8250DF;--grid:rgba(10,20,40,.05);}
*{box-sizing:border-box}body{margin:0}
.wrap{background:var(--bg);color:var(--ink);font-family:var(--sans);min-height:100vh;
padding:26px clamp(14px,3vw,40px) 60px;line-height:1.5;
background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);
background-size:34px 34px}
.maxw{max-width:1080px;margin:0 auto}
.mast{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:4px}
.wordmark{font-family:var(--mono);font-weight:700;font-size:15px;letter-spacing:.12em;
text-transform:uppercase;display:inline-flex;align-items:center;gap:8px}
.spark{width:10px;height:10px;border-radius:2px;background:var(--ember);
box-shadow:0 0 10px var(--ember);transform:rotate(45deg)}
.sub{font-family:var(--mono);font-size:12px;color:var(--faint)}
h1{font-size:clamp(22px,3vw,30px);margin:14px 0 6px;letter-spacing:-.02em;font-weight:680}
.lede{color:var(--muted);max-width:64ch;margin:0 0 22px;font-size:14.5px}
.summary{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px}
.schip{font-family:var(--mono);font-size:12px;font-weight:700;padding:6px 12px;border-radius:999px;
border:1px solid var(--hairline);background:var(--panel);display:inline-flex;gap:7px;align-items:center}
.schip .d{width:8px;height:8px;border-radius:50%}
.proj{background:var(--panel);border:1px solid var(--hairline);border-radius:16px;
box-shadow:var(--shadow);padding:18px 20px;margin-bottom:16px;border-top:3px solid var(--tc,var(--tool))}
.phead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.pname{font-size:18px;font-weight:700}
.ppath{font-family:var(--mono);font-size:11px;color:var(--faint)}
.pverdict{margin-left:auto;font-family:var(--mono);font-size:11px;font-weight:700;padding:4px 11px;border-radius:999px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.tile{background:var(--elevated);border:1px solid var(--hairline);border-radius:11px;padding:11px 13px}
.tk{font-family:var(--mono);font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-bottom:4px}
.tv{font-size:13.5px;font-weight:600;line-height:1.35}
.tv .sub2{display:block;font-size:11px;font-weight:400;color:var(--muted);margin-top:2px}
.ok{color:var(--allow)}.warn{color:var(--review)}.bad{color:var(--block)}.dim{color:var(--faint)}
.planned{margin-top:14px;border-top:1px dashed var(--hairline);padding-top:12px;
font-size:12px;color:var(--faint);font-family:var(--mono)}
.planned b{color:var(--muted)}
.foot{margin-top:34px;padding-top:16px;border-top:1px solid var(--hairline);
color:var(--faint);font-size:12px;font-family:var(--mono);line-height:1.6}
"""


def _esc(x: Any) -> str:
    return html.escape(str(x))


def _tile(k: str, v: str) -> str:
    return f'<div class="tile"><div class="tk">{_esc(k)}</div><div class="tv">{v}</div></div>'


def _verdict(p: dict[str, Any]) -> tuple[str, str]:
    """Derive an honest per-project verdict from real signals only."""
    enf = p["enforcement"]
    armed = sum(bool(enf[k]) for k in enf)
    sec = p["secrets"]
    if sec.get("findings"):
        return "needs-attention", "bad"
    if armed <= 2 or not enf.get("pre_push_gate"):
        return "under-protected", "warn"
    return "healthy", "ok"


def _project_html(p: dict[str, Any]) -> str:
    g, gh, sec, enf = p["git"], p["github"], p["secrets"], p["enforcement"]
    forge, tests, deps = p["forge"], p["tests"], p["deps"]
    verdict, cls = _verdict(p)
    tc = {"ok": "var(--allow)", "warn": "var(--review)", "bad": "var(--block)"}[cls]

    # git
    unc = g["uncommitted_files"]
    git_v = f'{_esc(g["branch"])}<span class="sub2">{_esc(g["last_commit_ago"])} · ' + (
        f'<span class="warn">{unc} uncommitted</span>' if unc else '<span class="ok">clean tree</span>'
    ) + "</span>"

    # github
    if gh.get("connected"):
        ci = gh.get("latest_ci", "unknown")
        ci_cls = "ok" if ci == "success" else ("bad" if ci == "failure" else "dim")
        gh_v = f'connected<span class="sub2">{gh.get("open_prs",0)} open PR · CI <span class="{ci_cls}">{_esc(ci)}</span></span>'
    else:
        gh_v = f'<span class="dim">not connected</span><span class="sub2">{_esc(gh.get("reason",""))}</span>'

    # secrets
    if sec.get("findings"):
        sec_v = f'<span class="bad">{sec["findings"]} in {_esc(sec.get("scope",""))}</span>'
    elif sec.get("clean"):
        sec_v = f'<span class="ok">clean</span><span class="sub2">{_esc(sec.get("scope",""))}' + (
            ' · <span class="warn">no pre-push gate</span>' if not sec.get("pre_push_gate") else ""
        ) + "</span>"
    else:
        sec_v = f'<span class="dim">{_esc(sec.get("status","?"))}</span>'

    # gates
    armed = sum(bool(enf[k]) for k in enf)
    gate_cls = "ok" if armed >= 5 else ("warn" if armed >= 3 else "bad")
    missing = [k.replace("_", "-") for k in enf if not enf[k]]
    gate_v = f'<span class="{gate_cls}">{armed}/6 armed</span>' + (
        f'<span class="sub2">missing: {_esc(", ".join(missing))}</span>' if missing else '<span class="sub2">all armed</span>'
    )

    tests_v = f'{tests["test_files"]} test files<span class="sub2">coverage not measured</span>'
    kv = deps.get("known_vulns")
    deps_v = ('<span class="ok">0 known CVEs</span>' if kv == 0 else f'<span class="dim">{_esc(kv)}</span>') + \
        f'<span class="sub2">{_esc(deps.get("manifest") or "no manifest")}</span>'
    forge_v = ('<span class="ok">installed</span>' if forge["installed"] else '<span class="dim">not installed</span>') + \
        f'<span class="sub2">{forge["governed_runs"]} governed runs</span>'

    tiles = "".join([
        _tile("git", git_v), _tile("github", gh_v), _tile("secrets", sec_v),
        _tile("gates", gate_v), _tile("tests", tests_v), _tile("deps", deps_v),
        _tile("forge", forge_v),
    ])

    planned = (
        '<div class="planned"><b>Not built yet</b> (honest): live workers · Forge pipeline runs · '
        'engine tiering · certification. These light up once Forge governs a real run here — '
        f'currently {forge["governed_runs"]} governed runs.</div>'
    )
    return (
        f'<div class="proj" style="--tc:{tc}">'
        f'<div class="phead"><span class="pname">{_esc(p["project"])}</span>'
        f'<span class="ppath">{_esc(p["path"])}</span>'
        f'<span class="pverdict" style="color:{tc};background:color-mix(in srgb,{tc} 14%,transparent)">{_esc(verdict)}</span></div>'
        f'<div class="tiles">{tiles}</div>{planned}</div>'
    )


def render(projects: list[dict[str, Any]], collected_at: str) -> str:
    healthy = sum(1 for p in projects if _verdict(p)[0] == "healthy")
    under = sum(1 for p in projects if _verdict(p)[0] == "under-protected")
    attn = sum(1 for p in projects if _verdict(p)[0] == "needs-attention")
    chips = (
        f'<span class="schip"><span class="d" style="background:var(--allow)"></span>{healthy} healthy</span>'
        f'<span class="schip"><span class="d" style="background:var(--review)"></span>{under} under-protected</span>'
        f'<span class="schip"><span class="d" style="background:var(--block)"></span>{attn} need attention</span>'
    )
    body = "".join(_project_html(p) for p in projects)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forge — Real Project Status</title><style>{_CSS}</style></head>
<body><div class="wrap"><div class="maxw">
<div class="mast"><span class="wordmark"><span class="spark"></span> Forge</span>
<span class="sub">real project status · collected {_esc(collected_at)}</span></div>
<h1>Your projects, as Forge actually sees them.</h1>
<p class="lede">Every number below is collected live from the real repositories by
<code>status/forge_status.py</code> (read-only). Nothing here is representative or mocked.
Where a capability isn't built yet, it says so.</p>
<div class="summary">{chips}</div>
{body}
<div class="foot">real data · read-only collection · secrets scanned with --redact (no values read) ·
scope shown per project · "not built yet" means exactly that — no faked activity.</div>
</div></div></body></html>"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    raw = open(argv[0]).read() if argv else sys.stdin.read()
    data = json.loads(raw)
    projects = data if isinstance(data, list) else [data]
    collected = projects[0].get("collected_at", "") if projects else ""
    sys.stdout.write(render(projects, collected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
