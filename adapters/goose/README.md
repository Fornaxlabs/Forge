# Block Goose adapter

Goose implements the Open Plugins hooks spec: it auto-discovers
`hooks/hooks.json` bundles under `~/.agents/plugins/*/hooks/hooks.json` and
fires `PreToolUse` denial hooks (payload on stdin; block = exit 2, or a
deny-JSON decision — the guard emits either, exit-2 by default). Install:
create `~/.agents/plugins/forge/hooks/` and copy this `hooks.json` there,
replacing `__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge
checkout; `scripts/forge-init.sh --harness goose` stamps a project-local copy
at `.agents/plugins/forge/hooks/hooks.json` with the path substituted, which
you can copy or symlink into `~/.agents/plugins/`. The matcher is `*` because
Goose tool names differ from Claude Code's — the ceiling will then count every
hooked tool call, so tighten the matcher to your mutating tools if the harness
supports it. **Status: built to the documented Open Plugins contract
(block.github.io/goose); NOT yet validated on the live harness.**
