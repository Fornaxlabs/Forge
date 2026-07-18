# Cline adapter

Cline fires a `PreToolUse` hook with the tool payload as JSON on stdin: exit 0
allows, exit 2 blocks (stderr is surfaced as the reason). Install: merge the
`hooks` block from `settings.json` here into your Cline settings file
(project `.cline/settings.json`, or the global Cline settings), replacing
`__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge checkout —
`scripts/forge-init.sh --harness cline` stamps a substituted copy at
`.cline/settings.json` if none exists. The matcher lists Cline's mutating
tools (`execute_command|write_to_file|replace_in_file`); adjust if your
version names them differently. **Status: built to the documented contract
(docs.cline.bot); NOT yet validated on the live harness.**
