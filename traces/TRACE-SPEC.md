# FORGE trace specification

## Format
- JSONL, one file per run: `traces/runs/<date>-<slug>.jsonl`.
- `traces/runs/` is gitignored; retention 90 days.
- Every event object carries: `ts`, `run_id`, `event`, plus an event-specific payload.

## "Geen bewijs = niet gebeurd"
Every /forge run produces a trace. It must begin with `run_start` and end with `run_end`.

## Event types and payloads
| event         | payload fields                                             |
|---------------|------------------------------------------------------------|
| `run_start`   | `task`, `triage` (SMALL/MEDIUM/LARGE), `git_ref`           |
| `plan`        | `agent`, `version`, `chosen_of_n`                          |
| `build`       | `files` (paths), `layer0_result` (lint/test pass|fail)     |
| `review`      | `iteration`, `findings` (list), `repeats` (list of ref)    |
| `attribution` | `category` (PLAN\|CONTEXT\|TOOL\|CAPABILITY), `note`       |
| `escalation`  | `to` (anvil\|human)                                        |
| `checkpoint`  | `ref` (commit sha or stash ref)                            |
| `run_end`     | `outcome`, `iterations`, `tool_calls`                      |

## Privacy
- No secrets/PII in traces.
- No line content from sensitive files — reference by `path:line` only.

## Example line
```json
{"ts":"2026-07-06T10:00:00+00:00","run_id":"2026-07-06-add-auth","event":"run_start","task":"add JWT auth","triage":"LARGE","git_ref":"a1b2c3d"}
```
