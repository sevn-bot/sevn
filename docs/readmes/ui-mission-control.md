<!-- generated: do not edit by hand; run `sevn readme update ui-mission-control` -->
# Mission Control UI — Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery.

## Level 1 — Overview (non-technical)

**Mission Control UI** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery.

In everyday use, mission control ui helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver Mission Control: a same-process dashboard (prd-07-mission-control) so the owner can inspect traces, costs, provider health, in-flight runs, proxy status, and config without opening SQLite from

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/ui/`. The package contains 65 Python module(s); primary entry points include `src/sevn/ui/__init__.py`, `src/sevn/ui/dashboard/__init__.py`, `src/sevn/ui/dashboard/api/__init__.py`, `src/sevn/ui/dashboard/api/_config_persist.py`, and 2 more.

### Data and control flow

Mission Control UI sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/24-dashboard.md`, `about-sevn.bot/specs/29-openui.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/ui/dashboard/__init__.py` — `register_dashboard_routes`
- `src/sevn/ui/dashboard/api/__init__.py` — `create_dashboard_api_router`
- `src/sevn/ui/dashboard/api/_config_persist.py` — `config_error`, `config_validation_error`, `read_config_body`, `load_workspace_document`
- `src/sevn/ui/dashboard/api/agent.py` — `tools_health_list`, `skills_inventory`, `skills_promote`, `skills_bundled_list`
- `src/sevn/ui/dashboard/api/audit.py` — `audit_timeline`, `analytics_tool_frequency`, `analytics_daily_volume`, `analytics_approvals`

### Spec context

From about-sevn.bot/specs/24-dashboard.md:
Deliver Mission Control: a same-process dashboard (prd-07-mission-control) so the owner can inspect traces, costs, provider health, in-flight runs, proxy status, and config without opening SQLite from

