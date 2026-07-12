---
name: cursor_cloud
description: Delegate code+PR work to Cursor Cloud Agent; returns PR, dashboard, and artifact links.
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
scripts:
  - path: scripts/launch.py
    description: Launch a Cursor Cloud Agent on a GitHub/GitLab repo (mutating).
    args_overview: "--prompt STR [--repo-url URL] [--ref REF] [--model ID] [--auto-create-pr|--no-auto-create-pr] [--mcp-profile NAME] [--mcp-servers-json JSON] [--subagents-json JSON] [--session-key KEY]"
    abortable: false
  - path: scripts/status.py
    description: Poll agent + latest run; update local job and return PR/dashboard URLs.
    args_overview: "[--job-id UUID | --cursor-agent-id bc-...]"
  - path: scripts/list_jobs.py
    description: List persisted Cursor cloud jobs for this workspace.
    args_overview: "[--session-key KEY] [--limit N]"
  - path: scripts/list_artifacts.py
    description: List artifacts for an agent; optional presigned download URL for one path.
    args_overview: "[--job-id UUID | --cursor-agent-id bc-...] [--download-path artifacts/...]"
---

# Cursor Cloud Agent skill

Delegate implementation work to a **Cursor Cloud Agent** when `skills.cursor_cloud.enabled` is true and
`integration.cursor.api_key` is configured on the egress proxy.

## Prerequisites

1. Enable **`skills.cursor_cloud.enabled`** in `sevn.json`.
2. Store **`integration.cursor.api_key`** via `sevn secrets` (Cursor Dashboard → Integrations).
3. Connect GitHub/GitLab to Cursor; target repo must be accessible with read/write.

## Hooks (automatic)

Cloud agents run **`.cursor/hooks.json`** from the cloned repository (formatters, audit scripts, policy).
No sevn step is required — ensure hooks exist on the branch you delegate.

## MCP

- Optional **`--mcp-profile NAME`** uses `skills.cursor_cloud.mcp_profiles` (secrets expanded on proxy).
- Optional **`--mcp-servers-json`** passes inline `mcpServers` to the Cursor API.
- Team MCP configured at [cursor.com/agents](https://cursor.com/agents) is additive.

## Workflow

1. Confirm with the user before **`launch.py`** (creates a real cloud run).
2. `run_skill_script` → `scripts/launch.py` with `--prompt` and `--repo-url` (or workspace default).
3. Poll `scripts/status.py` until status is terminal (`FINISHED`, `ERROR`, `CANCELLED`, `EXPIRED`).
4. Share **`agent_url`** for remote desktop review; use `list_artifacts.py` for screenshots/videos/logs.
5. Return **`pr_url`** when `autoCreatePR` was requested.

## Remote desktop

Open **`agent_url`** (`https://cursor.com/agents/{id}`) in a browser to control the agent's cloud desktop
or inspect artifacts — sevn does not embed the session.
