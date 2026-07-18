# AWS Kiro CLI adapter

Kiro CLI fires a `PreToolUse` hook with the tool payload as JSON on stdin:
exit 0 allows, exit 2 blocks. Install: copy `hooks.json` into your project's
Kiro hooks directory (`.kiro/hooks/forge-guard.json`), replacing
`__FORGE_PLUGIN_ROOT__` with the absolute path to your Forge checkout —
`scripts/forge-init.sh --harness kiro` does both. The matcher is `*` pending
confirmed mutating-tool names in Kiro's hook schema; tighten it so the
tool-call ceiling counts only mutating calls, and adapt the JSON keys if your
Kiro version uses a different hook-file schema (the guard itself is
schema-tolerant — it reads `tool_input`/`toolInput`/`params`/`arguments`).
**Status: built to the documented contract (docs.aws.amazon.com/kiro); NOT
yet validated on the live harness.**
