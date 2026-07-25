#!/usr/bin/env python3
"""Render the FORGE 3-tab dashboard from REAL collector data — no mockup.

Input: forge_status.py JSON (one or more projects), optionally enriched with a
"certificate" block by forge_dashboard.py. Output: one fully self-contained HTML
page — inline CSS, inline vanilla JS, zero external requests.

Three tabs, one project selector:
  Dashboard  — a designed hero per project: big verdict, Forge Verified badge,
               plain-language fact tiles, and the one top fix as a callout.
  Advanced   — every real signal as expandable cards (git, GitHub, secrets with
               scope, the 6 enforcement gates as a segmented meter, tests, deps,
               runs — real discovered traces linking to their rendered pipeline
               pages, never fabricated — forge, certificate claims with evidence).
  Configure  — HONEST reframe: a static file cannot save settings, so this tab
               inspects the real config and shows the exact shell command for
               each change, plus a live guard-rule tester that ports the actual
               deny rules from hooks/guard.py to client-side JS.

Honesty rules baked in: capabilities Forge has not built yet are "not built
yet", never faked; secrets always carry their scan scope; the certificate shows
its real level and why it is not higher. Every dynamic string that reaches the
HTML goes through html.escape (project names, paths, branches, commit messages,
PR titles, remotes, notes, evidence — all attacker-influenced). The only
unescaped interpolations are integers we cast ourselves.

Usage:
  python3 forge_dashboard.py <dirs...> -o dashboard.html          (full, with certificate)
  python3 forge_status.py <dirs...> --json | python3 render_dashboard.py > dashboard.html
"""
from __future__ import annotations

import html
import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Design tokens — shared with the other Forge surfaces (dark/light aware).
# Mono for telemetry, semantic status colors (allow/tool/review/block/escalate),
# ember used sparingly as the brand accent (wordmark spark, focus ring, active
# tab/filter, the one attention chip). prefers-reduced-motion kills every
# transition and animation (jump-cut, never lost content).
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
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
font-size:14px;line-height:1.55;
background-image:linear-gradient(var(--grid) 1px,transparent 1px),
linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:34px 34px}
.wrap{min-height:100vh;padding:16px clamp(14px,3vw,40px) 64px}
.maxw{max-width:1120px;margin:0 auto}
:focus-visible{outline:2px solid var(--ember);outline-offset:2px;border-radius:6px}
code{font-family:var(--mono)}
.ok{color:var(--allow)}.warn{color:var(--review)}.bad{color:var(--block)}.dim{color:var(--faint)}
.info{color:var(--tool)}

@keyframes viewin{from{opacity:0;transform:translateY(6px)}}
@keyframes panelin{from{opacity:0;transform:translateY(-4px)}}
@keyframes popin{from{opacity:0;transform:scale(.9)}}
@keyframes beat{0%,100%{opacity:.45}50%{opacity:1}}

/* ================= top bar ================= */
.topbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;position:sticky;top:0;
z-index:10;padding:12px 0 10px;margin-bottom:4px;
background:color-mix(in srgb,var(--bg) 90%,transparent);backdrop-filter:blur(8px)}
.wordmark{font-family:var(--mono);font-weight:700;font-size:15px;letter-spacing:.12em;
text-transform:uppercase;display:inline-flex;align-items:center;gap:8px}
.spark{width:10px;height:10px;border-radius:2px;background:var(--ember);
box-shadow:0 0 10px var(--ember);transform:rotate(45deg);flex:none}
.sub{font-family:var(--mono);font-size:11px;color:var(--faint)}
.psel{display:inline-flex;align-items:center;gap:8px}
.psel-l{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.1em;
text-transform:uppercase;color:var(--faint)}
select.scope{appearance:none;-webkit-appearance:none;font-family:var(--mono);font-size:12px;
font-weight:600;color:var(--ink);background:var(--elevated);border:1px solid var(--hairline);
border-radius:8px;padding:6px 26px 6px 10px;cursor:pointer;transition:border-color .15s;
background-image:linear-gradient(45deg,transparent 50%,var(--muted) 50%),
linear-gradient(135deg,var(--muted) 50%,transparent 50%);
background-position:right 13px top 55%,right 8px top 55%;background-size:5px 5px;
background-repeat:no-repeat}
select.scope:hover{border-color:var(--muted)}
.tabs{margin-left:auto;display:inline-flex;gap:3px;background:var(--panel);
border:1px solid var(--hairline);border-radius:11px;padding:3px}
.tab{font-family:var(--mono);font-size:11.5px;font-weight:700;letter-spacing:.05em;
padding:7px 16px;border-radius:8px;border:0;background:none;color:var(--muted);
cursor:pointer;transition:color .15s,background .15s,box-shadow .15s}
.tab:hover{color:var(--ink)}
.tab[aria-selected=true]{background:var(--elevated);color:var(--ink);
box-shadow:inset 0 0 0 1px var(--hairline),inset 0 -2px 0 var(--ember)}
h1{font-size:clamp(19px,2.4vw,24px);margin:16px 0 4px;letter-spacing:-.02em;font-weight:720}
.lede{color:var(--muted);max-width:70ch;margin:0 0 22px;font-size:13.5px}
@media(max-width:640px){.topbar{position:static}.tabs{margin-left:0;width:100%;display:flex}
.tab{flex:1;text-align:center}}
html:not(.js) .psel{display:none}
html:not(.js) .tabs{display:none}
html:not(.js) .js-only{display:none!important}
html:not(.js) .car{display:none}
html:not(.js) .fchip{display:none}

/* ================= views ================= */
.view{min-width:0}
.js .view{display:none}
.js .view.active{display:block;animation:viewin .22s ease}
.viewlabel{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.14em;
text-transform:uppercase;color:var(--faint);border-top:2px solid var(--hairline);
padding-top:14px;margin:30px 0 12px}
.js .viewlabel{display:none}
.card{background:var(--panel);border:1px solid var(--hairline);border-radius:16px;
box-shadow:var(--shadow);padding:20px 22px;min-width:0}

/* ================= dashboard hero ================= */
.v-bad{--vc:var(--block)}.v-warn{--vc:var(--review)}.v-ok{--vc:var(--allow)}
.hero{margin-bottom:18px;border-left:4px solid var(--vc);padding:22px 24px 20px}
.herotop{display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap}
.dico{width:54px;height:54px;border-radius:14px;flex:none;display:grid;place-items:center;
color:var(--vc);background:color-mix(in srgb,var(--vc) 12%,transparent)}
.dico svg{width:30px;height:30px}
.hmain{flex:1 1 300px;min-width:0}
.hname{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.1em;
text-transform:uppercase;color:var(--muted);display:flex;gap:10px;align-items:baseline;
flex-wrap:wrap}
.hpath{font-family:var(--mono);font-size:10px;font-weight:400;letter-spacing:0;
text-transform:none;color:var(--faint);word-break:break-all}
.hverdict{font-size:clamp(23px,3.2vw,31px);font-weight:750;letter-spacing:-.02em;
margin:6px 0 4px;line-height:1.15}
.hverdict .vword{color:var(--vc)}
.hsub{color:var(--muted);font-size:13.5px;max-width:62ch;margin:0 0 12px}
.hchips{display:flex;gap:8px;flex-wrap:wrap}
.hchip{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.04em;
padding:5px 12px;border-radius:999px;border:1px solid var(--hairline);
background:var(--elevated);color:var(--muted);display:inline-flex;align-items:center;gap:7px}
.hchip.att{color:var(--ember);border-color:color-mix(in srgb,var(--ember) 50%,var(--hairline));
background:color-mix(in srgb,var(--ember) 9%,var(--elevated))}
.hchip.okc{color:var(--allow)}
.hdot{width:8px;height:8px;border-radius:50%;background:currentColor;flex:none;
animation:beat 2s ease-in-out infinite}
.cert{flex:none;display:flex;gap:13px;align-items:center;border-radius:14px;
padding:12px 16px;max-width:350px;background:color-mix(in srgb,var(--lc) 6%,var(--elevated));
border:1px solid color-mix(in srgb,var(--lc) 32%,var(--hairline))}
.lv-0{--lc:var(--faint)}.lv-1{--lc:var(--tool)}.lv-2{--lc:var(--allow)}.lv-3{--lc:var(--escalate)}
.certmark{width:48px;height:48px;border-radius:12px;flex:none;display:grid;place-items:center;
font-family:var(--mono);font-weight:800;font-size:17px;color:var(--lc);
background:color-mix(in srgb,var(--lc) 13%,transparent);
border:1px solid color-mix(in srgb,var(--lc) 45%,transparent);
box-shadow:0 0 18px color-mix(in srgb,var(--lc) 16%,transparent)}
.certname{font-weight:700;font-size:13px}
.certwhy{font-size:11.5px;color:var(--muted);line-height:1.5;margin-top:2px}
/* fact tiles */
.facts{display:flex;flex-wrap:wrap;gap:1px;
background:var(--hairline);border:1px solid var(--hairline);border-radius:13px;
overflow:hidden;margin-top:18px}
.fact{flex:1 1 150px;background:var(--panel);padding:13px 16px 14px;display:flex;
flex-direction:column;gap:2px;min-width:0;transition:background .15s}
.fact:hover{background:var(--elevated)}
.fact .fn{font-family:var(--mono);font-size:21px;line-height:28px;font-weight:700;
font-variant-numeric:tabular-nums;letter-spacing:-.01em;overflow-wrap:anywhere}
.fact .fn.fn-sm{font-size:13px}
.fact .ft{font-size:12.5px;font-weight:600;color:var(--ink)}
.fact .fs{font-size:11px;color:var(--faint);overflow-wrap:anywhere}
.f-ok .fn{color:var(--allow)}.f-warn .fn{color:var(--review)}
.f-bad .fn{color:var(--block)}.f-dim .fn{color:var(--faint)}
/* the one fix callout */
.sev-block{--sc:var(--block)}.sev-review{--sc:var(--review)}.sev-tool{--sc:var(--tool)}
.sev-ok{--sc:var(--allow)}
.hfix{margin-top:16px;border-radius:13px;padding:15px 17px;
border:1px solid color-mix(in srgb,var(--sc) 32%,var(--hairline));
border-left:3px solid var(--sc);background:color-mix(in srgb,var(--sc) 5%,var(--panel))}
.hfix.sev-block{box-shadow:0 0 24px color-mix(in srgb,var(--sc) 10%,transparent)}
.hfixhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.hfixlab{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.09em;
text-transform:uppercase;color:var(--sc);padding:3px 9px;border-radius:999px;flex:none;
background:color-mix(in srgb,var(--sc) 14%,transparent)}
.hfixtitle{font-weight:700;font-size:14.5px}
.hfixwhy{color:var(--muted);font-size:13px;margin:0;max-width:75ch}
.cmd{display:flex;align-items:center;gap:10px;background:var(--elevated);
border:1px solid var(--hairline);border-radius:10px;padding:9px 12px;margin-top:11px}
.cmd code{font-size:12px;white-space:pre;overflow-x:auto;flex:1;display:block;
color:var(--ink);scrollbar-width:thin}
.copy{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.06em;
text-transform:uppercase;color:var(--muted);background:var(--panel);
border:1px solid var(--hairline);border-radius:7px;padding:5px 10px;cursor:pointer;
flex:none;transition:color .15s,border-color .15s}
.copy:hover{color:var(--ink);border-color:var(--muted)}
.copy.done{color:var(--allow);border-color:color-mix(in srgb,var(--allow) 45%,var(--hairline))}
.linklike{background:none;border:0;color:var(--tool);font:inherit;font-size:12.5px;
cursor:pointer;padding:0;margin-top:12px;text-decoration:underline;
text-underline-offset:3px;display:inline-block}
.linklike:hover{color:var(--ink)}

