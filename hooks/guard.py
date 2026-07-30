#!/usr/bin/env python3
"""FORGE PreToolUse guard.

Four enforced controls that used to be mere prose in CLAUDE.md:
1. Deny destructive Bash commands (rm -rf /, force-push, drop table, ...).
2. Enforce the run tool-call ceiling — counts MUTATING actions (Bash/Edit/Write/
   MultiEdit/NotebookEdit; see hooks.json matcher), not reads, and only while a
   FORGE run is active, so it never blocks unrelated sessions.
3. Enforce the loop cap (same blocker exceeded its iteration limit → block + escalate).
4. Enforce plan scope — the ASSUMPTION GUARD: block a file edit whose target is
   outside the run's declared scope (see scope_violation). Touching an undeclared
   file is an unconfirmed scope assumption; opt-in per run, fails open when no scope
   was declared. This is the deterministic slice of "Forge doesn't allow assumptions";
   intent/requirement assumptions are surfaced by the plan + caught by the reviewer,
   which a hook cannot do.

Exit 2 blocks the tool call. The guard fails OPEN: any internal error returns 0
(allow), so a bug here can never wedge the user's shell. It only ever blocks on a
confirmed match or a confirmed ceiling/loop breach.

HONEST LIMIT 1 — deny is a footgun-catcher, NOT a security boundary: a denylist can
never be complete (base64/eval/encoded args get through). Real protection = least
privilege + human approval for destructive ops + not executing untrusted input.

RUN-WIDE ENFORCEMENT (2026-07-18, empirically verified): the ceiling + loop cap span
the WHOLE fleet — main agent AND subagents. Two verified facts make this work:
(a) a subagent's tool calls DO fire this same PreToolUse hook, carrying agent_id; and
(b) anchoring active_run.json to $CLAUDE_PROJECT_DIR/.forge (see _forge_home) gives the
main agent and every subagent ONE shared counter, regardless of each tool's cwd.
Validated end-to-end: with ceiling=3, a subagent's 4th run-wide call was blocked
(exit 2). The earlier 118-vs-40 miss was NOT subagent bypass — it was the old
cwd-relative counter, so agents running in different dirs didn't share state. Fixed.

REMAINING BOUND — only tool calls that fire this hook are counted: the mutating tools
in hooks.json's matcher (Bash/Edit/Write/MultiEdit/NotebookEdit), not reads. Claude
Code's 200-subagent/session hard cap (CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION) backstops
runaway fan-out.

MULTI-HARNESS (2026-07-18): the decision core (is_denied / ceiling / loop cap) is
harness-neutral. A thin adapter boundary translates at the edges only:
- _extract() normalizes the stdin payload from any known harness (Claude Code, Codex
  CLI, Block Goose, AWS Kiro, Gemini CLI, Kimi Code, grok-build, Cline) into
  {command, tool_name, agent_id};
- _emit_block() speaks the harness's block signal: exit-2 + stderr (the default —
  the Claude Code path is byte-identical to before) or deny-JSON on stdout
  (FORGE_BLOCK_MODE=json or --mode json), for harnesses that consume a
  PreToolUse permissionDecision instead of an exit code.
Install configs per harness live in adapters/; the honest validation matrix is
docs/HARNESSES.md. Everything runs THIS one file — there are no per-harness forks
of the decision logic.
"""
from __future__ import annotations

import fcntl
import fnmatch
import json
import os
import re
import sys
import time
from typing import Any

# Unambiguous catastrophic patterns (checked verbatim).
_STATIC_DENY = [
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bdrop\s+(table|database)\b",
    r"\btruncate\s+table\b",
    r":\s*\(\s*\)\s*\{.*\}\s*;\s*:",   # fork bomb (tolerant of spaces)
    r">\s*/dev/sd[a-z]\d*",
    r"\bfind\s+/\s.*-delete\b",
    # Pipe-to-shell: fetching a remote payload straight into an interpreter is
    # arbitrary unreviewed code execution — the fetched script never touches disk and
    # never passes this hook's own checks, so it can carry any blocked command one
    # layer removed. Requires BOTH a fetch and a pipe into a shell, so ordinary
    # `curl … > file` and `bash install.sh` stay allowed. (Gap found 2026-07-26.)
    r"\b(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|k|da)?sh\b",
    r"\b(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:python3?|perl|ruby|node)\b",
]


