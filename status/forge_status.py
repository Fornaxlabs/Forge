#!/usr/bin/env python3
"""FORGE status collector — read a real project and emit real status JSON.

This is the data source behind the dashboard. It is strictly READ-ONLY: it runs
git/gh/gitleaks/etc. against a project directory, never writes to it, never pushes,
never prints a secret value (gitleaks runs --redact and only counts are kept).

Every probe degrades gracefully: a missing tool, an unauth'd gh, a timeout — each
becomes a status string, never a crash. What Forge has not actually done yet
(governed runs, live workers) is reported as empty/absent, not faked.

Usage:  python3 forge_status.py <project_dir> [--json] [--history]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any


def _run(args: list[str], cwd: str, timeout: float = 20.0) -> tuple[int, str]:
    """Run a command read-only; return (rc, combined_output). Never raises."""
    try:
        p = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # never hang on auth prompt
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "tool-not-installed"
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:  # noqa: BLE001 — a probe must never crash the collector
        return 1, f"error: {exc}"


def _has(tool: str) -> bool:
    from shutil import which
    return which(tool) is not None


def probe_git(d: str) -> dict[str, Any]:
    rc, branch = _run(["git", "branch", "--show-current"], d)
    _, last = _run(["git", "log", "-1", "--format=%s\x1f%cr"], d)
    subject, _, ago = last.strip().partition("\x1f")
    _, status = _run(["git", "status", "--porcelain"], d)
    uncommitted = len([ln for ln in status.splitlines() if ln.strip()]) if status.strip() and "not-installed" not in status else 0
    _, remote = _run(["git", "remote", "get-url", "origin"], d)
    return {
        "branch": branch.strip() or "(detached)",
        "last_commit": subject.strip()[:80],
        "last_commit_ago": ago.strip(),
        "uncommitted_files": uncommitted,
        "has_remote": bool(rc == 0 and remote.strip() and "not-installed" not in remote),
        "remote": remote.strip() if remote.strip() and "not-installed" not in remote else None,
    }


def probe_github(d: str) -> dict[str, Any]:
    if not _has("gh"):
        return {"connected": False, "reason": "gh not installed"}
    rc, prs = _run(["gh", "pr", "list", "--state", "open", "--json", "number,title"], d, timeout=15)
    if rc != 0:
        reason = "not a github repo / not authenticated" if "not-installed" not in prs else "gh error"
        return {"connected": False, "reason": reason}
    try:
        pr_list = json.loads(prs) if prs.strip().startswith("[") else []
    except ValueError:
        pr_list = []
    # Bind CI to the CERTIFIED commit (HEAD), not "the most recent run on any branch"
    # — a green run elsewhere must not vouch for a broken HEAD.
    _, head = _run(["git", "rev-parse", "HEAD"], d)
    head = head.strip()
    rc2, runs = _run(
        ["gh", "run", "list", "--limit", "20", "--json", "headSha,status,conclusion"], d, timeout=15
    )
    ci = "no run for HEAD"
    try:
        for r in (json.loads(runs) if runs.strip().startswith("[") else []):
            if r.get("headSha") == head:
                ci = r.get("conclusion") or r.get("status") or "unknown"
                break
    except ValueError:
        ci = "unknown"
    return {
        "connected": True,
        "open_prs": len(pr_list),
        "pr_titles": [p.get("title", "")[:60] for p in pr_list[:3]],
        "latest_ci": ci,
        "ci_commit": head[:12],
    }


# Vendored / data / binary paths that produce gitleaks false positives (entropy in
# fixtures, media, minified bundles). Mirrors scripts/forge-comply.sh's ignore set.
# A "finding" inside these is noise, not a leaked key — so we report it separately.
_NOISE_RE = re.compile(
    r"(^|/)(node_modules|vendor|dist|build|target|\.venv|venv|__pycache__|"
    r"data|datasets|fixtures|samples|coverage|\.mypy_cache|\.pytest_cache)/|"
    r"\.(min\.(js|css)|jpe?g|png|gif|webp|ico|svg|pdf|zip|gz|tar|mp4|mkv|mp3|"
    r"bin|so|dylib|rlib|rmeta|lock|map)$",
    re.I,
)


def _gitleaks_scan(base_args: list[str], cwd: str, timeout: float) -> Any:
    """Run gitleaks with a JSON report and split real findings from vendored/data
    noise. --redact means no secret VALUE is ever read; we keep only file paths and
    counts. gitleaks auto-applies the project's .gitleaks.toml allowlist if present."""
    fd, rep = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        args = base_args + ["--redact", "--no-banner", "--report-format", "json", "--report-path", rep]
        rc, _ = _run(args, cwd, timeout=timeout)
        if rc == 127:
            return None  # not installed
        if rc == 124:
            return "timeout"
        try:
            with open(rep) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = []
        if not isinstance(data, list):
            data = []
        raw = len(data)
        real = sum(1 for f in data if not _NOISE_RE.search((f.get("File", "") or "").replace("\\", "/")))
        return {"real": real, "noise": raw - real}
    finally:
        try:
            os.remove(rep)
        except OSError:
            pass