/* ================= fleet strip ================= */
.fleetstrip{margin-bottom:18px;padding:16px 20px}
.fleetcounts{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.1em;
text-transform:uppercase;color:var(--faint);margin-bottom:6px}
.fleetrow{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:10px 8px;
margin:0 -8px;border-top:1px solid var(--hairline);border-radius:10px;font-size:13px;
transition:background .15s}
.fleetrow:hover{background:var(--elevated)}
.fleetrow .fn2{font-weight:700;font-size:14px;min-width:130px}
.vpill{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.06em;
text-transform:uppercase;padding:3px 10px;border-radius:999px;color:var(--vc);flex:none;
background:color-mix(in srgb,var(--vc) 13%,transparent);white-space:nowrap}
.lvchip{font-family:var(--mono);font-size:10.5px;font-weight:800;padding:3px 9px;
border-radius:6px;color:var(--lc);background:color-mix(in srgb,var(--lc) 13%,transparent);
border:1px solid color-mix(in srgb,var(--lc) 40%,transparent);white-space:nowrap;flex:none}
.ftop{font-family:var(--mono);font-size:11px;color:var(--muted);flex:1;min-width:160px;
overflow-wrap:anywhere}

/* ================= filter chips (fleet scope, Advanced) ================= */
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.fchip{font-family:var(--mono);font-size:11.5px;font-weight:700;padding:6px 13px;
border-radius:999px;border:1px solid var(--hairline);background:var(--panel);
color:var(--muted);display:inline-flex;gap:8px;align-items:center;cursor:pointer;
transition:border-color .15s,color .15s,box-shadow .15s}
.fchip .d{width:8px;height:8px;border-radius:50%;flex:none}
.fchip .n{color:var(--ink);font-variant-numeric:tabular-nums}
.fchip:hover{border-color:var(--muted);color:var(--ink)}
.fchip[aria-pressed=true]{border-color:var(--ember);color:var(--ink);
box-shadow:inset 0 0 0 1px var(--ember)}
.fleet-only{display:none}
body.fleet .fleet-only{display:flex}
.fhide{display:none!important}

/* ================= advanced: project block + signal cards ================= */
.pblock{margin-bottom:26px}
.pbhead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:4px 0 12px}
.pbname{font-size:17px;font-weight:750;letter-spacing:-.01em}
.pbpath{font-family:var(--mono);font-size:10px;color:var(--faint);word-break:break-all}
.sig{background:var(--panel);border:1px solid var(--hairline);border-radius:13px;
box-shadow:var(--shadow);margin-bottom:10px;overflow:hidden;transition:border-color .15s}
.sig:hover{border-color:color-mix(in srgb,var(--faint) 55%,var(--hairline))}
.shead{display:flex;align-items:center;gap:14px;flex-wrap:wrap;width:100%;
padding:13px 18px;background:none;border:0;color:inherit;font:inherit;text-align:left;
cursor:pointer;transition:background .15s}
.shead:hover{background:var(--elevated)}
.shead:hover .car{color:var(--ember)}
.stitle{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.1em;
text-transform:uppercase;color:var(--muted);min-width:120px}
.ssum{font-family:var(--mono);font-size:11.5px;color:var(--muted);flex:1;min-width:200px;
display:flex;gap:6px 14px;flex-wrap:wrap;font-variant-numeric:tabular-nums}
.car{display:inline-block;font-size:10px;color:var(--faint);flex:none;
transition:transform .18s ease,color .15s}
.shead[aria-expanded=true] .car{transform:rotate(90deg);color:var(--ember)}
.sbody{padding:6px 18px 16px;border-top:1px solid var(--hairline)}
.js .sbody{display:none}
.js .sbody.open{display:block;animation:panelin .18s ease}
.kv{display:flex;justify-content:space-between;gap:12px;padding:4px 0;font-size:13px}
.kk{font-family:var(--mono);font-size:11px;color:var(--faint);flex:none}
.kx{text-align:right;min-width:0;overflow-wrap:anywhere}
.kx.mono{font-family:var(--mono);font-size:11.5px;font-variant-numeric:tabular-nums}
.note{margin-top:9px;font-size:11.5px;color:var(--faint);line-height:1.55}
.commitmsg{margin-top:9px;font-family:var(--mono);font-size:11.5px;color:var(--muted);
background:var(--elevated);border:1px solid var(--hairline);border-radius:8px;
padding:7px 10px;overflow-wrap:anywhere}
/* segmented gates meter */
.mwrap{display:inline-flex;align-items:center;gap:9px;font-family:var(--mono);
font-size:11.5px;color:var(--muted)}
.meter{display:inline-flex;gap:3px}
.meter i{width:17px;height:8px;border-radius:3px;background:var(--hairline);
transition:background .2s}
.meter i.on{background:var(--gc);
box-shadow:0 0 8px color-mix(in srgb,var(--gc) 45%,transparent)}
.mn{font-weight:700;font-variant-numeric:tabular-nums;color:var(--gc)}
.g-ok{--gc:var(--allow)}.g-warn{--gc:var(--review)}.g-bad{--gc:var(--block)}
.gline{display:flex;justify-content:space-between;gap:12px;padding:4px 0;
font-size:12.5px;font-family:var(--mono)}
.gmark{font-weight:700;flex:none}
/* certificate claims checklist */
.claim{display:flex;gap:10px;padding:9px 0;border-top:1px solid var(--hairline);
font-size:12.5px}
.claim:first-of-type{border-top:0;margin-top:6px}
.claim .ck{font-family:var(--mono);font-weight:700;font-size:12px;flex:none;width:16px}
.claim .cbody2{min-width:0}
.claim b{font-family:var(--mono);font-size:11.5px}
.claimev{color:var(--muted);font-size:11.5px;overflow-wrap:anywhere}
.repro{font-family:var(--mono);font-size:10.5px;color:var(--faint);margin-top:3px;
overflow-wrap:anywhere}
.planned{margin-top:8px;border-top:1px dashed var(--hairline);padding-top:9px;
font-size:11px;color:var(--faint);font-family:var(--mono);line-height:1.55}
.planned b{color:var(--muted)}
.emptymsg{font-family:var(--mono);font-size:12.5px;color:var(--faint);
border:1px dashed var(--hairline);border-radius:12px;padding:22px;text-align:center}
/* runs card (Advanced): one row per REAL discovered trace */
.runrow{display:flex;gap:8px 14px;align-items:baseline;flex-wrap:wrap;
padding:8px 0;border-top:1px solid var(--hairline);font-size:12.5px}
.runrow:first-of-type{border-top:0;padding-top:4px}
.runout{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.06em;
text-transform:uppercase;padding:2.5px 9px;border-radius:999px;flex:none}
.ro-ok{color:var(--allow);background:color-mix(in srgb,var(--allow) 13%,transparent)}
.ro-esc{color:var(--escalate);background:color-mix(in srgb,var(--escalate) 13%,transparent)}
.ro-dim{color:var(--muted);background:var(--elevated);border:1px solid var(--hairline)}
.runtask{font-weight:600;min-width:0;overflow-wrap:anywhere}
.runid{font-family:var(--mono);font-size:11px;color:var(--muted);overflow-wrap:anywhere}
.runmeta{font-family:var(--mono);font-size:11px;color:var(--faint);
font-variant-numeric:tabular-nums}
.runlink{font-family:var(--mono);font-size:11.5px;margin-left:auto;flex:none;
color:var(--tool);text-decoration:none;text-underline-offset:3px}
a.runlink:hover{color:var(--ink);text-decoration:underline}
.norun{font-family:var(--mono);font-size:12px;color:var(--muted);line-height:1.7;
border:1px dashed var(--hairline);border-radius:10px;padding:14px 16px;margin-top:8px}
.norun code{color:var(--ember);font-size:11.5px}

