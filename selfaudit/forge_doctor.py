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
import sys
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


# A hook blocks only if the guard's non-zero exit reaches the shell UNCHANGED.
# Any operator/wrapper/comment can subvert that (`; exit 0`, `|| true`, `&`,
# `# …`, `sh -c "exit 0" guard.py`). So the blocking guard command must be a BARE
# `python <path>.py` invocation — nothing before or after. `env`-wrapping is fine.
_GUARD_CMD_RE = re.compile(
    r'^(?:/usr/bin/env\s+)?python3?\s+(?:"([^"]+\.py)"|(\S+\.py))\s*$'
)


def _canonical_guard_path(command: str, root: str) -> str | None:
    """Return the resolved guard path IFF `command` is a bare `python <path>.py`
    invocation whose path exists — else None. Rejects every shell trick because
    anything other than the exact shape fails the full-line match."""
    c = command.replace("${CLAUDE_PLUGIN_ROOT}", root).replace("$CLAUDE_PLUGIN_ROOT", root).strip()
    m = _GUARD_CMD_RE.match(c)
    if not m:
        return None
    tok = m.group(1) or m.group(2) or ""
    p = tok if os.path.isabs(tok) else os.path.join(root, tok)
    p = os.path.normpath(p)
    return os.path.abspath(p) if os.path.isfile(p) else None


def _matcher_covers_bash(matcher: Any) -> bool:
    """Does this hook entry's matcher fire on the Bash tool? Empty/`*` = all tools.
    Otherwise treat it as the regex Claude Code matches against the tool name."""
    if not matcher or matcher == "*":
        return True
    if not isinstance(matcher, str):
        return False
    try:
        return re.search(matcher, "Bash") is not None
    except re.error:
        return "Bash" in matcher


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


def _blessed(path: str | None, root: str) -> bool:
    return (
        path is not None
        and path.startswith(os.path.abspath(root) + os.sep)
        and os.path.basename(path) in _BLESSED_HOOK_SCRIPTS
    )


def resolve_wired_guard(root: str) -> tuple[Any | None, str | None, list[Check]]:
    """Find and load the guard actually wired to fire on Bash at the *blocking*
    PreToolUse event. Requires (a) a PreToolUse entry whose matcher covers Bash,
    (b) a canonical `python <path>` command (no shell tricks), (c) that path
    loading a module exposing is_denied. Anything else → FAIL."""
    checks: list[Check] = []
    hooks = _read_hooks(root)
    if hooks is None:
        checks.append(Check("guard-hook-wired", FAIL, "hooks.json missing or invalid"))
        return None, None, checks

    pre = hooks.get("PreToolUse")
    if not (isinstance(pre, list) and pre):
        checks.append(Check("guard-hook-wired", FAIL, "no PreToolUse hook is configured"))
        return None, None, checks

    for entry in pre:
        if not isinstance(entry, dict) or not _matcher_covers_bash(entry.get("matcher")):
            continue
        for hook in entry.get("hooks", []) or []:
            cmd = hook.get("command", "") if isinstance(hook, dict) else ""
            path = _canonical_guard_path(cmd, root)
            if not path:
                continue
            try:
                mod = _load_guard_module(path)
            except Exception:  # noqa: BLE001 — a broken/decoy script is not a valid guard
                continue
            if callable(getattr(mod, "is_denied", None)):
                checks.append(
                    Check("guard-hook-wired", OK, f"guard fires on Bash: {os.path.relpath(path, root)}")
                )
                return mod, path, checks

    checks.append(
        Check(
            "guard-hook-wired",
            FAIL,
            "no PreToolUse entry matching Bash wires a canonical guard exposing "
            "is_denied — possible decoy, shell-wrapped/neutered command, wrong matcher, "
            "or guard on a non-blocking event",
        )
    )
    return None, None, checks


def check_no_foreign_hooks(root: str) -> Check:
    """Every hook command must be a canonical invocation of a blessed Forge script
    under the plugin root. A URL, a piped shell, a shell-wrapped/operator-laden
    command, or an arbitrary binary is flagged — a shell trick is NOT blessed."""
    hooks = _read_hooks(root)
    if hooks is None:
        return Check("no-foreign-hooks", FAIL, "hooks.json missing or invalid")
    pre_foreign = [c for c in _event_commands(hooks, "PreToolUse")
                   if not _blessed(_canonical_guard_path(c, root), root)]
    other_foreign = [c for c in _event_commands(hooks)
                     if not _blessed(_canonical_guard_path(c, root), root) and c not in pre_foreign]
    if pre_foreign:
        # A foreign command on the blocking PreToolUse event can defeat the stateful
        # controls (e.g. delete/rewrite active_run.json) → this is a FAIL, not advisory.
        return Check("no-foreign-hooks", FAIL,
                     f"unblessed command wired to the blocking PreToolUse event: {pre_foreign}")
    if other_foreign:
        return Check("no-foreign-hooks", WARN, f"unreviewed hook command(s) on non-blocking events: {other_foreign}")
    return Check("no-foreign-hooks", OK, "every hook is a canonical blessed Forge script")


