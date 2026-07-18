# Forge across harnesses — the honest matrix

One harness-neutral guard (`hooks/guard.py`: deny-list + tool-call ceiling +
loop cap) behind thin per-harness install configs (`adapters/`). The guard
reads any of the documented payload shapes
(`tool_input`/`toolInput`/`params`/`arguments`/bare `command`) and speaks two
block signals: **exit-2 + stderr** (default) and **deny-JSON on stdout**
(`--mode json` / `FORGE_BLOCK_MODE=json`).

**Read the validation column before trusting a row.** Only Claude Code is
validated end-to-end. Everything else is built to that harness's *documented*
hook contract and has not been proven on the live harness. A guard you haven't
watched block a real `rm -rf /` is a hypothesis, not a control.

| Harness | Hook event | Block signal | Config file | Subagent bypass? | Validation status |
|---|---|---|---|---|---|
| **Claude Code** | `PreToolUse` | exit 2 + stderr | `hooks/hooks.json` (plugin, `${CLAUDE_PLUGIN_ROOT}`) | No — subagent tool calls fire the same hook (verified); run counter is fleet-wide | **Validated end-to-end (this session):** blocks destructive Bash, enforces ceiling + loop cap, incl. from subagents |
| **Codex CLI** | `PreToolUse` | exit 2 **or** deny-JSON | `.codex/hooks.json` / plugin `hooks/hooks.json` (`adapters/codex/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **Block Goose** | `PreToolUse` (Open Plugins spec) | exit 2 / deny | `~/.agents/plugins/*/hooks/hooks.json` (`adapters/goose/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **AWS Kiro CLI** | `PreToolUse` | exit 0 allow / exit 2 block | Kiro hooks dir, e.g. `.kiro/hooks/forge-guard.json` (`adapters/kiro/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **Google Gemini CLI** | **`BeforeTool`** (not PreToolUse) | exit 2 + stderr (`hookSpecificOutput.tool_input` can also rewrite args) | `.gemini/settings.json` (`adapters/gemini/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **Kimi Code CLI** | `PreToolUse` | exit 2 / deny-JSON | `~/.kimi/config.toml` `[[hooks]]` (`adapters/kimi/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **grok-build** | `PreToolUse` | exit 0/2, JSON stdin/stdout | grok hook config, e.g. `.grok/hooks.json` (`adapters/grok/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **Cline** | `PreToolUse` | exit 0 allow / exit 2 block | Cline settings.json (`adapters/cline/`) | Not verified by us | Built to documented contract; NOT yet validated on the live harness |
| **OpenCode** | pre-tool plugin hook | plugin deny | plugin | **YES — documented gap:** hooks do NOT fire inside subagents, and MCP tool calls bypass hooks entirely | Not adapted — the bypass gaps break Forge's run-wide invariant; git/CI floor still applies |
| **GitHub Copilot (agent)** | — | — | — | **YES — documented gap:** hooks not enforced inside subagents | Not adapted; git/CI floor only |
| **Aider** | **none** — no pre-tool hook exists | — | — | n/a | **git/CI floor only** — pre-commit/pre-push/CI gates work; no in-session guard is possible |

## What "git/CI floor" means

Even where no in-session guard can run, Forge's Layer A still holds: gitleaks
pre-commit + pre-push secret gates, lint/type/test/SBOM CI, and the standards
docs. Those are enforced by git and CI, not by the harness — they survive any
agent, including ones with no hook API at all.

## Known limits (do not oversell)

- **The deny-list is a footgun-catcher, not a security boundary** — true on
  every harness (see the guard's HONEST LIMIT).
- **Subagent coverage is only proven on Claude Code.** On every other harness,
  whether subagent tool calls fire the pre-tool hook is unverified; OpenCode
  and Copilot are *documented* not to enforce it. Treat the ceiling/loop-cap as
  main-agent-only there until proven otherwise.
- **Matchers differ per harness.** Where mutating-tool names are unconfirmed,
  adapters ship `matcher: "*"` — the ceiling then counts every hooked call, so
  tighten the matcher once you know the harness's tool names.
- **Contract drift.** Harness hook APIs are young and change; adapters are thin
  on purpose so drift is absorbed at the edge, never in the decision core.

## Sources

- Claude Code hooks: https://docs.anthropic.com/en/docs/claude-code/hooks
- Codex CLI hooks: https://developers.openai.com/codex/hooks ·
  https://deepwiki.com/openai/codex/3.11-hooks-system
- Block Goose (Open Plugins hooks discovery): https://block.github.io/goose/
- AWS Kiro hooks: https://docs.aws.amazon.com/kiro/
- Gemini CLI (`BeforeTool`): https://github.com/google-gemini/gemini-cli
- Cline: https://docs.cline.bot/
- Kernel-vs-harness enforcement framing: https://www.firecrawl.dev/blog/best-ai-coding-agents