def _env_int(name: str, fallback: int) -> int:
    """Read a positive int from the environment; any garbage falls back safely.
    Never raises — a bad env var must not wedge the guard."""
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else fallback
    except (TypeError, ValueError):
        return fallback


# Ceiling calibration (revised again 2026-07-30 — FIELD DATA, not a guess).
# 40 was still wrong and fired on honest work in a real FornaxOS run: a single
# adversarial subagent review consumed 39 calls by itself, so review + remediation
# could not coexist in one run and the guard blocked legitimate fixing. A ceiling that
# punishes doing the review properly is a ceiling users disable — the exact death
# documented below, which this default then walked into.
#
# The ceiling is a RUNAWAY BACKSTOP, not a budget. A runaway loop does hundreds of
# calls; repetition-without-progress is caught earlier and more precisely by the loop
# cap (same blocker 3x). So the number only has to sit above legitimate long work:
# 150 clears a 39-call review plus remediation plus build with headroom, and still
# stops a loop long before it does real damage.
# Original note, which correctly predicted the failure above:
# Current long-horizon engines (Fable 5, Opus 5) sustain autonomous runs for HOURS and
# routinely exceed 40 mutating actions on legitimate work — a ceiling that fires on
# honest work trains users to disable it, which is how a guardrail dies. So the default
# is env-tunable (FORGE_CEILING) and per-run overridable (`TRACE start --ceiling N`);
# see docs/ENGINE-PROFILES.md for per-engine values. It remains a RUNAWAY backstop —
# a number you should not reach — not a budget.
DEFAULT_CEILING = _env_int("FORGE_CEILING", 150)
# Loop discipline: max review iterations on the SAME blocker before a human must
# take over. Enforced here (not just prose): once the reviewer has recorded a
# blocker this many times (via `forge_trace blocker --id`), the next tool call in
# the run is blocked. A run may override via active_run.json ("iteration_cap").
DEFAULT_ITERATION_CAP = 3
# Crash safety: ignore an active run older than this. Raised 6h -> 24h (2026-07-26)
# because long-horizon engines run autonomously for hours and multiday runs are a
# stated use case; at 6h a legitimate long run silently LOST its ceiling and loop cap
# mid-flight — enforcement evaporating exactly when a run is most likely to go wrong.
# Tunable via FORGE_STALE_HOURS for shorter/longer operating windows.
STALE_SECONDS = _env_int("FORGE_STALE_HOURS", 24) * 3600


# Shell separators — split a compound line into individual command invocations so
# tokens from DIFFERENT commands aren't combined into a false positive (e.g.
# `git rm x && git init --bare /r` must not read as an `rm --recursive ... /`).
_SEP = re.compile(r"&&|\|\||[;\n|]")


def _segment_denied(seg: str) -> bool:
    """Multi-condition structural checks, evaluated within ONE command invocation."""
    # rm: recursive AND force AND a bare catastrophic target (/, ~, /*).
    if re.search(r"\brm\b", seg):
        recursive = bool(re.search(r"--recursive|-[a-z]*r", seg))
        force = bool(re.search(r"--force|-[a-z]*f", seg))
        target = bool(re.search(r"(?:^|[\s=])(?:/|~|/\*)(?:\s|$)", seg)) \
            or "--no-preserve-root" in seg
        if recursive and force and target:
            return True
    # git push: any force flag OR a '+refspec' (forced update).
    if re.search(r"\bgit\s+push\b", seg):
        if re.search(r"--force|--force-with-lease|(?:^|\s)-[a-z]*f(?:\s|$)", seg):
            return True
        if re.search(r"\s\+\S", seg):
            return True
    # chmod: recursive 777 on bare root.
    if re.search(r"\bchmod\b", seg) and "777" in seg:
        if re.search(r"--recursive|-[a-z]*r", seg) and re.search(r"(?:^|[\s=])/(?:\s|$)", seg):
            return True
    return False


def is_denied(command: str) -> bool:
    """Best-effort deny of catastrophic commands (see module HONEST LIMIT).
    Multi-condition checks run PER invocation (split on shell separators); the
    single-pattern static + project lists match anywhere on the line."""
    c = command.lower()
    if any(_segment_denied(seg) for seg in _SEP.split(c)):
        return True
    if any(re.search(p, c) for p in _STATIC_DENY):
        return True
    for pat in _extra_patterns():  # project-specific extensions
        try:
            if re.search(pat, c, re.IGNORECASE):
                return True
        except re.error:
            continue  # a malformed project pattern must never wedge the guard
    return False