def _guard_exit(guard_path: str, command: str, forge_home: str | None = None) -> int:
    """Run the guard file EXACTLY as Claude Code does — as a subprocess, piping the
    tool payload to stdin → main() → decide() — and return its exit code (2 = block).
    This is the crux: the audit must test the EXECUTED dispatch, not the helper
    functions in isolation, or a gutted `decide()` bypasses every control unseen."""
    env = {**os.environ}
    if forge_home is not None:
        env["FORGE_HOME"] = forge_home
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    try:
        p = subprocess.run(
            [sys.executable, guard_path], input=payload, capture_output=True, text=True,
            timeout=15, env=env,
        )
        return p.returncode
    except Exception:  # noqa: BLE001 — a guard that can't even run is not blocking anything
        return -1


def check_guard_denies(guard_path: str) -> Check:
    """Every catastrophic canary, fed through the real entrypoint, must exit 2."""
    leaked = [c for c in CANARIES if _guard_exit(guard_path, c) != 2]
    if leaked:
        return Check("guard-denies-catastrophic", FAIL, f"guard did not block (exit≠2 via decide): {leaked}")
    return Check("guard-denies-catastrophic", OK, f"all {len(CANARIES)} canaries blocked through decide()")


def check_guard_allows_safe(guard_path: str) -> Check:
    """Every ordinary-safe command, through the real entrypoint, must exit 0."""
    blocked = [c for c in SAFE if _guard_exit(guard_path, c) != 0]
    if blocked:
        return Check("guard-allows-safe", FAIL, f"guard blocked safe commands (exit≠0 via decide): {blocked}")
    return Check("guard-allows-safe", OK, f"all {len(SAFE)} safe commands allowed through decide()")


def _temp_run_dir(fn: Any) -> Any:
    tmp = tempfile.mkdtemp(prefix="forge-doctor-")
    try:
        return fn(tmp)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _write_active(tmp: str, **fields: Any) -> None:
    run = {"run_id": "audit", "path": os.path.join(tmp, "runs", "x.jsonl"),
           "started_at": time.time(), "tool_calls": 0, **fields}
    with open(os.path.join(tmp, "active_run.json"), "w") as fh:
        json.dump(run, fh)


def check_ceiling_behaves(guard_path: str) -> Check:
    """Drive the real entrypoint past a small ceiling; the 3rd call must exit 2.
    Catches a neutered tick_and_check AND a gutted decide() (which never calls it)."""
    def run(tmp: str) -> Check:
        _write_active(tmp, ceiling=2)
        codes = [_guard_exit(guard_path, "ls -la", forge_home=tmp) for _ in range(3)]
        if codes == [0, 0, 2]:
            return Check("ceiling-enforced", OK, "ceiling trips past the limit through decide()")
        return Check("ceiling-enforced", FAIL,
                     f"ceiling not enforced through decide() (exit sequence {codes}, expected 0,0,2)")

    return _temp_run_dir(run)


def check_iteration_cap_behaves(guard_path: str) -> Check:
    """Through the real entrypoint: a blocker seen 1× must exit 0, seen 3× (over the
    cap of 2) must exit 2. Catches a neutered iteration_breached AND a gutted decide()."""
    def run(tmp: str) -> Check:
        _write_active(tmp, iteration_cap=2, blockers={"x": 1})
        under = _guard_exit(guard_path, "ls -la", forge_home=tmp)
        _write_active(tmp, iteration_cap=2, blockers={"x": 3})
        over = _guard_exit(guard_path, "ls -la", forge_home=tmp)
        if under == 0 and over == 2:
            return Check("loop-cap-enforced", OK, "loop cap trips past the limit through decide()")
        return Check("loop-cap-enforced", FAIL,
                     f"loop cap not enforced through decide() (under-cap={under}, over-cap={over}, expected 0,2)")

    return _temp_run_dir(run)


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
        proc = subprocess.run(
            ["bash", init_sh, tmp], capture_output=True, text=True, timeout=45,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        settings = os.path.join(tmp, ".claude", "settings.json")
        if not os.path.isfile(settings):
            # Distinguish "init aborted" from "plan-mode broken": surface init stderr.
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["(no output)"]
            return Check("plan-mode-first", FAIL, f"forge-init did not emit settings.json — init failed: {tail[0]}")
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
    _guard, path, wiring_checks = resolve_wired_guard(root)
    checks.extend(wiring_checks)
    if path is not None:
        checks.append(check_guard_denies(path))
        checks.append(check_guard_allows_safe(path))
        checks.append(check_ceiling_behaves(path))
        checks.append(check_iteration_cap_behaves(path))
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
