#!/usr/bin/env python3
"""FORGE self-audit — verify Forge's own enforcement layer is intact.

A governance tool is only as trustworthy as its enforcement layer. That layer can
be silently weakened: the deny-list trimmed, the guard hook unregistered, a secret
gate neutered, a hostile hook slipped in. Nobody notices until it fails in
production. `forge_doctor` is the check that Forge governs itself.

Design choice — BEHAVIOR over hashes. A file-hash baseline breaks on every honest
edit and teaches people to ignore it. Instead the guard is audited by USE: we
import the live guard and fire a battery of known-catastrophic commands at it. If
any gets through, the deny-list is gutted however it was gutted. A reverse battery
of ordinary-safe commands catches the opposite failure — an over-broad deny that
would wedge normal work. Structural checks confirm the wiring (hook registered,
secret gates present, plan-mode-first, no unreviewed foreign hook).

Exit 0 iff no FAIL. FAIL = tamper/regression (CI and pre-push should gate on it).
WARN = advisory (something to look at, does not fail the run). Unlike the runtime
guard, this tool fails CLOSED: an internal error is itself a FAIL, because a
self-audit that silently passes is worse than none.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # OK | WARN | FAIL
    detail: str


# Commands the guard MUST deny. Each is unambiguously catastrophic; if the guard
# lets any through, its deny-list has been weakened. Keep these representative of
# every deny branch (static patterns + structural rm/push/chmod checks).
CANARIES: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf ~",
    "rm --recursive --force /",
    "mkfs.ext4 /dev/sda",
    "dd if=/dev/zero of=/dev/sda",
    "git push --force origin main",
    "git push -f origin main",
    ":(){ :|:& };:",
    "drop table users",
    "chmod -R 777 /",
)

# Commands the guard MUST allow. A deny-list that also blocks these is broken in
# the other direction (over-broad) and would wedge ordinary work — itself a defect.
SAFE: tuple[str, ...] = (
    "rm -rf ./build",
    "rm -rf node_modules",
    "git push origin feature-branch",
    "git rm stale.txt && git commit -m cleanup",
    "grep -rf patterns.txt src/",
    "ls -la /etc",
)


def _plugin_root(root: str | None) -> str:
    """Resolve the Forge plugin root whose enforcement layer we audit.

    Precedence: explicit --root, then $CLAUDE_PLUGIN_ROOT, then the parent of this
    file's directory (selfaudit/.. == the plugin checkout). This lets the tool
    audit the installed plugin OR a working copy without configuration.
    """
    if root:
        return os.path.abspath(root)
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_guard(root: str) -> Any:
    """Import the guard module straight from the plugin's own source file, by path,
    so the audit reflects the guard THIS install actually runs — not whatever
    happens to be importable on sys.path."""
    guard_path = os.path.join(root, "hooks", "guard.py")
    if not os.path.isfile(guard_path):
        raise FileNotFoundError(guard_path)
    spec = importlib.util.spec_from_file_location("forge_guard_under_audit", guard_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load guard from {guard_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_guard_denies(guard: Any) -> Check:
    """Every canary must be denied. A single leak means the deny-list is gutted."""
    leaked = [c for c in CANARIES if not guard.is_denied(c)]
    if leaked:
        return Check(
            "guard-denies-catastrophic",
            FAIL,
            f"deny-list weakened — these got through: {leaked}",
        )
    return Check(
        "guard-denies-catastrophic", OK, f"all {len(CANARIES)} catastrophic canaries blocked"
    )


def check_guard_allows_safe(guard: Any) -> Check:
    """Ordinary-safe commands must pass. Over-broad denial is its own regression."""
    blocked = [c for c in SAFE if guard.is_denied(c)]
    if blocked:
        return Check(
            "guard-allows-safe",
            FAIL,
            f"deny-list over-broad — these ordinary commands are blocked: {blocked}",
        )
    return Check("guard-allows-safe", OK, f"all {len(SAFE)} safe commands allowed")


def check_ceiling_intact(guard: Any) -> Check:
    """The tool-call ceiling is the loop-brake. Confirm it exists and is sane."""
    ceiling = getattr(guard, "DEFAULT_CEILING", None)
    if not isinstance(ceiling, int) or ceiling <= 0:
        return Check("ceiling-intact", FAIL, f"DEFAULT_CEILING missing or invalid: {ceiling!r}")
    if not callable(getattr(guard, "tick_and_check", None)):
        return Check("ceiling-intact", FAIL, "tick_and_check() missing — loop-brake removed")
    return Check("ceiling-intact", OK, f"loop-brake present (ceiling={ceiling})")


# Hook commands that are known/blessed parts of the Forge enforcement layer. Any
# other command wired into a lifecycle hook is flagged for human review — that is
# exactly how a hostile hook would be smuggled in.
_KNOWN_HOOK_TOKENS = ("guard.py",)


def check_guard_hook_wired(root: str) -> list[Check]:
    """hooks.json must register the guard on PreToolUse, and no hook may invoke a
    command outside the blessed set (a foreign hook = potential tamper)."""
    path = os.path.join(root, "hooks", "hooks.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
    except OSError:
        return [Check("guard-hook-wired", FAIL, f"hooks.json missing at {path}")]
    except ValueError as exc:
        return [Check("guard-hook-wired", FAIL, f"hooks.json is not valid JSON: {exc}")]

    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return [Check("guard-hook-wired", FAIL, "hooks.json has no 'hooks' object")]

    # Collect every command string across every lifecycle event.
    commands: list[str] = []
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for hook in (entry or {}).get("hooks", []) if isinstance(entry, dict) else []:
                cmd = hook.get("command", "") if isinstance(hook, dict) else ""
                if cmd:
                    commands.append(cmd)

    results: list[Check] = []
    pre = hooks.get("PreToolUse")
    guarded = any("guard.py" in c for c in commands)
    if not (isinstance(pre, list) and pre and guarded):
        results.append(
            Check("guard-hook-wired", FAIL, "guard.py is not registered on PreToolUse")
        )
    else:
        results.append(Check("guard-hook-wired", OK, "guard.py registered on PreToolUse"))

    foreign = [c for c in commands if not any(tok in c for tok in _KNOWN_HOOK_TOKENS)]
    if foreign:
        results.append(
            Check(
                "no-foreign-hooks",
                WARN,
                f"unreviewed hook command(s) present — confirm intentional: {foreign}",
            )
        )
    else:
        results.append(Check("no-foreign-hooks", OK, "no foreign hook commands"))
    return results


def _file_contains(path: str, needle: str) -> bool:
    try:
        with open(path) as fh:
            return needle in fh.read()
    except OSError:
        return False


def check_secret_gates(root: str) -> list[Check]:
    """The secret gates are the highest-consequence control. Confirm each is
    present and still references gitleaks (a neutered gate is worse than none)."""
    checks: list[Check] = []
    gates = [
        ("pre-push-secret-gate", os.path.join(root, "templates", "pre-push"), "gitleaks"),
        (
            "pre-commit-secret-gate",
            os.path.join(root, "templates", "pre-commit-config.yaml"),
            "gitleaks",
        ),
    ]
    for name, path, needle in gates:
        if not os.path.isfile(path):
            checks.append(Check(name, FAIL, f"missing: {path}"))
        elif not _file_contains(path, needle):
            checks.append(Check(name, FAIL, f"present but no '{needle}' reference — neutered?"))
        else:
            checks.append(Check(name, OK, f"present and references {needle}"))

    toml = os.path.join(root, "templates", ".gitleaks.toml")
    checks.append(
        Check("gitleaks-config", OK, "present")
        if os.path.isfile(toml)
        else Check("gitleaks-config", WARN, f"missing: {toml} (gitleaks uses defaults)")
    )
    return checks


def check_plan_mode_first(root: str) -> Check:
    """forge-init must still stamp plan-mode-first (read-only until a plan is
    approved). If that logic is gone, new projects lose the plan gate silently."""
    init_sh = os.path.join(root, "scripts", "forge-init.sh")
    if not os.path.isfile(init_sh):
        return Check("plan-mode-first", FAIL, f"forge-init.sh missing: {init_sh}")
    try:
        with open(init_sh) as fh:
            body = fh.read()
    except OSError as exc:
        return Check("plan-mode-first", FAIL, f"cannot read forge-init.sh: {exc}")
    if 'defaultMode' in body and '"plan"' in body:
        return Check("plan-mode-first", OK, "forge-init stamps defaultMode=plan")
    return Check("plan-mode-first", FAIL, "forge-init no longer sets plan-mode-first")


def run_audit(root: str) -> list[Check]:
    """Run every self-audit check against the enforcement layer at `root`.

    Fails CLOSED: if the guard cannot even be loaded, that is a FAIL, not a skip —
    a self-audit that can't inspect the guard must not report health.
    """
    checks: list[Check] = []
    try:
        guard = _load_guard(root)
    except Exception as exc:  # noqa: BLE001 — any load failure is a FAIL, by contract
        checks.append(Check("guard-loadable", FAIL, f"cannot load guard.py: {exc}"))
        guard = None
    if guard is not None:
        checks.append(Check("guard-loadable", OK, "guard.py imports"))
        checks.append(check_guard_denies(guard))
        checks.append(check_guard_allows_safe(guard))
        checks.append(check_ceiling_intact(guard))
    checks.extend(check_guard_hook_wired(root))
    checks.extend(check_secret_gates(root))
    checks.append(check_plan_mode_first(root))
    return checks


def _worst(checks: Sequence[Check]) -> str:
    if any(c.status == FAIL for c in checks):
        return FAIL
    if any(c.status == WARN for c in checks):
        return WARN
    return OK


_GLYPH = {OK: "✓", WARN: "!", FAIL: "✗"}


def _render(checks: Sequence[Check]) -> str:
    lines = [f"  [{_GLYPH[c.status]}] {c.name}: {c.detail}" for c in checks]
    n_fail = sum(c.status == FAIL for c in checks)
    n_warn = sum(c.status == WARN for c in checks)
    verdict = _worst(checks)
    header = "FORGE self-audit — enforcement layer"
    footer = (
        f"verdict: {verdict}  ({len(checks)} checks, {n_fail} FAIL, {n_warn} WARN)"
    )
    return "\n".join([header, *lines, footer])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge_doctor", description=__doc__)
    parser.add_argument(
        "--root", help="plugin root to audit (default: $CLAUDE_PLUGIN_ROOT or this checkout)"
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    root = _plugin_root(args.root)
    checks = run_audit(root)
    verdict = _worst(checks)

    if args.json:
        print(
            json.dumps(
                {
                    "root": root,
                    "verdict": verdict,
                    "checks": [
                        {"name": c.name, "status": c.status, "detail": c.detail} for c in checks
                    ],
                },
                indent=2,
            )
        )
    else:
        print(_render(checks))

    return 1 if verdict == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
