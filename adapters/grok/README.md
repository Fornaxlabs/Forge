# grok-build adapter

grok-build fires a `PreToolUse` deny hook with the tool payload as JSON on
stdin: exit 0 allows, exit 2 blocks, and a JSON decision on stdout is also
honored (run the guard with `--mode json` / `FORGE_BLOCK_MODE=json` for that
signal; exit-2 is the default). Install: copy `hooks.json` into grok-build's
hook config location for your project (`.grok/hooks.json`), replacing
`__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge checkout —
`scripts/forge-init.sh --harness grok` does both. The matcher is `*` pending
confirmed mutating-tool names; tighten it so the ceiling counts only mutating
calls. **Status: built to the documented contract; NOT yet validated on the
live harness.**