/* ================= configure ================= */
.rulenote{border:1px solid var(--hairline);border-left:3px solid var(--tool);
border-radius:12px;background:color-mix(in srgb,var(--tool) 5%,var(--panel));
padding:12px 16px;font-size:13px;color:var(--muted);margin-bottom:18px}
.cfgblock{margin-bottom:26px}
.cfggrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;
align-items:start}
.cfgcard{padding:18px 20px}
.cfgh{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.12em;
text-transform:uppercase;color:var(--faint);margin-bottom:12px;display:flex;gap:8px;
align-items:center;flex-wrap:wrap}
.cfgh .pill{font-size:9.5px;padding:2.5px 8px;border-radius:999px;letter-spacing:.08em;
color:var(--allow);background:color-mix(in srgb,var(--allow) 13%,transparent)}
.gate{display:flex;align-items:center;gap:10px;padding:9px 0;
border-top:1px solid var(--hairline);font-size:13px;color:var(--ink)}
.gate:first-of-type{border-top:0}
.gate .ic{width:9px;height:9px;border-radius:3px;flex:none;background:var(--allow)}
.gate.off .ic{background:var(--block)}
.gate .st{margin-left:auto;font-family:var(--mono);font-size:10.5px;font-weight:700;
letter-spacing:.06em;color:var(--allow)}
.gate.off .st{color:var(--block)}
.posture{display:flex;align-items:center;gap:10px;padding-bottom:10px;font-size:13px}
.posture .pk{font-family:var(--mono);font-size:11px;color:var(--faint)}
.posture .vpill{margin-left:auto}
.fix{border-top:1px dashed var(--hairline);padding:12px 0}
.fix:first-of-type{border-top:0;padding-top:2px}
.fixtitle{font-weight:700;font-size:13.5px;display:flex;align-items:center;gap:8px}
.sevdot{width:8px;height:8px;border-radius:50%;background:var(--sc);flex:none}
.fixwhy{color:var(--muted);font-size:12.5px;margin-top:2px;max-width:75ch}
.allgood{font-size:13px;color:var(--allow);font-weight:600}
/* guard tester */
.tester{margin-top:6px;padding:20px 22px}
.gtlab{display:block;font-size:12.5px;color:var(--muted);margin-bottom:9px;max-width:80ch}
.gin{width:100%;font-family:var(--mono);font-size:13px;padding:10px 12px;border-radius:9px;
border:1px solid var(--hairline);background:var(--elevated);color:var(--ink);
transition:border-color .15s}
.gin::placeholder{color:var(--faint)}
.gin:hover{border-color:var(--muted)}
.gin:focus{outline:2px solid var(--ember);outline-offset:1px}
.gout{margin-top:12px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
min-height:26px;font-size:12.5px;color:var(--muted)}
.gt-verdict{font-family:var(--mono);font-size:11px;font-weight:700;letter-spacing:.08em;
padding:4px 12px;border-radius:999px;flex:none}
.js .gt-verdict{animation:popin .18s ease}
.gt-verdict.blk{color:var(--block);background:color-mix(in srgb,var(--block) 14%,transparent)}
.gt-verdict.alw{color:var(--allow);background:color-mix(in srgb,var(--allow) 12%,transparent)}
.gexs{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;align-items:center}
.gexs .fl{font-family:var(--mono);font-size:10px;color:var(--faint);letter-spacing:.08em;
text-transform:uppercase}
.gex{font-family:var(--mono);font-size:10.5px;font-weight:600;color:var(--muted);
background:var(--elevated);border:1px solid var(--hairline);border-radius:999px;
padding:4px 10px;cursor:pointer;transition:color .15s,border-color .15s}
.gex:hover{color:var(--ink);border-color:var(--muted)}

.foot{margin-top:36px;padding-top:16px;border-top:1px solid var(--hairline);
color:var(--faint);font-size:11.5px;font-family:var(--mono);line-height:1.6}

