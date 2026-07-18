# Forge adapters — one guard, many harnesses

Every subdirectory here is a thin **install config** that wires the SAME
`hooks/guard.py` into a different agent harness. There are no per-harness forks
of the decision logic — the deny-list, tool-call ceiling, and loop cap live in
one file; adapters only tell each harness when to run it and how to read its
block signal (exit-2 + stderr by default; deny-JSON via `--mode json` /
`FORGE_BLOCK_MODE=json` for harnesses that consume a `permissionDecision`).

Configs ship with the placeholder `__FORGE_PLUGIN_ROOT__` where the harness has
no plugin-root variable of its own — replace it with the absolute path of your
Forge checkout, or let `scripts/forge-init.sh --harness <name>` substitute it
for you when stamping a project. The Claude Code path needs no adapter: the
native `hooks/hooks.json` (using `${CLAUDE_PLUGIN_ROOT}`) is unchanged.

**Honesty note:** only the Claude Code wiring is validated end-to-end. Every
other adapter is built to that harness's documented hook contract and has NOT
been validated on the live harness — see `docs/HARNESSES.md` for the full
matrix, including the documented subagent-bypass gaps (OpenCode, Copilot) and
harnesses with no pre-tool hook at all (Aider: git/CI floor only).
