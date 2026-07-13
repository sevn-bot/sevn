<!-- generated: do not edit by hand; run `sevn readme update integrations` -->
# Integrations — Cursor Cloud, GitHub skill clients, and external integration call paths

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Cursor Cloud, GitHub skill clients, and external integration call paths. Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

## Level 1 — Overview (non-technical)

**Integrations** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Cursor Cloud, GitHub skill clients, and external integration call paths.

In everyday use, integrations helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/integrations/`. The package contains 16 Python module(s); primary entry points include `src/sevn/integrations/__init__.py`, `src/sevn/integrations/code_graph_rag/__init__.py`, `src/sevn/integrations/cursor_cloud/__init__.py`, `src/sevn/integrations/cursor_cloud/client.py`, and 2 more.

### Data and control flow

Integrations sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/34-plugin-hooks.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/integrations/cursor_cloud/client.py` — `create_cloud_agent`, `get_agent`, `get_run`, `list_artifacts`
- `src/sevn/integrations/cursor_cloud/config.py` — `load_cursor_cloud_settings`
- `src/sevn/integrations/cursor_cloud/jobs.py` — `insert_job`, `get_job`, `update_job`, `list_workspace_jobs`
- `src/sevn/integrations/github_skill/client.py` — `parse_github_repo`, `github_integration_call`, `github_integration_call_sync`, `github_legacy_call`
- `src/sevn/integrations/github_skill/gh_issues.py` — `list_issues`, `view_issue`, `create_issue`, `comment_on_issue`

### Spec context

From about-sevn.bot/specs/34-plugin-hooks.md:
Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/integrations/` (16 Python files). Normative design: `about-sevn.bot/specs/34-plugin-hooks.md`.

### Module inventory

- `src/sevn/integrations/__init__.py` — """External system integrations (scaffold).
- `src/sevn/integrations/code_graph_rag/__init__.py` — """Optional CGR integration package root ('about-sevn.bot/specs/28-code-understanding.md' §4.2).
- `src/sevn/integrations/cursor_cloud/__init__.py` — """Cursor Cloud Agent integration for bundled ''cursor_cloud'' skill.
- `src/sevn/integrations/cursor_cloud/client.py` — """Cursor Cloud Agents API client via egress proxy.
- `src/sevn/integrations/cursor_cloud/config.py` — """Workspace config helpers for ''cursor_cloud'' skill.
- `src/sevn/integrations/cursor_cloud/errors.py` — """Stable error codes for Cursor cloud integration.
- `src/sevn/integrations/cursor_cloud/jobs.py` — """SQLite persistence for Cursor cloud agent jobs.
- `src/sevn/integrations/github_skill/__init__.py` — """GitHub bundled skill helpers — REST via ''integration_call'' proxy.
- `src/sevn/integrations/github_skill/client.py` — """Shared GitHub skill helpers — repo parsing and integration dispatch.
- `src/sevn/integrations/github_skill/gh_issues.py` — """Issue operations for bundled ''gh-issues'' skill scripts.
- `src/sevn/integrations/github_skill/gh_pr.py` — """Pull request operations for bundled ''gh-pr'' skill scripts.
- `src/sevn/integrations/github_skill/github_manager.py` — """GitHub manager operations for bundled ''github-manager'' skill scripts.
- … and 4 more Python modules

### Client (`src/sevn/integrations/cursor_cloud/client.py`)

Public entry points:
- `create_cloud_agent` — see `src/sevn/integrations/cursor_cloud/client.py`
- `get_agent` — see `src/sevn/integrations/cursor_cloud/client.py`
- `get_run` — see `src/sevn/integrations/cursor_cloud/client.py`
- `list_artifacts` — see `src/sevn/integrations/cursor_cloud/client.py`
- `artifact_download_url` — see `src/sevn/integrations/cursor_cloud/client.py`
- `refresh_job_status` — see `src/sevn/integrations/cursor_cloud/client.py`
- `parse_mcp_servers_json` — see `src/sevn/integrations/cursor_cloud/client.py`
- `parse_subagents_json` — see `src/sevn/integrations/cursor_cloud/client.py`

### Config (`src/sevn/integrations/cursor_cloud/config.py`)

Public entry points:
- `load_cursor_cloud_settings` — see `src/sevn/integrations/cursor_cloud/config.py`

### Jobs (`src/sevn/integrations/cursor_cloud/jobs.py`)

Public entry points:
- `insert_job` — see `src/sevn/integrations/cursor_cloud/jobs.py`
- `get_job` — see `src/sevn/integrations/cursor_cloud/jobs.py`
- `update_job` — see `src/sevn/integrations/cursor_cloud/jobs.py`
- `list_workspace_jobs` — see `src/sevn/integrations/cursor_cloud/jobs.py`

### Client (`src/sevn/integrations/github_skill/client.py`)

Public entry points:
- `parse_github_repo` — see `src/sevn/integrations/github_skill/client.py`
- `github_integration_call` — see `src/sevn/integrations/github_skill/client.py`
- `github_integration_call_sync` — see `src/sevn/integrations/github_skill/client.py`
- `github_legacy_call` — see `src/sevn/integrations/github_skill/client.py`

### Gh Issues (`src/sevn/integrations/github_skill/gh_issues.py`)

Public entry points:
- `list_issues` — see `src/sevn/integrations/github_skill/gh_issues.py`
- `view_issue` — see `src/sevn/integrations/github_skill/gh_issues.py`
- `create_issue` — see `src/sevn/integrations/github_skill/gh_issues.py`
- `comment_on_issue` — see `src/sevn/integrations/github_skill/gh_issues.py`

### Additional modules

4 more Python files under `src/sevn/integrations/` — including `src/sevn/integrations/github_skill/hooks.py`, `src/sevn/integrations/litellm_lap/__init__.py`, `src/sevn/integrations/litellm_lap/client.py`, `src/sevn/integrations/proxy_client.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/34-plugin-hooks.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/integrations/`, run `sevn readme update integrations` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/34-plugin-hooks.md](../../about-sevn.bot/specs/34-plugin-hooks.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/34-plugin-hooks.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/integrations/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