def _forge_home() -> str:
    """Resolve the .forge dir INDEPENDENTLY of the tool's working directory.

    Empirically (verified 2026-07-18) a subagent's tool calls fire this same hook and
    every hook invocation — main agent and every subagent — receives the same
    CLAUDE_PROJECT_DIR. Anchoring here means all of them read/write the SAME
    active_run.json, so the ceiling + loop cap count RUN-WIDE (the whole fleet), not
    per-cwd. Precedence: explicit FORGE_HOME > $CLAUDE_PROJECT_DIR/.forge > ./.forge.
    (The old cwd-relative default silently no-op'd enforcement whenever a tool ran
    from a directory other than the one the run was started in — the 118-vs-40 bug.)"""
    home = os.environ.get("FORGE_HOME")
    if home:
        return home
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        return os.path.join(proj, ".forge")
    return ".forge"


def _active_run_path() -> str:
    return os.path.join(_forge_home(), "active_run.json")


def _is_orphan_adhoc(run: dict[str, Any]) -> bool:
    """True for an ad-hoc session run living OUTSIDE a project.

    Self-healing for a real field failure: an ad-hoc run armed in $HOME has no task
    boundary, so nothing ever closes it — one counter accumulated across every session
    until it crossed the ceiling and halted them all, permanently. Preventing new ones
    is not enough; anyone already holding a poisoned file stays wedged forever. So the
    guard now simply IGNORES such a run instead of enforcing against it.

    Deliberately narrow: only ad_hoc runs, and only where the parent directory is not a
    git project. A real /forge run is always honoured, wherever it lives."""
    if not run.get("ad_hoc"):
        return False
    parent = os.path.dirname(os.path.abspath(_forge_home()))
    return not os.path.isdir(os.path.join(parent, ".git"))


def _extra_patterns() -> list[str]:
    """Project-specific deny regexes from ${forge-home}/deny-extra.txt (one per line,
    '#' comments allowed). Lets a project extend the deny-list WITHOUT forking the
    shared plugin — e.g. FornaxOS adds nft/ip/rpm-ostree lockout patterns here."""
    path = os.path.join(_forge_home(), "deny-extra.txt")
    try:
        with open(path) as fh:
            return [
                ln.strip() for ln in fh
                if ln.strip() and not ln.lstrip().startswith("#")
            ]
    except OSError:
        return []


def tick_and_check(now: float | None = None) -> bool:
    """Increment the active run's tool-call count. Return True iff the ceiling is
    breached. No active run, stale run, or any error → False (never block).

    The read-modify-write is done under an exclusive flock so parallel tool-call
    hooks can't lose increments (which would let the ceiling be silently exceeded)."""
    path = _active_run_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX)
            except OSError:
                pass  # locking unsupported → best-effort, still correct single-threaded
            try:
                run = json.load(fh)
            except ValueError:
                return False
            started = run.get("started_at", 0)
            now = time.time() if now is None else now
            if not started or (now - started) > STALE_SECONDS:
                return False  # crashed/forgotten run — don't hold the shell hostage
            if _is_orphan_adhoc(run):
                return False  # orphaned session run outside a project — never enforce
            count = int(run.get("tool_calls", 0)) + 1
            run["tool_calls"] = count
            ceiling = int(run.get("ceiling", DEFAULT_CEILING))
            fh.seek(0)
            json.dump(run, fh)
            fh.truncate()
            return count > ceiling
    except OSError:
        return False


# Multi-agent fan-out cap. Current engines (Opus 5, Fable 5) delegate to subagents far
# more readily than earlier models, and vendor guidance recommends deterministic caps
# on how many agents may be launched — delegation multiplies cost and blast radius.
# Forge already counts tool CALLS run-wide; this counts distinct AGENTS. Tunable via
# FORGE_MAX_AGENTS. Claude Code's 200/session limit is a far looser backstop.
DEFAULT_MAX_AGENTS = _env_int("FORGE_MAX_AGENTS", 12)


