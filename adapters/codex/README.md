# Codex CLI adapter

Codex CLI exposes a Claude-Code-shaped hook system: a `PreToolUse` event with
the tool payload on stdin, blocked by exit 2 + stderr — or by a JSON decision
(`{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision":
"deny", ...}}` on stdout; run the guard with `--mode json` or
`FORGE_BLOCK_MODE=json` if you prefer that signal). Install: copy `hooks.json`
into your project as `.codex/hooks.json` (or bundle it as a plugin's
`hooks/hooks.json` per the Open Plugins spec), replacing
`__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge checkout —
`scripts/forge-init.sh --harness codex` does both. **Status: built to the
documented contract (developers.openai.com/codex/hooks); NOT yet validated on
the live harness.**