@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;
animation:none!important}}
@media(max-width:640px){.herotop{flex-direction:column}
.hmain{flex:0 0 auto;width:100%}.cert{max-width:none;width:100%}
.ssum{order:5;width:100%}}
"""

# ---------------------------------------------------------------------------
# Inline JS. Vanilla, dependency-free, zero external requests. Runs only when
# JS is available (the .js gate on <html> is set by a tiny head script); without
# JS the page renders fully static: tabs stacked with view labels, every card
# open. The guard tester is a faithful client-side port of the built-in deny
# rules in hooks/guard.py (same segmentation, same regexes) — see _JS comments.
# ---------------------------------------------------------------------------
_HEAD_JS = 'document.documentElement.className += " js";'

_JS = r"""
(function () {
  "use strict";
  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  /* ---------------- tabs (WAI-ARIA pattern: roving tabindex + arrows) ------ */
  var tabs = $$("[role=tab]");
  var panels = tabs.map(function (t) {
    return document.getElementById(t.getAttribute("aria-controls"));
  });
  function selectTab(idx, focus) {
    tabs.forEach(function (t, i) {
      var on = i === idx;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      if (panels[i]) { panels[i].classList.toggle("active", on); }
    });
    if (focus) { tabs[idx].focus(); }
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { selectTab(i, false); });
    t.addEventListener("keydown", function (e) {
      var n = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { n = (i + 1) % tabs.length; }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { n = (i - 1 + tabs.length) % tabs.length; }
      else if (e.key === "Home") { n = 0; }
      else if (e.key === "End") { n = tabs.length - 1; }
      if (n !== null) { e.preventDefault(); selectTab(n, true); }
    });
  });
  $$("[data-goto]").forEach(function (b) {
    b.addEventListener("click", function () {
      var want = "tab-" + b.getAttribute("data-goto");
      for (var i = 0; i < tabs.length; i += 1) {
        if (tabs[i].id === want) { selectTab(i, true); return; }
      }
    });
  });

  /* ---------------- project scope selector -------------------------------- */
  var scopeSel = document.getElementById("scope");
  var scoped = $$(".scoped");
  var curFilter = "all";
  function applyScope() {
    var val = scopeSel ? scopeSel.value : "fleet";
    var fleet = val === "fleet";
    document.body.classList.toggle("fleet", fleet);
    scoped.forEach(function (el) {
      el.hidden = !(fleet || el.getAttribute("data-p") === val);
    });
    applyFilter(curFilter);
  }
  if (scopeSel) { scopeSel.addEventListener("change", applyScope); }

  /* ---------------- verdict filter chips (fleet view, Advanced tab) -------- */
  var chips = $$(".fchip");
  function applyFilter(val) {
    curFilter = val;
    var fleet = document.body.classList.contains("fleet");
    var visible = 0;
    $$(".pblock").forEach(function (b) {
      var match = val === "all" || b.getAttribute("data-verdict") === val;
      var hide = fleet && !match;
      b.classList.toggle("fhide", hide);
      if (!b.hidden && !hide) { visible += 1; }
    });
    chips.forEach(function (c) {
      c.setAttribute("aria-pressed", c.getAttribute("data-filter") === val ? "true" : "false");
    });
    var empty = document.getElementById("advEmpty");
    if (empty) { empty.hidden = visible !== 0; }
  }
  chips.forEach(function (c) {
    c.addEventListener("click", function () { applyFilter(c.getAttribute("data-filter")); });
  });

  /* ---------------- expandable signal cards (one open at a time) ----------- */
  var heads = $$(".shead");
  function setOpen(btn, open) {
    var body = document.getElementById(btn.getAttribute("aria-controls"));
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (body) { body.classList.toggle("open", open); }
  }
  heads.forEach(function (btn) {
    setOpen(btn, false); // server renders open for no-JS; collapse for the app view
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      if (!open) {
        heads.forEach(function (o) { if (o !== btn) { setOpen(o, false); } });
      }
      setOpen(btn, !open);
    });
  });

  /* ---------------- copy-to-clipboard for fix commands --------------------- */
  function legacyCopy(txt) {
    var ta = document.createElement("textarea");
    ta.value = txt;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }
  $$(".copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var code = btn.parentNode.querySelector("code");
      var txt = code ? code.textContent : "";
      function done(ok) {
        btn.textContent = ok ? "copied ✓" : "copy failed";
        btn.classList.toggle("done", ok);
        setTimeout(function () {
          btn.textContent = "copy";
          btn.classList.remove("done");
        }, 1400);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(
          function () { done(true); },
          function () { done(legacyCopy(txt)); }
        );
      } else {
        done(legacyCopy(txt));
      }
    });
  });

  /* ---------------- guard tester ------------------------------------------
     Client-side port of the BUILT-IN deny rules in hooks/guard.py (is_denied):
     same shell-separator segmentation, same regexes. Project-specific
     deny-extra.txt patterns are NOT evaluated here — a static page cannot read
     files. Like the real guard, this is a best-effort footgun-catcher, not a
     security boundary. */
  var SEP = /&&|\|\||[;\n|]/;
  var STATIC_DENY = [
    [/\bmkfs\b/, "mkfs (filesystem format)"],
    [/\bdd\s+if=/, "dd if= (raw disk write)"],
    [/\bdrop\s+(table|database)\b/, "DROP TABLE / DROP DATABASE"],
    [/\btruncate\s+table\b/, "TRUNCATE TABLE"],
    [/:\s*\(\s*\)\s*\{[\s\S]*\}\s*;\s*:/, "fork bomb"],
    [/>\s*\/dev\/sd[a-z]\d*/, "write to raw block device"],
    [/\bfind\s+\/\s[\s\S]*-delete\b/, "find / ... -delete"]
  ];
  function segDenied(seg) {
    if (/\brm\b/.test(seg)) {
      var recursive = /--recursive|-[a-z]*r/.test(seg);
      var force = /--force|-[a-z]*f/.test(seg);
      var target = /(^|[\s=])(\/|~|\/\*)(\s|$)/.test(seg) ||
        seg.indexOf("--no-preserve-root") !== -1;
      if (recursive && force && target) { return "rm: recursive+force on / or ~"; }
    }
    if (/\bgit\s+push\b/.test(seg)) {
      if (/--force|--force-with-lease|(^|\s)-[a-z]*f(\s|$)/.test(seg)) {
        return "git push with a force flag";
      }
      if (/\s\+\S/.test(seg)) { return "git push +refspec (forced update)"; }
    }
    if (/\bchmod\b/.test(seg) && seg.indexOf("777") !== -1) {
      if (/--recursive|-[a-z]*r/.test(seg) && /(^|[\s=])\/(\s|$)/.test(seg)) {
        return "chmod -R 777 on /";
      }
    }
    return null;
  }
  function whyDenied(command) {
    var c = command.toLowerCase();
    var segs = c.split(SEP);
    for (var i = 0; i < segs.length; i += 1) {
      var r = segDenied(segs[i]);
      if (r) { return r; }
    }
    for (var j = 0; j < STATIC_DENY.length; j += 1) {
      if (STATIC_DENY[j][0].test(c)) { return STATIC_DENY[j][1]; }
    }
    return null;
  }
  var gin = document.getElementById("gcmd");
  var gout = document.getElementById("gout");
  var lastVerdict = "";
  function judge() {
    if (!gin || !gout) { return; }
    var v = gin.value;
    if (!v.replace(/\s/g, "")) {
      lastVerdict = "";
      gout.innerHTML = '<span class="dim">verdict appears here as you type — nothing is executed</span>';
      return;
    }
    var why = whyDenied(v);
    var verdict = why ? "blk" : "alw";
    if (verdict !== lastVerdict) {
      lastVerdict = verdict;
      gout.innerHTML = why
        ? '<span class="gt-verdict blk">&#10007; BLOCKED</span><span class="why"></span>'
        : '<span class="gt-verdict alw">&#10003; allowed</span><span class="why"></span>';
    }
    gout.querySelector(".why").textContent = why
      ? "matched rule: " + why + " — denied before execution; the agent never sees the result."
      : "no built-in deny rule matched (project deny-extra.txt rules not evaluated here).";
  }
  if (gin) {
    gin.addEventListener("input", judge);
    judge();
  }
  $$(".gex").forEach(function (b) {
    b.addEventListener("click", function () {
      if (gin) {
        gin.value = b.textContent;
        lastVerdict = "";
        judge();
        gin.focus();
      }
    });
  });

  /* ---------------- init ---------------------------------------------------- */
  if (tabs.length) { selectTab(0, false); }
  applyScope();
})();
"""

_GATE_LABELS: dict[str, str] = {
    "pre_commit_config": "pre-commit config",
    "pre_commit_installed": "pre-commit installed",
    "pre_push_gate": "pre-push secret gate",
    "ci_workflow": "CI workflow",
    "gitleaks_allowlist": "gitleaks allowlist",
    "plan_mode_first": "plan-mode first",
}

_ORDER = {"needs-attention": 0, "under-protected": 1, "healthy": 2}
_VCLASS = {"needs-attention": "v-bad", "under-protected": "v-warn", "healthy": "v-ok"}
_VWORD = {
    "needs-attention": "Needs attention",
    "under-protected": "Under-protected",
    "healthy": "Protected",
}
# certificate level -> (big glyph, human name, css class)
_LEVEL_META = {
    "L1": ("L1", "Forge Verified — Gated", "lv-1"),
    "L2": ("L2", "Forge Verified — Verified", "lv-2"),
    "L3": ("L3", "Forge Verified — Provenanced", "lv-3"),
    "none": ("—", "Not certified", "lv-0"),
}
# hero icon per verdict — static inline SVG (stroke follows the verdict color)
_SHIELD = ('M12 3l7 3v5c0 4.6-2.9 8.1-7 10-4.1-1.9-7-5.4-7-10V6z')
_ICONS = {
    "healthy": (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                f'<path d="{_SHIELD}"/><path d="M9 12.2l2.1 2.1L15.3 10"/></svg>'),
    "under-protected": (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                        f'<path d="{_SHIELD}"/><path d="M12 8.5v4"/>'
                        f'<path d="M12 15.5h.01"/></svg>'),
    "needs-attention": (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                        f'<path d="{_SHIELD}"/><path d="M9.5 9.5l5 5"/>'
                        f'<path d="M14.5 9.5l-5 5"/></svg>'),
}


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


# ---------------------------------------------------------------------------
# Gap -> remedy. Every flagged gap carries its exact fix command; the Dashboard
# shows the top one, Configure shows them all. Commands are static strings we
# author (no project data interpolated), still escaped at render time.
# $CLAUDE_PLUGIN_ROOT is the Forge plugin checkout (set in Claude Code hooks;
# substitute the plugin path when running by hand).
# ---------------------------------------------------------------------------
def _fixes(p: dict[str, Any]) -> list[dict[str, str]]:
    enf, sec, forge, g = p["enforcement"], p["secrets"], p["forge"], p["git"]
    deps = p["deps"]
    fixes: list[dict[str, str]] = []
    if sec.get("findings"):
        n = int(sec["findings"])
        fixes.append({
            "sev": "block",
            "title": f"{n} possible secret(s) in committed history",
            "why": (f"gitleaks flagged {n} finding(s) in the scanned scope "
                    f"({sec.get('scope', '?')}). Inspect them (values stay redacted), "
                    "rotate anything real, then allowlist confirmed false positives "
                    "in .gitleaks.toml."),
            "cmd": "gitleaks git --redact -v",
        })
    if not forge.get("installed"):
        fixes.append({
            "sev": "review",
            "title": "Forge is not initialised in this project",
            "why": ("Run /forge-init in Claude Code (idempotent — stamps only what is "
                    "missing): CLAUDE.md, pre-commit config, gitleaks allowlist, CI "
                    "workflow, pre-push gate, plan-mode-first, and .forge/memory.db."),
            "cmd": "/forge-init",
        })
    if not enf.get("pre_push_gate"):
        fixes.append({
            "sev": "review",
            "title": "Pre-push secret gate is not installed",
            "why": ("Nothing scans commits at push time — the authoritative moment a "
                    "secret would leave this machine."),
            "cmd": ('cp "$CLAUDE_PLUGIN_ROOT/templates/pre-push" .git/hooks/pre-push '
                    "&& chmod +x .git/hooks/pre-push"),
        })
    if enf.get("pre_commit_config") and not enf.get("pre_commit_installed"):
        fixes.append({
            "sev": "review",
            "title": "pre-commit config exists but the hook is not installed",
            "why": (".pre-commit-config.yaml is present, yet no .git/hooks/pre-commit "
                    "— the checks never actually run on commit."),
            "cmd": "pre-commit install",
        })
    if not enf.get("pre_commit_config"):
        fixes.append({
            "sev": "review",
            "title": "No pre-commit config",
            "why": "No lint/secret checks run at commit time.",
            "cmd": ('cp "$CLAUDE_PLUGIN_ROOT/templates/pre-commit-config.yaml" '
                    ".pre-commit-config.yaml && pre-commit install"),
        })
    if not enf.get("ci_workflow"):
        fixes.append({
            "sev": "review",
            "title": "No CI workflow",
            "why": "Nothing verifies pushed commits server-side.",
            "cmd": ("mkdir -p .github/workflows && "
                    'cp "$CLAUDE_PLUGIN_ROOT/templates/ci-pipeline.yml" '
                    ".github/workflows/forge-ci.yml"),
        })
    if not enf.get("gitleaks_allowlist"):
        fixes.append({
            "sev": "tool",
            "title": "No gitleaks allowlist",
            "why": ("Without .gitleaks.toml the secret scans are noisy; the Forge "
                    "template excludes known false-positive paths."),
            "cmd": 'cp "$CLAUDE_PLUGIN_ROOT/templates/.gitleaks.toml" .gitleaks.toml',
        })
    if forge.get("installed") and not enf.get("plan_mode_first"):
        fixes.append({
            "sev": "tool",
            "title": "Sessions do not start in plan mode",
            "why": ("permissions.defaultMode != \"plan\" in .claude/settings.json. "
                    "/forge-init merges it in idempotently (never clobbers other "
                    "settings)."),
            "cmd": "/forge-init",
        })
    if not g.get("has_remote"):
        fixes.append({
            "sev": "tool",
            "title": "No git remote",
            "why": ("Work only exists on this machine. Forge standard: a PRIVATE "
                    "repo before real work."),
            "cmd": "gh repo create --private --source . --push",
        })
    kv = deps.get("known_vulns")
    if isinstance(kv, int) and kv > 0:
        fixes.append({
            "sev": "block",
            "title": f"{int(kv)} known dependency CVE(s)",
            "why": "pip-audit found known-vulnerable pinned dependencies.",
            "cmd": "pip-audit",
        })
    return fixes


# ---------------------------------------------------------------------------
# Small HTML helpers (everything dynamic goes through _esc).
# ---------------------------------------------------------------------------
def _kv(key: str, value_html: str, mono: bool = False) -> str:
    cls = "kx mono" if mono else "kx"
    return (f'<div class="kv"><span class="kk">{_esc(key)}</span>'
            f'<span class="{cls}">{value_html}</span></div>')


def _yn(v: bool) -> str:
    return '<span class="ok">yes</span>' if v else '<span class="warn">MISSING</span>'


def _ci_class(ci: str) -> str:
    if ci == "success":
        return "ok"
    if ci in ("failure", "cancelled", "timed_out"):
        return "bad"
    return "dim"


def _cmdblock(cmd: str) -> str:
    return (f'<div class="cmd"><code>{_esc(cmd)}</code>'
            '<button type="button" class="copy js-only">copy</button></div>')


def _gates_meter(enf: dict[str, Any]) -> str:
    armed = sum(bool(enf[k]) for k in enf)
    total = len(enf)
    gcls = "g-ok" if armed >= 5 else ("g-warn" if armed >= 3 else "g-bad")
    missing = [_GATE_LABELS.get(k, k) for k in _GATE_LABELS if not enf.get(k)]
    label = f"{armed} of {total} enforcement gates armed"
    if missing:
        label += " — missing: " + ", ".join(missing)
    segs = "".join(f'<i class="{"on" if enf.get(k) else ""}"></i>' for k in _GATE_LABELS)
    return (f'<span class="mwrap {gcls}" role="img" aria-label="{_esc(label)}" '
            f'title="{_esc(label)}"><span class="meter" aria-hidden="true">{segs}</span>'
            f'<span class="mn">{armed}/{total}</span></span>')


def _level_meta(cert: dict[str, Any] | None) -> tuple[str, str, str, str]:
    """(glyph, name, css_class, why-line) — level whitelisted through _LEVEL_META,
    never interpolated raw into a class attribute."""
    if cert is None:
        return ("?", "Certificate not computed",
                "lv-0", "Run status/forge_dashboard.py to compute the Forge Verified "
                "certificate for this project (plain forge_status JSON has none).")
    glyph, name, cls = _LEVEL_META.get(str(cert.get("level")), _LEVEL_META["none"])
    level = str(cert.get("level"))
    claims = [c for c in cert.get("claims", []) if isinstance(c, dict)]
    failing = [str(c.get("name", "?")) for c in claims if not c.get("passed")]
    runs = int(cert.get("governed_runs", 0))
    if level == "L3":
        why = f"Every claim green and {runs} Forge-governed run(s) recorded."
    elif level == "L2":
        why = (f"L3 (provenanced) needs Forge-governed run history — this project has "
               f"{runs} governed run(s).")
    elif level == "L1":
        why = "Enforcement armed; failing for L2: " + (", ".join(failing) or "?") + "."
    else:
        why = ("Not L1: enforcement not fully armed (needs pre-push gate + CI + "
               "pre-commit config).")
    return glyph, name, cls, why


# ---------------------------------------------------------------------------
# Tab 1 — Dashboard (plain language)
# ---------------------------------------------------------------------------
def _fact(cls: str, value: str, label: str, sub: str) -> str:
    vcls = "fn fn-sm" if len(value) > 8 else "fn"
    return (f'<div class="fact {cls}"><span class="{vcls}">{_esc(value)}</span>'
            f'<span class="ft">{_esc(label)}</span>'
            f'<span class="fs">{_esc(sub)}</span></div>')


def _fact_tiles(p: dict[str, Any]) -> str:
    g, gh, sec, enf, forge = p["git"], p["github"], p["secrets"], p["enforcement"], p["forge"]
    facts: list[str] = []
    if sec.get("findings"):
        facts.append(_fact("f-bad", str(int(sec["findings"])), "possible secret(s)",
                           f"in {sec.get('scope', '?')} — check now"))
    elif sec.get("clean"):
        facts.append(_fact("f-ok", "clean", "secrets",
                           f"scanned: {sec.get('scope', '?')}"))
    else:
        facts.append(_fact("f-dim", "—", "secrets", f"scan: {sec.get('status', '?')}"))
    armed = sum(bool(enf[k]) for k in enf)
    missing = [_GATE_LABELS.get(k, k) for k in _GATE_LABELS if not enf.get(k)]
    cls = "f-ok" if armed >= 5 else ("f-warn" if armed >= 3 else "f-bad")
    facts.append(_fact(cls, f"{armed}/{len(enf)}", "protections on",
                       "all gates armed" if not missing
                       else "missing: " + ", ".join(missing[:2])
                       + (" +" + str(len(missing) - 2) if len(missing) > 2 else "")))
    if gh.get("connected"):
        ci = str(gh.get("latest_ci", "unknown"))
        cic = {"ok": "f-ok", "bad": "f-bad", "dim": "f-dim"}[_ci_class(ci)]
        facts.append(_fact(cic, ci, "CI", "bound to the current commit"))
    else:
        facts.append(_fact("f-dim", "—", "CI", "GitHub not connected"))
    unc = int(g["uncommitted_files"])
    facts.append(_fact("f-warn" if unc else "f-ok", str(unc), "uncommitted",
                       f"{unc} file(s) not committed yet" if unc else "all work committed"))
    runs = int(forge["governed_runs"])
    facts.append(_fact("f-ok" if runs else "f-dim", str(runs), "governed runs",
                       "real Forge-run history" if runs else "none yet — real count"))
    return f'<div class="facts">{"".join(facts)}</div>'


def _hero(p: dict[str, Any], i: int) -> str:
    verdict = _verdict(p)
    fixes = _fixes(p)
    word = _VWORD[verdict]
    n = len(fixes)
    if n:
        chip = (f'<span class="hchip att"><span class="hdot" aria-hidden="true"></span>'
                f'{int(n)} thing{"s" if n != 1 else ""} need{"" if n != 1 else "s"} you</span>')
    else:
        chip = '<span class="hchip okc">&#10003; nothing needs you</span>'
    subs = {
        "healthy": "Push-time and commit-time protections are armed on this project.",
        "under-protected": "Key protections are off — this project is easier to hurt than it should be.",
        "needs-attention": "The secret scan flagged committed content. Deal with this before anything else.",
    }
    glyph, name, lvcls, why = _level_meta(p.get("certificate"))
    cert_html = (
        f'<div class="cert {lvcls}"><span class="certmark" aria-hidden="true">{_esc(glyph)}</span>'
        f'<span><span class="certname">{_esc(name)}</span>'
        f'<div class="certwhy">{_esc(why)}</div></span></div>'
    )
    if fixes:
        top = fixes[0]
        more = ""
        if n > 1:
            more = (f'<button type="button" class="linklike js-only" data-goto="cfg">'
                    f"{n - 1} more fix{'es' if n - 1 != 1 else ''} in Configure &rarr;</button>")
        sev = {"block": "sev-block", "review": "sev-review", "tool": "sev-tool"}[top["sev"]]
        fix_html = (
            f'<div class="hfix {sev}"><div class="hfixhead">'
            f'<span class="hfixlab">do this first</span>'
            f'<span class="hfixtitle">{_esc(top["title"])}</span></div>'
            f'<p class="hfixwhy">{_esc(top["why"])}</p>'
            f"{_cmdblock(top['cmd'])}{more}</div>"
        )
    else:
        fix_html = ('<div class="hfix sev-ok"><div class="hfixhead">'
                    '<span class="hfixlab">nothing to do</span>'
                    '<span class="hfixtitle">Nothing needs you right now.</span></div>'
                    '<p class="hfixwhy">Every setting this page inspects is at the '
                    "recommended state.</p></div>")
    runs = p.get("runs") or []
    runs_link = ""
    if runs:
        nr = len(runs)
        runs_link = (f'<button type="button" class="linklike js-only" data-goto="adv">'
                     f'{nr} recorded run trace{"s" if nr != 1 else ""} &mdash; '
                     "pipeline links in Advanced &rarr;</button>")
    return (
        f'<section class="hero card {_VCLASS[verdict]} scoped" data-p="{int(i)}">'
        f'<div class="herotop">'
        f'<span class="dico" aria-hidden="true">{_ICONS[verdict]}</span>'
        f'<div class="hmain">'
        f'<div class="hname">{_esc(p["project"])} '
        f'<span class="hpath">{_esc(p["path"])}</span></div>'
        f'<h3 class="hverdict"><span class="vword">{_esc(word)}</span></h3>'
        f'<p class="hsub">{_esc(subs[verdict])}</p>'
        f'<div class="hchips">{chip}</div></div>'
        f"{cert_html}</div>"
        f"{_fact_tiles(p)}{fix_html}{runs_link}</section>"
    )


def _fleet_strip(projects: list[dict[str, Any]]) -> str:
    counts = {v: 0 for v in _ORDER}
    rows: list[str] = []
    for p in projects:
        v = _verdict(p)
        counts[v] += 1
        fixes = _fixes(p)
        glyph, _name, lvcls, _why = _level_meta(p.get("certificate"))
        top = _esc(fixes[0]["title"]) if fixes else '<span class="ok">nothing needs you</span>'
        rows.append(
            f'<div class="fleetrow {_VCLASS[v]}"><span class="fn2">{_esc(p["project"])}</span>'
            f'<span class="vpill">{_esc(_VWORD[v])}</span>'
            f'<span class="lvchip {lvcls}">{_esc(glyph)}</span>'
            f'<span class="ftop">{top}</span></div>'
        )
    summary = (f"fleet &middot; {int(counts['healthy'])} protected &middot; "
               f"{int(counts['under-protected'])} under-protected &middot; "
               f"{int(counts['needs-attention'])} need attention")
    return (f'<section class="fleetstrip card scoped" data-p="fleet" '
            f'aria-label="fleet overview">'
            f'<div class="fleetcounts">{summary}</div>{"".join(rows)}</section>')


# ---------------------------------------------------------------------------
# Tab 2 — Advanced (every real signal, expandable cards)
# ---------------------------------------------------------------------------
def _sigcard(pid: int, key: str, title: str, summary: str, body: str) -> str:
    hid, did = f"h-{int(pid)}-{key}", f"d-{int(pid)}-{key}"
    return (
        f'<div class="sig"><button type="button" class="shead" id="{hid}" '
        f'aria-expanded="true" aria-controls="{did}">'
        f'<span class="stitle">{_esc(title)}</span>'
        f'<span class="ssum">{summary}</span>'
        f'<span class="car" aria-hidden="true">&#9656;</span></button>'
        f'<div class="sbody" id="{did}" role="region" aria-labelledby="{hid}">{body}</div></div>'
    )


def _card_git(p: dict[str, Any], i: int) -> str:
    g = p["git"]
    unc = int(g["uncommitted_files"])
    unc_html = (f'<span class="warn">{unc} file(s)</span>' if unc
                else '<span class="ok">clean tree</span>')
    remote = (f'<span class="dim">{_esc(g["remote"])}</span>'
              if g.get("has_remote") and g.get("remote")
              else '<span class="warn">no remote</span>')
    body = (
        _kv("branch", _esc(g["branch"]), mono=True)
        + _kv("last commit", _esc(g["last_commit_ago"]), mono=True)
        + _kv("uncommitted", unc_html, mono=True)
        + _kv("remote", remote, mono=True)
        + _kv("collected", _esc(p.get("collected_at", "")), mono=True)
    )
    if g.get("last_commit"):
        body += f'<div class="commitmsg">{_esc(g["last_commit"])}</div>'
    summary = (f"<span><b>{_esc(g['branch'])}</b> &middot; {_esc(g['last_commit_ago'])}</span>"
               + ("<span class='warn'>%d uncommitted</span>" % unc if unc
                  else "<span class='ok'>clean tree</span>"))
    return _sigcard(i, "git", "git", summary, body)


def _card_github(p: dict[str, Any], i: int) -> str:
    gh = p["github"]
    if not gh.get("connected"):
        body = (_kv("connected", '<span class="dim">no</span>')
                + _kv("reason", f'<span class="dim">{_esc(gh.get("reason", "?"))}</span>'))
        return _sigcard(i, "github", "github", '<span class="dim">not connected</span>', body)
    ci = str(gh.get("latest_ci", "unknown"))
    prs = int(gh.get("open_prs", 0))
    body = (
        _kv("connected", '<span class="ok">yes</span>')
        + _kv("open PRs", f"{prs}", mono=True)
        + _kv("CI (bound to HEAD)", f'<span class="{_ci_class(ci)}">{_esc(ci)}</span>', mono=True)
        + _kv("bound commit", _esc(gh.get("ci_commit", "?")), mono=True)
    )
    titles = [t for t in gh.get("pr_titles", []) if t]
    if titles:
        body += '<div class="note">open: ' + " &middot; ".join(_esc(t) for t in titles) + "</div>"
    summary = (f'<span>CI <span class="{_ci_class(ci)}">{_esc(ci)}</span> '
               f'@ {_esc(gh.get("ci_commit", "?"))}</span><span>{prs} open PR(s)</span>')
    return _sigcard(i, "github", "github", summary, body)


def _card_secrets(p: dict[str, Any], i: int) -> str:
    sec = p["secrets"]
    if "findings" not in sec:
        body = (_kv("tool", _esc(sec.get("tool", "gitleaks")), mono=True)
                + _kv("status", f'<span class="dim">{_esc(sec.get("status", "?"))}</span>'))
        return _sigcard(i, "secrets", "secrets",
                        f'<span class="dim">{_esc(sec.get("status", "?"))}</span>', body)
    findings = int(sec["findings"])
    f_html = (f'<span class="bad">{findings}</span>' if findings
              else '<span class="ok">0 — clean</span>')
    body = (
        _kv("tool", _esc(sec.get("tool", "gitleaks")) + " (--redact)", mono=True)
        + _kv("scope", _esc(sec.get("scope", "?")), mono=True)
        + _kv("findings", f_html, mono=True)
        + _kv("noise excluded", f"{int(sec.get('noise_excluded', 0))}", mono=True)
        + _kv("allowlist", _yn(bool(sec.get("allowlist"))), mono=True)
        + _kv("pre-push gate", _yn(bool(sec.get("pre_push_gate"))), mono=True)
    )
    if sec.get("note"):
        body += f'<div class="note">{_esc(sec["note"])}</div>'
    if findings:
        summary = (f'<span class="bad">{findings} finding(s)</span>'
                   f"<span>{_esc(sec.get('scope', '?'))}</span>")
    else:
        gate = ("" if sec.get("pre_push_gate")
                else ' <span class="warn">no pre-push gate</span>')
        summary = (f'<span class="ok">clean</span><span>{_esc(sec.get("scope", "?"))}</span>'
                   + gate)
    return _sigcard(i, "secrets", "secrets", summary, body)


def _card_gates(p: dict[str, Any], i: int) -> str:
    enf = p["enforcement"]
    lines = []
    for key, label in _GATE_LABELS.items():
        on = bool(enf.get(key))
        mark = ('<span class="gmark ok">&#10003; armed</span>' if on
                else '<span class="gmark bad">&#10007; missing</span>')
        lines.append(f'<div class="gline"><span>{_esc(label)}</span>{mark}</div>')
    body = ("".join(lines)
            + '<div class="note">fix commands for anything missing are in the '
              "Configure tab.</div>")
    return _sigcard(i, "gates", "enforcement gates", _gates_meter(enf), body)


def _card_tests_deps(p: dict[str, Any], i: int) -> str:
    tests, deps = p["tests"], p["deps"]
    kv = deps.get("known_vulns")
    if isinstance(kv, int):
        vulns = (f'<span class="bad">{int(kv)} known CVEs</span>' if kv
                 else '<span class="ok">0 known CVEs</span>')
    else:
        vulns = f'<span class="dim">{_esc(kv)}</span>'
    body = (
        _kv("test files", f"{int(tests['test_files'])}", mono=True)
        + _kv("coverage", f'<span class="dim">{_esc(tests.get("coverage", "not measured"))}</span>')
        + _kv("manifest", _esc(deps.get("manifest") or "no python manifest"), mono=True)
        + _kv("vulnerabilities", vulns, mono=True)
    )
    summary = f"<span>{int(tests['test_files'])} test file(s)</span><span>{vulns}</span>"
    return _sigcard(i, "testsdeps", "tests & deps", summary, body)


def _card_forge(p: dict[str, Any], i: int) -> str:
    forge = p["forge"]
    runs = int(forge["governed_runs"])
    body = (
        _kv("installed", '<span class="ok">yes</span>' if forge.get("installed")
            else '<span class="dim">no</span>', mono=True)
        + _kv("governed runs", f"{runs}", mono=True)
    )
    if forge.get("note"):
        body += f'<div class="note">{_esc(forge["note"])}</div>'
    body += (
        '<div class="planned"><b>Not built yet</b> (honest): live workers &middot; '
        "pipeline runs &middot; engine tiering. These light up only once Forge governs "
        f"a real run here — currently {runs} governed run(s).</div>"
    )
    inst = ('<span class="ok">installed</span>' if forge.get("installed")
            else '<span class="dim">not installed</span>')
    summary = f"<span>{inst}</span><span>{runs} governed run(s)</span>"
    return _sigcard(i, "forge", "forge", summary, body)


def _card_certificate(p: dict[str, Any], i: int) -> str:
    cert = p.get("certificate")
    glyph, name, lvcls, why = _level_meta(cert)
    if cert is None:
        body = f'<div class="note">{_esc(why)}</div>'
        return _sigcard(i, "cert", "certificate",
                        '<span class="dim">not computed</span>', body)
    claims = [c for c in cert.get("claims", []) if isinstance(c, dict)]
    passed = sum(1 for c in claims if c.get("passed"))
    rows = []
    for c in claims:
        ok = bool(c.get("passed"))
        mark = ('<span class="ck ok">&#10003;</span>' if ok
                else '<span class="ck bad">&#10007;</span>')
        rows.append(
            f'<div class="claim">{mark}<div class="cbody2">'
            f"<b>{_esc(c.get('name', '?'))}</b> "
            f'<span class="claimev">— {_esc(c.get("evidence", ""))}</span>'
            f'<div class="repro">reproduce: <code>{_esc(c.get("reproduce", ""))}</code></div>'
            f"</div></div>"
        )
    body = (
        _kv("level", f'<span class="lvchip {lvcls}">{_esc(glyph)}</span> {_esc(name)}')
        + _kv("commit", _esc(cert.get("commit", "?")), mono=True)
        + _kv("claims passing", f"{passed}/{len(claims)}", mono=True)
        + _kv("governed runs", f"{int(cert.get('governed_runs', 0))}", mono=True)
        + "".join(rows)
        + f'<div class="note">{_esc(cert.get("honest_note", ""))}</div>'
    )
    summary = (f'<span class="lvchip {lvcls}">{_esc(glyph)}</span>'
               f"<span>{_esc(name)}</span><span>{passed}/{len(claims)} claims pass</span>")
    return _sigcard(i, "cert", "certificate", summary, body)


def _card_runs(p: dict[str, Any], i: int) -> str:
    """Discovered run traces (<project>/.forge/runs/*.jsonl) with links to their
    rendered pipeline pages. NEVER fabricates a run: no traces -> honest empty
    state; "runs" key absent (plain forge_status JSON, discovery never ran) ->
    says so instead of claiming zero."""
    runs = p.get("runs")
    if runs is None:
        body = ('<div class="note">Run discovery was not performed for this render '
                "(plain forge_status JSON carries no runs list). Generate the "
                "dashboard with status/forge_dashboard.py to list real recorded "
                "traces.</div>")
        return _sigcard(i, "runs", "runs",
                        '<span class="dim">not discovered</span>', body)
    if not runs:
        body = ('<div class="norun">No governed runs yet &mdash; start one with '
                "<code>/forge</code>. The pipeline view lights up here once a run "
                "records a trace.</div>")
        return _sigcard(i, "runs", "runs",
                        '<span class="dim">none yet — real count</span>', body)
    rows: list[str] = []
    linked = 0
    for r in runs:
        outcome = str(r.get("outcome") or "")
        if outcome == "escalated":
            ocls, otext = "ro-esc", outcome
        elif outcome:
            ocls, otext = "ro-ok", outcome
        else:
            ocls, otext = "ro-dim", "no run_end"
        href = str(r.get("href") or "")
        if href:
            linked += 1
            link = f'<a class="runlink" href="{_esc(href)}">view pipeline &rarr;</a>'
        else:
            link = ('<span class="runlink dim">pipeline page not emitted '
                    "(single-file output)</span>")
        meta = " &middot; ".join(
            _esc(b) for b in (str(r.get("started") or ""),
                              f"{int(r.get('events', 0))} events") if b)
        rows.append(
            '<div class="runrow">'
            f'<span class="runout {ocls}">{_esc(otext)}</span>'
            f'<span class="runtask">{_esc(r.get("task") or "(untitled run)")}</span>'
            f'<span class="runid">{_esc(r.get("run_id") or "?")}</span>'
            f'<span class="runmeta">{meta}</span>'
            f"{link}</div>"
        )
    note = ('<div class="note">Each row is a real trace file at '
            "&lt;project&gt;/.forge/runs/*.jsonl, replayed event-by-event on its "
            "pipeline page — nothing listed here is fabricated.</div>")
    summary = (f"<span>{len(runs)} recorded trace(s)</span>"
               + (f"<span>{linked} pipeline page(s) linked</span>" if linked else ""))
    return _sigcard(i, "runs", "runs", summary, "".join(rows) + note)


def _advanced_block(p: dict[str, Any], i: int) -> str:
    verdict = _verdict(p)
    glyph, _name, lvcls, _why = _level_meta(p.get("certificate"))
    cards = (
        _card_git(p, i) + _card_github(p, i) + _card_secrets(p, i) + _card_gates(p, i)
        + _card_tests_deps(p, i) + _card_runs(p, i) + _card_forge(p, i)
        + _card_certificate(p, i)
    )
    return (
        f'<div class="pblock scoped {_VCLASS[verdict]}" data-p="{int(i)}" '
        f'data-verdict="{_esc(verdict)}">'
        f'<div class="pbhead"><span class="pbname">{_esc(p["project"])}</span>'
        f'<span class="vpill">{_esc(_VWORD[verdict])}</span>'
        f'<span class="lvchip {lvcls}">{_esc(glyph)}</span>'
        f'<span class="pbpath">{_esc(p["path"])}</span></div>{cards}</div>'
    )


def _chip(flt: str, label: str, count: int, dot: str) -> str:
    return (f'<button type="button" class="fchip" data-filter="{_esc(flt)}" aria-pressed="false">'
            f'<span class="d" style="background:{dot}" aria-hidden="true"></span>'
            f'{_esc(label)} <span class="n">{int(count)}</span></button>')


# ---------------------------------------------------------------------------
# Tab 3 — Configure (inspect + instruct; never pretends to save)
# ---------------------------------------------------------------------------
def _audit_block(p: dict[str, Any], i: int) -> str:
    """Compliance evidence for one project — the governed-run record auditors ask for.
    Mirrors status/forge_audit.py (same traces, same definitions) so the UI and the
    CLI export can never tell different stories."""
    runs = p.get("audit_runs") or []
    proj = _esc(p["project"])
    if not runs:
        return (
            f'<div class="cfgcard card" data-proj="{int(i)}">'
            f'<div class="cfgh">{proj} — governance evidence</div>'
            '<div class="note">No governed runs recorded yet. Evidence appears once a run '
            "is traced (<code>/forge &lt;task&gt;</code>, or forge_trace start … end). "
            "Nothing is inferred — an empty record stays empty.</div></div>"
        )
    total = len(runs)
    approved = sum(1 for r in runs if r.get("human_approved"))
    verified = sum(1 for r in runs if r.get("verified"))
    forced = sum(1 for r in runs if r.get("forced_close"))
    rows = []
    for r in runs[:12]:
        vmark = "verified" if r.get("verified") else ("FORCED" if r.get("forced_close") else "—")
        rows.append(
            '<div class="gate">'
            f'<span class="ic" aria-hidden="true"></span>{_esc(str(r.get("task", ""))[:44])}'
            f'<span class="st">{_esc(str(r.get("triage", "?")))} · '
            f'{"approved" if r.get("human_approved") else "no-approval"} · {vmark}</span></div>'
        )
    return (
        f'<div class="cfgcard card" data-proj="{int(i)}">'
        f'<div class="cfgh">{proj} — governance evidence ({total} run'
        f'{"s" if total != 1 else ""})</div>'
        f'<div class="posture"><span class="pk">human-approved</span>'
        f'<span class="vpill">{approved}/{total}</span></div>'
        f'<div class="posture"><span class="pk">verified closes</span>'
        f'<span class="vpill">{verified}/{total}</span></div>'
        f'<div class="posture"><span class="pk">forced (unverified) closes</span>'
        f'<span class="vpill">{forced}</span></div>'
        + "".join(rows)
        + '<div class="note">Each row traces to .forge/runs/&lt;run&gt;.jsonl. Export the '
          "full report for an auditor with "
          "<code>python3 status/forge_audit.py . --out audit.md</code> (add --json for a "
          "machine-readable manifest). Traces are self-reported by each run: this evidences "
          "governed discipline, not a tamper-proof ledger — enforcement integrity is attested "
          "separately by forge_doctor.</div></div>"
    )


def _configure_block(p: dict[str, Any], i: int) -> str:
    enf = p["enforcement"]
    verdict = _verdict(p)
    fixes = _fixes(p)
    glines = []
    for key, label in _GATE_LABELS.items():
        on = bool(enf.get(key))
        st = "ARMED" if on else "OFF"
        glines.append(f'<div class="gate{"" if on else " off"}">'
                      f'<span class="ic" aria-hidden="true"></span>{_esc(label)}'
                      f'<span class="st">{_esc(st)}</span></div>')
    current = (
        f'<div class="cfgcard card {_VCLASS[verdict]}">'
        '<div class="cfgh">current config (read from the repo)</div>'
        '<div class="posture"><span class="pk">protection posture</span>'
        f'<span class="vpill">{_esc(_VWORD[verdict])}</span></div>'
        + "".join(glines)
        + '<div class="note">Bash deny rules: the built-in list ships with the Forge '
          "plugin (hooks/guard.py) and applies to every governed session; a project "
          "can extend it via .forge/deny-extra.txt. Test the built-in rules below.</div>"
        + "</div>"
    )
    if fixes:
        items = []
        for f in fixes:
            sev = {"block": "sev-block", "review": "sev-review", "tool": "sev-tool"}[f["sev"]]
            items.append(
                f'<div class="fix {sev}"><div class="fixtitle">'
                f'<span class="sevdot" aria-hidden="true"></span>{_esc(f["title"])}</div>'
                f'<div class="fixwhy">{_esc(f["why"])}</div>{_cmdblock(f["cmd"])}</div>'
            )
        changes = (f'<div class="cfgcard card"><div class="cfgh">to change it — run these '
                   f"({len(fixes)})</div>" + "".join(items)
                   + '<div class="note">Run shell commands from the project root. '
                     "$CLAUDE_PLUGIN_ROOT is the Forge plugin checkout (set "
                     "automatically inside Claude Code hooks; substitute the plugin "
                     "path when running by hand). /forge-init is a Claude Code "
                     "command.</div></div>")
    else:
        changes = ('<div class="cfgcard card"><div class="cfgh">to change it</div>'
                   '<div class="allgood">Nothing to change — every setting this page '
                   "inspects is at the recommended state.</div></div>")
    return (
        f'<div class="cfgblock scoped" data-p="{int(i)}">'
        f'<div class="pbhead"><span class="pbname">{_esc(p["project"])}</span>'
        f'<span class="pbpath">{_esc(p["path"])}</span></div>'
        f'<div class="cfggrid">{current}{changes}</div></div>'
    )


_TESTER_EXAMPLES = [
    "rm -rf /",
    "rm -rf ./build",
    "git push --force origin main",
    "git push origin feat",
    "chmod +x deploy.sh",
    "DROP TABLE users;",
]


def _tester() -> str:
    exs = "".join(f'<button type="button" class="gex js-only">{_esc(e)}</button>'
                  for e in _TESTER_EXAMPLES)
    return (
        '<div class="tester card"><div class="cfgh">guard tester '
        '<span class="pill js-only">live</span></div>'
        '<label class="gtlab" for="gcmd">Type a shell command; it is checked '
        "against a client-side port of the built-in deny rules from hooks/guard.py "
        "(rm -rf on / or ~, force-push, mkfs, dd if=, DROP/TRUNCATE TABLE, fork bomb, "
        "chmod -R 777 /). Nothing is executed and nothing leaves this page.</label>"
        '<input type="text" id="gcmd" class="gin" autocomplete="off" spellcheck="false" '
        'placeholder="e.g.  git push --force origin main">'
        '<div id="gout" class="gout" role="status" aria-live="polite"></div>'
        f'<div class="gexs"><span class="fl js-only">try</span>{exs}</div>'
        "<noscript><div class='note'>The live tester needs JavaScript. The same rules "
        "run for real in hooks/guard.py on every governed Bash call.</div></noscript>"
        '<div class="note">Best-effort footgun-catcher, not a security boundary '
        "(obfuscation can evade any denylist — so the real guard also relies on least "
        "privilege and human approval). Project-specific deny-extra.txt patterns are "
        "not evaluated here: a static page cannot read files.</div></div>"
    )


# ---------------------------------------------------------------------------
# Page assembly
# ---------------------------------------------------------------------------
def render(projects: list[dict[str, Any]], collected_at: str) -> str:
    ordered = sorted(projects, key=lambda p: _ORDER[_verdict(p)])
    counts = {v: sum(1 for p in ordered if _verdict(p) == v) for v in _ORDER}

    options = "".join(
        f'<option value="{int(i)}">{_esc(p["project"])}</option>'
        for i, p in enumerate(ordered)
    ) + '<option value="fleet">All projects (fleet)</option>'

    tabs_html = (
        '<div class="tabs" role="tablist" aria-label="dashboard views">'
        '<button type="button" class="tab" role="tab" id="tab-dash" '
        'aria-controls="panel-dash" aria-selected="true">Dashboard</button>'
        '<button type="button" class="tab" role="tab" id="tab-adv" '
        'aria-controls="panel-adv" aria-selected="false" tabindex="-1">Advanced</button>'
        '<button type="button" class="tab" role="tab" id="tab-audit" '
        'aria-controls="panel-audit" aria-selected="false" tabindex="-1">Audit</button>'
        '<button type="button" class="tab" role="tab" id="tab-cfg" '
        'aria-controls="panel-cfg" aria-selected="false" tabindex="-1">Configure</button></div>'
    )

    heroes = "".join(_hero(p, i) for i, p in enumerate(ordered))
    fleet = _fleet_strip(ordered) if ordered else ""
    dash_panel = (
        '<section class="view" id="panel-dash" role="tabpanel" aria-labelledby="tab-dash" '
        f'tabindex="0"><h2 class="viewlabel">Dashboard</h2>{fleet}{heroes}</section>'
    )

    chips = (
        _chip("all", "all", len(ordered), "var(--faint)")
        + _chip("needs-attention", "needs attention", counts["needs-attention"], "var(--block)")
        + _chip("under-protected", "under-protected", counts["under-protected"], "var(--review)")
        + _chip("healthy", "healthy", counts["healthy"], "var(--allow)")
    )
    adv_blocks = "".join(_advanced_block(p, i) for i, p in enumerate(ordered))
    adv_panel = (
        '<section class="view" id="panel-adv" role="tabpanel" aria-labelledby="tab-adv" '
        'tabindex="0"><h2 class="viewlabel">Advanced</h2>'
        f'<div class="filters fleet-only" role="group" aria-label="filter projects by verdict">'
        f"{chips}</div>{adv_blocks}"
        '<div class="emptymsg" id="advEmpty" hidden>no projects match this filter</div></section>'
    )

    audit_blocks = "".join(_audit_block(p, i) for i, p in enumerate(ordered))
    audit_panel = (
        '<section class="view" id="panel-audit" role="tabpanel" aria-labelledby="tab-audit" '
        'tabindex="0"><h2 class="viewlabel">Audit</h2>'
        '<div class="rulenote">Compliance evidence from real governed runs — who approved '
        "what, at which risk tier, and whether it was verified before closing. This is the "
        "lineage auditors ask for (EU AI Act human-oversight/auditability, ISO 42001). "
        "Same source and definitions as <code>status/forge_audit.py</code>.</div>"
        f"{audit_blocks}</section>"
    )

    cfg_blocks = "".join(_configure_block(p, i) for i, p in enumerate(ordered))
    cfg_panel = (
        '<section class="view" id="panel-cfg" role="tabpanel" aria-labelledby="tab-cfg" '
        'tabindex="0"><h2 class="viewlabel">Configure</h2>'
        '<div class="rulenote">Configure inspects your real config and tells you how to '
        "change it; it does not edit files — Forge changes go through the CLI/hooks. "
        "Every command below is copy-pasteable and does exactly one thing.</div>"
        f"{cfg_blocks}{_tester()}</section>"
    )

    body = dash_panel + adv_panel + audit_panel + cfg_panel
    if not ordered:
        body = '<div class="emptymsg">no projects collected</div>'

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>Forge — Real Project Status</title>\n"
        f"<script>{_HEAD_JS}</script>\n"
        f"<style>{_CSS}</style>\n"
        '</head>\n<body><div class="wrap"><div class="maxw">\n'
        '<header><div class="topbar"><span class="wordmark">'
        '<span class="spark" aria-hidden="true"></span> Forge</span>'
        f'<span class="sub">real status &middot; collected {_esc(collected_at)}</span>'
        '<label class="psel"><span class="psel-l">project</span>'
        f'<select id="scope" class="scope" aria-label="project scope">{options}</select>'
        f"</label>{tabs_html}</div>\n"
        "<h1>Your projects, as Forge actually sees them.</h1>\n"
        '<p class="lede">Every number on this page is collected live from the real '
        "repositories, read-only. Nothing is representative, projected, or mocked.</p>\n"
        f"</header>\n<main>{body}</main>\n"
        '<footer class="foot">real data &middot; read-only collection &middot; secrets '
        "scanned with --redact (no secret values read), scope always shown per project "
        '&middot; the certificate states machine-verified claims at one commit, not '
        '"secure" &middot; "not built yet" means exactly that — no faked workers, '
        "pipelines, or activity &middot; this page makes zero external requests.</footer>\n"
        f"</div></div>\n<script>{_JS}</script>\n</body></html>"
    )


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