def record_agent(agent_id: str, now: float | None = None) -> bool:
    """Record this agent in the active run's roster. Return True iff admitting it would
    breach the fan-out cap (i.e. it is a NEW agent and the roster is already full).

    Agents already on the roster are never blocked — the cap limits how WIDE a run may
    fan out, not how much an admitted agent may do (the ceiling governs that). Empty
    agent_id (the main agent, or a harness that sends none) is never counted.
    Fails open on every error, like every other control here."""
    if not agent_id:
        return False
    path = _active_run_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX)
            except OSError:
                pass
            try:
                run = json.load(fh)
            except ValueError:
                return False
            if not isinstance(run, dict):
                return False
            started = run.get("started_at", 0)
            now = time.time() if now is None else now
            if not started or (now - started) > STALE_SECONDS:
                return False
            agents = run.get("agents")
            if not isinstance(agents, dict):
                agents = {}
            cap = int(run.get("max_agents", DEFAULT_MAX_AGENTS))
            if agent_id not in agents and len(agents) >= cap:
                return True  # new agent, roster full -> deny the fan-out
            agents[agent_id] = int(agents.get(agent_id, 0)) + 1
            run["agents"] = agents
            fh.seek(0)
            json.dump(run, fh)
            fh.truncate()
            return False
    except OSError:
        return False


def iteration_breached(now: float | None = None) -> bool:
    """True iff the active run has hit the same blocker more than the iteration cap.
    Read-only (never mutates the run file). No active/stale run, or any error → False,
    so this can never wedge an unrelated shell — same fail-open contract as the ceiling."""
    path = _active_run_path()
    if not os.path.exists(path):
        return False
    try:
        with open(path) as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_SH)  # shared read lock: never read a torn write
            except OSError:
                pass
            run = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(run, dict):
        return False
    started = run.get("started_at", 0)
    now = time.time() if now is None else now
    if not started or (now - started) > STALE_SECONDS:
        return False
    if _is_orphan_adhoc(run):
        return False
    cap = int(run.get("iteration_cap", DEFAULT_ITERATION_CAP))
    blockers = run.get("blockers", {})
    if not isinstance(blockers, dict):
        return False
    try:
        return any(int(v) > cap for v in blockers.values())
    except (TypeError, ValueError):
        return False


# Forge's OWN run-control commands. A halted run must stay escapable: the ceiling and
# loop-cap messages tell the operator to run `forge_trace end`, but that is itself a
# Bash call, so a breached run blocked its own remedy — the escape hatch sat behind the
# lock, and the only way out was disabling Forge. (Field bug, 2026-07-30.)
#
# Safety: this exempts ONLY a canonical invocation of Forge's own trace CLI with a
# known subcommand, and it is checked AFTER the deny-list, so destructive commands are
# still blocked even when disguised alongside it. Ending a run is itself logged, so the
# escape is auditable rather than silent.
_FORGE_CONTROL = re.compile(
    r"^\s*(?:[\w./\\-]*python[\d.]*\s+)?"              # optional interpreter
    r"[\"']?[^\"'\s]*(?:forge_trace(?:\.py)?|TRACE)[\"']?\s+"  # trace CLI or its alias
    r"(end|start|scope|log|blocker)\b",                   # a known subcommand
    re.I,
)


def is_forge_control(command: str) -> bool:
    """True when the command's effective action is Forge run-control.

    Checked PER SEGMENT, because the real-world invocation is almost never bare: the
    agent writes `cd <project> && python3 .../forge_trace.py end`, and Forge's own
    commands/forge.md uses a `TRACE` alias. A first version matched only the bare form
    and so failed to unlock the very deadlock it was written to fix (field bug,
    2026-07-30). Accepts forge_trace, forge_trace.py and TRACE, with or without an
    interpreter or a leading `cd`.

    Safe because is_denied() runs BEFORE this exemption, so a destructive segment is
    still blocked no matter what it is chained to."""
    return any(_FORGE_CONTROL.match(seg) for seg in _SEP.split(command or ""))


def _halt_message(reason: str) -> str:
    """A halt message whose remedy is COPY-PASTEABLE and actually exists.

    Earlier versions said "run `forge_trace end`" — but forge_trace is a Python script,
    not an executable on PATH, so the guard's own advice could not be run (field bug,
    2026-07-30). A halt the operator cannot clear is a halt that gets Forge uninstalled,
    so the message now resolves the real path and offers the always-works escape."""
    run = _active_run_path()
    here = os.path.dirname(os.path.abspath(__file__))
    trace = os.path.join(os.path.dirname(here), "traces", "forge_trace.py")
    return (
        f"FORGE guard: {reason} — run halted.\n"
        "If this was honest work (a review plus its remediation easily exceeds the "
        "default), close this run at a clean task boundary and start a fresh one.\n"
        f"  Clear it:  rm -f {run}\n"
        f"  Or close properly:  python3 {trace} end --outcome escalated\n"
        "  Or raise the limit:  FORGE_CEILING=<n> (env) / --ceiling <n> at start\n"
        "In Claude Code, prefix with ! to run it in your own shell.\n"
        "If you cannot tell honest work from a runaway, escalate to a human — that is "
        "what this halt is for."
    )