def probe_secrets(d: str, history: bool) -> dict[str, Any]:
    """Scan COMMITTED content, not the working directory. `gitleaks dir` flags every
    high-entropy string in untracked data/caches/media (thousands of false positives
    in a data-heavy repo); `gitleaks git` only sees tracked commits — the real "did a
    secret get committed" question. This is a quick signal, NOT authoritative: the
    pre-push gate (scanning the commits being pushed) is the real check."""
    if not _has("gitleaks"):
        return {"tool": "gitleaks", "status": "not installed"}
    allowlist = os.path.isfile(os.path.join(d, ".gitleaks.toml"))
    pre_push = os.path.isfile(os.path.join(d, ".git", "hooks", "pre-push"))
    _, cnt = _run(["git", "rev-list", "--count", "HEAD"], d)
    try:
        n_commits = int(cnt.strip())
    except (ValueError, AttributeError):
        n_commits = 0
    if n_commits == 0:
        return {"tool": "gitleaks", "status": "no commits to scan"}

    args = ["gitleaks", "git"]
    if not history and n_commits > 50:
        args.append("--log-opts=HEAD~50..HEAD")
        scope = "last 50 commits"
    else:
        scope = "full history"
    scan = _gitleaks_scan(args, d, timeout=200 if scope == "full history" else 90)
    if scan is None:
        return {"tool": "gitleaks", "status": "not installed"}
    if not isinstance(scan, dict):
        return {"tool": "gitleaks", "status": f"{scan} (scope: {scope})", "scope": scope}
    return {
        "tool": "gitleaks",
        "scope": scope,
        "findings": scan["real"],
        "noise_excluded": scan["noise"],
        "clean": scan["real"] == 0,
        "allowlist": allowlist,
        "pre_push_gate": pre_push,
        "note": "quick scan of committed content; the pre-push gate is the authoritative check",
    }


def probe_enforcement(d: str) -> dict[str, Any]:
    def f(*parts: str) -> bool:
        return os.path.exists(os.path.join(d, *parts))
    settings_plan = False
    sp = os.path.join(d, ".claude", "settings.json")
    if os.path.isfile(sp):
        try:
            with open(sp) as fh:
                settings_plan = (json.load(fh).get("permissions", {}) or {}).get("defaultMode") == "plan"
        except (OSError, ValueError):
            pass
    ci = os.path.isdir(os.path.join(d, ".github", "workflows")) and bool(
        [x for x in os.listdir(os.path.join(d, ".github", "workflows")) if x.endswith((".yml", ".yaml"))]
    ) if os.path.isdir(os.path.join(d, ".github", "workflows")) else False
    return {
        "pre_commit_config": f(".pre-commit-config.yaml"),
        "pre_commit_installed": f(".git", "hooks", "pre-commit"),
        "pre_push_gate": f(".git", "hooks", "pre-push"),
        "ci_workflow": ci,
        "gitleaks_allowlist": f(".gitleaks.toml"),
        "plan_mode_first": settings_plan,
    }


def probe_tests(d: str) -> dict[str, Any]:
    count = 0
    for root, _, files in os.walk(d):
        if any(seg in root for seg in (".git", "node_modules", ".venv", "venv", "__pycache__", "target")):
            continue
        count += sum(1 for fn in files if fn.startswith("test_") and fn.endswith(".py") or fn.endswith("_test.py"))
    return {"test_files": count, "coverage": "not measured (collector does not run your tests)"}