From about-sevn.bot/specs/29-openui.md:
Deliver OpenUI: explicit openui_render tool calls produce sanitised, CSP-wrapped, size-capped HTML (live or rasterised) and deterministic form callbacks that rejoin the same executor turn for tier B /

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/ui/` (65 Python files). Normative design: `about-sevn.bot/specs/24-dashboard.md`, `about-sevn.bot/specs/29-openui.md`.

### Module inventory

- `src/sevn/ui/__init__.py` — """User interface components (scaffold).
- `src/sevn/ui/dashboard/__init__.py` — """Mission Control dashboard registration facade ('about-sevn.bot/specs/24-dashboard.md' §4.1).
- `src/sevn/ui/dashboard/api/__init__.py` — """Mission Control REST API router assembly.
- `src/sevn/ui/dashboard/api/_config_persist.py` — """Shared helpers for persisting Mission Control config edits to ''sevn.json''.
- `src/sevn/ui/dashboard/api/agent.py` — """Mission Control Agent group REST router ('about-sevn.bot/specs/24-dashboard.md' MC-7).
- `src/sevn/ui/dashboard/api/audit.py` — """Dashboard audit trail and analytics REST router.
- `src/sevn/ui/dashboard/api/auth.py` — """Dashboard auth REST router.
- `src/sevn/ui/dashboard/api/canvas.py` — """Dashboard OpenUI Canvas tab REST router ('about-sevn.bot/specs/24-dashboard.md' §4.4).
- `src/sevn/ui/dashboard/api/channels.py` — """Dashboard channels and alert rollup REST routers ('about-sevn.bot/specs/24-dashboard.md' MC-5).
- `src/sevn/ui/dashboard/api/chat.py` — """Mission Control in-dashboard webchat console API (MC W6).
- `src/sevn/ui/dashboard/api/cli_console.py` — """Mission Control sevn CLI console API (MC W1 §2c).
- `src/sevn/ui/dashboard/api/coding_agents.py` — """Mission Control Coding Agents hub REST router (CA1 + CA6.2 artifacts).
- … and 53 more Python modules

###   Init   (`src/sevn/ui/dashboard/__init__.py`)

Public entry points:
- `register_dashboard_routes` — see `src/sevn/ui/dashboard/__init__.py`

###   Init   (`src/sevn/ui/dashboard/api/__init__.py`)

Public entry points:
- `create_dashboard_api_router` — see `src/sevn/ui/dashboard/api/__init__.py`

###  Config Persist (`src/sevn/ui/dashboard/api/_config_persist.py`)

Public entry points:
- `config_error` — see `src/sevn/ui/dashboard/api/_config_persist.py`
- `config_validation_error` — see `src/sevn/ui/dashboard/api/_config_persist.py`
- `read_config_body` — see `src/sevn/ui/dashboard/api/_config_persist.py`
- `load_workspace_document` — see `src/sevn/ui/dashboard/api/_config_persist.py`
- `persist_workspace_document` — see `src/sevn/ui/dashboard/api/_config_persist.py`
- `deep_merge` — see `src/sevn/ui/dashboard/api/_config_persist.py`

### Agent (`src/sevn/ui/dashboard/api/agent.py`)

Public entry points:
- `tools_health_list` — see `src/sevn/ui/dashboard/api/agent.py`
- `skills_inventory` — see `src/sevn/ui/dashboard/api/agent.py`
- `skills_promote` — see `src/sevn/ui/dashboard/api/agent.py`
- `skills_bundled_list` — see `src/sevn/ui/dashboard/api/agent.py`
- `skills_install` — see `src/sevn/ui/dashboard/api/agent.py`
- `skills_uninstall` — see `src/sevn/ui/dashboard/api/agent.py`
- `skills_toggle` — see `src/sevn/ui/dashboard/api/agent.py`
- `mcp_servers_registry` — see `src/sevn/ui/dashboard/api/agent.py`

### Audit (`src/sevn/ui/dashboard/api/audit.py`)

Public entry points:
- `audit_timeline` — see `src/sevn/ui/dashboard/api/audit.py`
- `analytics_tool_frequency` — see `src/sevn/ui/dashboard/api/audit.py`
- `analytics_daily_volume` — see `src/sevn/ui/dashboard/api/audit.py`
- `analytics_approvals` — see `src/sevn/ui/dashboard/api/audit.py`

### Auth (`src/sevn/ui/dashboard/api/auth.py`)

Public entry points:
- `auth_status` — see `src/sevn/ui/dashboard/api/auth.py`
- `login` — see `src/sevn/ui/dashboard/api/auth.py`
- `logout` — see `src/sevn/ui/dashboard/api/auth.py`

### Canvas (`src/sevn/ui/dashboard/api/canvas.py`)

Public entry points:
- `dashboard_canvas` — see `src/sevn/ui/dashboard/api/canvas.py`

### Channels (`src/sevn/ui/dashboard/api/channels.py`)

Public entry points:
- `channels_status` — see `src/sevn/ui/dashboard/api/channels.py`
- `alerts_rollup` — see `src/sevn/ui/dashboard/api/channels.py`
- `channels_config_get` — see `src/sevn/ui/dashboard/api/channels.py`
- `channels_config_put` — see `src/sevn/ui/dashboard/api/channels.py`

### Chat (`src/sevn/ui/dashboard/api/chat.py`)

Public entry points:
- `chat_token` — see `src/sevn/ui/dashboard/api/chat.py`
- `chat_fork` — see `src/sevn/ui/dashboard/api/chat.py`

### Additional modules

53 more Python files under `src/sevn/ui/` — including `src/sevn/ui/dashboard/api/deps.py`, `src/sevn/ui/dashboard/api/evolution.py`, `src/sevn/ui/dashboard/api/files.py`, `src/sevn/ui/dashboard/api/knowledge.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/24-dashboard.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/ui/`, run `sevn readme update ui-mission-control` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/24-dashboard.md](../../about-sevn.bot/specs/24-dashboard.md)
- [../../about-sevn.bot/specs/29-openui.md](../../about-sevn.bot/specs/29-openui.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/24-dashboard.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/ui/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
