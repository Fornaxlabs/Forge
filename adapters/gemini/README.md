# Google Gemini CLI adapter

Gemini CLI's pre-tool event is **`BeforeTool`** (NOT `PreToolUse`), matched on
the tool name, with the payload on stdin; block = exit 2 + stderr (its
`hookSpecificOutput.tool_input` can additionally override tool args — Forge
does not use that). The guard's `_extract` handles Gemini's payload nesting
(`toolInput`/`tool_input`/`params`/`arguments`). Install: merge the `hooks`
block from `settings.json` here into your project's `.gemini/settings.json`
(or `~/.gemini/settings.json` for user-wide), replacing
`__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge checkout —
`scripts/forge-init.sh --harness gemini` stamps a substituted copy at
`.gemini/settings.json` if none exists (it never clobbers an existing file;
merge by hand in that case). The matcher lists Gemini's mutating tools
(`run_shell_command|write_file|replace`); widen it if your version names them
differently. **Status: built to the documented contract
(github.com/google-gemini/gemini-cli docs); NOT yet validated on the live
harness.**
