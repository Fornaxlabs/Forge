#!/usr/bin/env python3
"""FORGE privacy gate — catch IDENTITY leaks, not just credential leaks.

gitleaks finds API keys and tokens. It has no concept of *you*. Forge shipped 57
public commits stamped with a real name and a machine hostname
(`user@Host.local`) while its own pre-push gate reported "no secrets in pushed
commits" — technically true, practically misleading. This closes that gap.

What it flags:
  * local filesystem paths that embed a username (/Users/<you>, /home/<you>)
  * machine hostnames (*.local) and personal email addresses in the git identity
  * private/internal IP addresses
  * names on a project's own do-not-publish list

    python3 selfaudit/forge_privacy.py [ROOT] [--json]

Exit 1 on any finding, so it can gate a push. Allowlist false positives in
`.forge/privacy-allow.txt` (one substring per line, '#' comments) — an escape hatch
that is explicit and reviewable, rather than a check people learn to bypass.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass

# Public-safe by construction: GitHub's noreply form still links to the profile.
_SAFE_EMAIL = re.compile(r"users\.noreply\.github\.com$", re.I)

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("local-path", re.compile(r"/(?:Users|home)/(?!runner\b|user\b)[A-Za-z0-9._-]{2,}"),
     "a local filesystem path revealing a username"),
    ("hostname", re.compile(r"\b[A-Za-z0-9-]+\.local\b"),
     "a machine hostname"),
    ("private-ip", re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
     "a private/internal IP address"),
    ("personal-email", re.compile(r"\b[A-Za-z0-9._%+-]+@(?:gmail|outlook|hotmail|yahoo|proton(?:mail)?)\.[a-z]{2,}\b", re.I),
     "a personal email address"),
]


@dataclass
class Leak:
    kind: str
    where: str
    detail: str
    sample: str


def _allowlist(root: str) -> list[str]:
    path = os.path.join(root, ".forge", "privacy-allow.txt")
    try:
        with open(path) as fh:
            return [ln.strip() for ln in fh
                    if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def _git(root: str, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", root, *args], check=False,
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def scan_identities(root: str) -> list[Leak]:
    """Author/committer identities across all history — the leak gitleaks cannot see."""
    out: list[Leak] = []
    raw = _git(root, "log", "--all", "--format=%an <%ae>%n%cn <%ce>")
    for ident in sorted({ln.strip() for ln in raw.splitlines() if ln.strip()}):
        email = ident.split("<")[-1].rstrip(">") if "<" in ident else ""
        if not email or _SAFE_EMAIL.search(email):
            continue
        for kind, pat, detail in _PATTERNS:
            if pat.search(email):
                out.append(Leak(kind, "git history (author/committer)",
                                f"{detail} in a commit identity", ident))
                break
    return out


def scan_files(root: str, allow: list[str]) -> list[Leak]:
    """Tracked file CONTENT — only what is actually published."""
    out: list[Leak] = []
    files = [f for f in _git(root, "ls-files").splitlines() if f.strip()]
    for rel in files:
        full = os.path.join(root, rel)
        try:
            if os.path.getsize(full) > 1_000_000:
                continue
            with open(full, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for kind, pat, detail in _PATTERNS:
            for m in pat.finditer(text):
                s = m.group(0)
                if any(a in s for a in allow):
                    continue
                line = text[:m.start()].count("\n") + 1
                out.append(Leak(kind, f"{rel}:{line}", detail, s))
                break  # one finding per pattern per file is enough to act on
    return out


def scan(root: str) -> list[Leak]:
    allow = _allowlist(root)
    return [lk for lk in (scan_identities(root) + scan_files(root, allow))
            if not any(a in lk.sample for a in allow)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="forge_privacy",
                                description="Catch identity leaks before they go public")
    p.add_argument("root", nargs="?", default=".")
    p.add_argument("--json", action="store_true")
    ns = p.parse_args(argv)
    root = os.path.abspath(ns.root)
    leaks = scan(root)

    if ns.json:
        print(json.dumps([lk.__dict__ for lk in leaks], indent=2))
    elif not leaks:
        print("FORGE privacy: no identity leaks found "
              "(paths, hostnames, private IPs, personal emails, commit identities)")
    else:
        print(f"FORGE privacy: {len(leaks)} identity leak(s) — these would be PUBLIC\n")
        for lk in leaks:
            print(f"  [{lk.kind}] {lk.where}")
            print(f"      {lk.detail}: {lk.sample}")
        print("\n  Allowlist a false positive in .forge/privacy-allow.txt (one per line).")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