def _run_scope(now: float | None = None) -> list[str] | None:
    """The active run's declared scope globs, or None if the run declared none.

    None means 'no scope enforcement' (the assumption guard is opt-in per run): a run
    that never declared what files it would touch is not second-guessed. An empty list
    is treated the same as None. No/stale/corrupt active run → None. Same fail-open
    contract as the ceiling — an error here can never wedge the shell."""
    path = _active_run_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_SH)
            except OSError:
                pass
            run = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(run, dict):
        return None
    started = run.get("started_at", 0)
    now = time.time() if now is None else now
    if not started or (now - started) > STALE_SECONDS:
        return None
    if _is_orphan_adhoc(run):
        return None
    scope = run.get("scope")
    if not isinstance(scope, list):
        return None
    globs = [s for s in scope if isinstance(s, str) and s.strip()]
    return globs or None


def _path_matches(candidate: str, pattern: str) -> bool:
    """True if `candidate` is covered by scope `pattern`. fnmatch's '*' spans '/',
    so `hooks/*` already covers `hooks/a/b.py`; the extra `pattern/*` form lets a
    bare directory name ('hooks') cover files beneath it."""
    pat = pattern.strip()
    if fnmatch.fnmatch(candidate, pat):
        return True
    return fnmatch.fnmatch(candidate, pat.rstrip("/") + "/*")


def _in_scope(file_path: str, globs: list[str], project_dir: str | None) -> bool:
    """Is `file_path` inside the declared scope? Tried permissively — as given, as a
    path relative to the project dir, and as a basename — because a false 'out of
    scope' block would wedge a legitimate edit. Blocking is reserved for a path that
    matches NONE of these forms against ANY declared glob."""
    candidates = {file_path, os.path.normpath(file_path)}
    if project_dir and os.path.isabs(file_path):
        try:
            candidates.add(os.path.relpath(file_path, project_dir))
        except ValueError:
            pass
    candidates.add(os.path.basename(file_path))
    return any(
        _path_matches(cand, pat) for pat in globs for cand in candidates
    )


def scope_violation(tool_name: str, file_path: str, now: float | None = None) -> str | None:
    """The assumption guard (deterministic slice): block a file-mutating tool whose
    target is OUTSIDE the run's declared scope. Touching a file the plan never said it
    would touch is an unconfirmed scope assumption — exactly the silent scope-creep
    that 'no assumptions' must stop. Returns a deny reason, or None to allow.

    Fails open everywhere ambiguity exists: no declared scope, non-file tool, missing
    file_path, stale/corrupt run → None. It only ever blocks a concrete out-of-scope
    file edit under an active run that DID declare a scope."""
    if tool_name not in _FILE_MUTATING_TOOLS:
        return None
    if not file_path:
        return None
    globs = _run_scope(now)
    if not globs:
        return None
    if _in_scope(file_path, globs, os.environ.get("CLAUDE_PROJECT_DIR")):
        return None
    return (
        f"FORGE guard: out-of-scope edit — {file_path} is not in the run's declared "
        "scope; the plan did not say it would touch this. Don't assume — widen the "
        "scope on purpose (forge_trace scope --add <glob>) or re-plan the task."
    )


# --- harness adapter boundary ------------------------------------------------
# The decision core above is harness-neutral; only the two functions below know
# that harnesses differ. Payload-shape and block-signal knowledge stops here.

# Containers a harness may nest the tool arguments under. Claude Code, Codex,
# Kiro, and Cline use tool_input; Gemini CLI and camelCase harnesses use
# toolInput; some emit params/arguments; a bare top-level "command" is the
# last resort.
_INPUT_KEYS = ("tool_input", "toolInput", "params", "arguments")
_TOOL_NAME_KEYS = ("tool_name", "toolName", "tool")
_AGENT_ID_KEYS = ("agent_id", "agentId", "agent")
# Where a file-mutating tool names its target across harnesses.
_FILE_PATH_KEYS = ("file_path", "filePath", "path", "notebook_path", "notebookPath")

# Tools whose file target the scope guard governs. Bash is deliberately excluded:
# a shell command has no single declared file target, so scope can't be judged from
# it without false positives — the deny-list + ceiling cover Bash instead.
_FILE_MUTATING_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


