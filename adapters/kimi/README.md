# Kimi Code CLI adapter

Kimi Code CLI fires blockable `PreToolUse` hooks configured as `[[hooks]]`
tables in `~/.kimi/config.toml` (event / matcher / command / timeout; payload
on stdin; block = exit 2 + stderr, or the deny-JSON decision — the guard
speaks both, exit-2 by default). Install: append the `[[hooks]]` block from
`config.toml` here to your `~/.kimi/config.toml`, replacing
`__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge checkout —
`scripts/forge-init.sh --harness kimi` stamps a substituted copy into the
project (`.forge/kimi-hooks.toml`) ready to paste, since Kimi's config is
user-global rather than per-project. Adjust the matcher if your Kimi build
uses different mutating-tool names. **Status: built to the documented
contract; NOT yet validated on the live harness.**