def probe_deps(d: str) -> dict[str, Any]:
    manifest = next((m for m in ("pyproject.toml", "requirements.txt") if os.path.isfile(os.path.join(d, m))), None)
    if not manifest:
        return {"manifest": None, "known_vulns": "no python manifest"}
    if not _has("pip-audit"):
        return {"manifest": manifest, "known_vulns": "pip-audit not installed"}
    args = ["pip-audit", "--progress-spinner", "off"]
    if manifest == "requirements.txt":
        args += ["-r", "requirements.txt"]
    rc, out = _run(args, d, timeout=60)
    if rc == 124:
        return {"manifest": manifest, "known_vulns": "timed out (deps not resolvable offline)"}
    if rc == 127:
        return {"manifest": manifest, "known_vulns": "pip-audit not installed"}
    if "No known vulnerabilities" in out or rc == 0:
        return {"manifest": manifest, "known_vulns": 0}
    import re
    found = len(re.findall(r"^\S+\s+\S+\s+\S+", out, re.M))
    return {"manifest": manifest, "known_vulns": "see pip-audit" if found else "could not resolve"}


def _is_valid_trace(path: str) -> bool:
    """A governed run must contain BOTH a run_start and a run_end event — so an empty
    `touch fake.jsonl` cannot inflate the count (which would forge L3 provenance)."""
    try:
        events = set()
        with open(path) as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                rec = json.loads(ln)
                if isinstance(rec, dict) and isinstance(rec.get("event"), str):
                    events.add(rec["event"])
        return "run_start" in events and "run_end" in events
    except (OSError, ValueError):
        return False


def probe_forge(d: str) -> dict[str, Any]:
    fdir = os.path.join(d, ".forge")
    installed = os.path.isdir(fdir)
    # forge_trace writes to FORGE_HOME/runs (default .forge/runs) — count only VALID
    # traces there, not any .jsonl a hand can drop in.
    runs_dir = os.path.join(fdir, "runs")
    runs = 0
    if os.path.isdir(runs_dir):
        runs = sum(1 for fn in os.listdir(runs_dir)
                   if fn.endswith(".jsonl") and _is_valid_trace(os.path.join(runs_dir, fn)))
    return {
        "installed": installed,
        "governed_runs": runs,
        "note": None if runs else "No valid Forge-governed runs (run_start+run_end) recorded yet — pipeline/provenance empty until you run /forge here.",
    }


def collect(d: str, history: bool = False) -> dict[str, Any]:
    d = os.path.abspath(d)
    return {
        "project": os.path.basename(d),
        "path": d,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": probe_git(d),
        "github": probe_github(d),
        "secrets": probe_secrets(d, history),
        "enforcement": probe_enforcement(d),
        "tests": probe_tests(d),
        "deps": probe_deps(d),
        "forge": probe_forge(d),
    }


def _fmt(s: dict[str, Any]) -> str:
    g, gh, sec, enf, forge = s["git"], s["github"], s["secrets"], s["enforcement"], s["forge"]
    armed = sum(bool(v) for v in enf.values())
    lines = [
        f"■ {s['project']}  ({s['path']})",
        f"  git      · {g['branch']} · {g['last_commit_ago']} · {g['uncommitted_files']} uncommitted · last: {g['last_commit']}",
        "  github   · " + ("connected · %s open PR · CI %s" % (gh.get("open_prs"), gh.get("latest_ci")) if gh.get("connected") else "not connected (%s)" % gh.get("reason")),
        "  secrets  · " + (
            f"clean ✓ ({sec.get('scope')})" if sec.get("clean") else
            (f"{sec.get('findings')} finding(s) in {sec.get('scope')}" if sec.get("findings") is not None else str(sec.get("status", "?")))
        ) + (f" · pre-push gate={'yes' if sec.get('pre_push_gate') else 'MISSING'}" if "pre_push_gate" in sec else "")
        + (f" · allowlist={'yes' if sec.get('allowlist') else 'MISSING'}" if "allowlist" in sec else ""),
        f"  gates    · {armed}/6 armed  (pre-commit-cfg={enf['pre_commit_config']}, installed={enf['pre_commit_installed']}, pre-push={enf['pre_push_gate']}, CI={enf['ci_workflow']}, allowlist={enf['gitleaks_allowlist']}, plan-mode={enf['plan_mode_first']})",
        f"  tests    · {s['tests']['test_files']} test files · coverage {s['tests']['coverage']}",
        f"  deps     · {s['deps'].get('manifest')} · vulns: {s['deps'].get('known_vulns')}",
        f"  forge    · {'installed' if forge['installed'] else 'not installed'} · {forge['governed_runs']} governed runs" + (f"  ⚠ {forge['note']}" if forge.get("note") else ""),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    as_json = "--json" in argv
    history = "--history" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: forge_status.py <project_dir> [more_dirs...] [--json] [--history]", file=sys.stderr)
        return 2
    results = [collect(p, history) for p in paths if os.path.isdir(p)]
    if as_json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    else:
        for r in results:
            print(_fmt(r))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