def _extract(payload: dict[str, Any]) -> dict[str, str]:
    """Normalize a PreToolUse-style payload from ANY known harness into
    {command, tool_name, agent_id, file_path}. Missing/foreign fields -> "" — never
    raise; an unrecognized shape must degrade to "nothing seen", not a crash
    (the fail-open contract extends to parsing)."""
    command = ""
    file_path = ""
    for key in _INPUT_KEYS:
        inner = payload.get(key)
        if isinstance(inner, dict):
            if not command and isinstance(inner.get("command"), str):
                command = inner["command"]
            if not file_path:
                for fk in _FILE_PATH_KEYS:
                    if isinstance(inner.get(fk), str):
                        file_path = inner[fk]
                        break
    if not command and isinstance(payload.get("command"), str):
        command = payload["command"]
    tool_name = ""
    for key in _TOOL_NAME_KEYS:
        val = payload.get(key)
        if isinstance(val, str):
            tool_name = val
            break
    agent_id = ""
    for key in _AGENT_ID_KEYS:
        val = payload.get(key)
        if isinstance(val, str):
            agent_id = val
            break
    return {
        "command": command, "tool_name": tool_name,
        "agent_id": agent_id, "file_path": file_path,
    }


def evaluate(payload: dict[str, Any]) -> str | None:
    """Harness-neutral core decision: the deny reason, or None to allow.
    Same checks, same order, same messages as the guard has always enforced
    (deny-list -> loop cap -> ceiling tick). Ticks the run counter as a side
    effect, exactly as before."""
    fields = _extract(payload)
    command = fields["command"]
    if command and is_denied(command):
        return "FORGE guard: destructive command blocked"
    # Escape hatch, checked AFTER the deny-list: Forge's own run-control commands stay
    # runnable during a halt, or the halt is unrecoverable and users disable Forge.
    if is_forge_control(command):
        return None
    if iteration_breached():
        return _halt_message(
            "loop cap — the same blocker exceeded the iteration limit; attribute "
            "(PLAN|CONTEXT|TOOL|CAPABILITY)")
    scope_reason = scope_violation(fields["tool_name"], fields["file_path"])
    if scope_reason is not None:
        return scope_reason
    # Fan-out cap before the ceiling tick: a denied agent must not consume the run's
    # tool-call budget. Also records per-agent activity, so a multi-agent run can be
    # audited by WHO acted, not just how much happened.
    if record_agent(fields["agent_id"]):
        return (
            "FORGE guard: subagent fan-out cap reached — this run has already engaged "
            "the maximum number of agents; consolidate the work or raise FORGE_MAX_AGENTS"
        )
    if tick_and_check():
        return _halt_message("tool-call ceiling reached")
    return None


def _block_mode(argv: list[str] | None = None) -> str:
    """Resolve the block-signal mode: 'exit2' (default) or 'json'.
    Precedence: --mode flag > FORGE_BLOCK_MODE env > exit2. Anything
    unrecognized falls back to exit2 — the mode selector must never be a way
    to accidentally disable blocking."""
    argv = sys.argv[1:] if argv is None else argv
    mode = ""
    for i, arg in enumerate(argv):
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]
    if not mode:
        mode = os.environ.get("FORGE_BLOCK_MODE", "")
    return "json" if mode.strip().lower() == "json" else "exit2"


def _emit_block(reason: str, mode: str) -> int:
    """Speak the harness's block signal for a confirmed deny.
    exit2 (default): reason on stderr, exit 2 — Claude Code, Codex, Kiro,
    Cline, Gemini, grok-build, Goose, Kimi all block on this.
    json: the PreToolUse deny-decision object on stdout, exit 0 — for
    harnesses that consume a permissionDecision instead of the exit code."""
    if mode == "json":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        return 0
    print(reason, file=sys.stderr)
    return 2


def decide(payload: dict[str, Any]) -> int:
    """Claude Code contract, unchanged: exit-2 + stderr on deny, 0 on allow."""
    reason = evaluate(payload)
    if reason is None:
        return 0
    return _emit_block(reason, "exit2")


def main() -> int:
    try:
        mode = _block_mode()
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0  # non-object JSON (null/[]/"x") → nothing to guard
        if mode == "exit2":
            return decide(payload)  # the exact pre-multi-harness Claude Code path
        reason = evaluate(payload)
        return 0 if reason is None else _emit_block(reason, mode)
    except Exception:  # noqa: BLE001 — fail OPEN on ANY error, per the contract
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
