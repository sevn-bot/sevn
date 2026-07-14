<!-- generated: do not edit by hand; run `sevn readme update ui-mission-control` -->
# Mission Control UI — Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery.

## Level 1 — Overview (non-technical)

**Mission Control UI** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery.

In everyday use, mission control ui helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/ui/`. The package contains 66 Python module(s); primary entry points include `src/sevn/ui/__init__.py`, `src/sevn/ui/dashboard/__init__.py`, `src/sevn/ui/dashboard/api/__init__.py`, `src/sevn/ui/dashboard/api/_config_persist.py`, `src/sevn/ui/dashboard/api/agent.py`, `src/sevn/ui/dashboard/api/audit.py`, and 60 more.

### Data and control flow

Mission Control UI is organized around `  init  `, `  init  `, `  init  `, ` config persist`, and 2 more under `src/sevn/ui/` with 66 Python module(s) in the scanned tree. Primary entry points include __init__.py (register_dashboard_routes), __init__.py (create_dashboard_api_router), _config_persist.py (config_error), agent.py (tools_health_list).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/24-dashboard.md`, `about-sevn.bot/specs/29-openui.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/ui/dashboard/__init__.py` — `register_dashboard_routes`
- `src/sevn/ui/dashboard/api/__init__.py` — `create_dashboard_api_router`
- `src/sevn/ui/dashboard/api/_config_persist.py` — `config_error`, `config_validation_error`, `read_config_body`, `load_workspace_document`
- `src/sevn/ui/dashboard/api/agent.py` — `tools_health_list`, `skills_inventory`, `skills_promote`, `skills_bundled_list`
- `src/sevn/ui/dashboard/api/audit.py` — `audit_timeline`, `analytics_tool_frequency`, `analytics_daily_volume`, `analytics_approvals`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/ui`](../../src/sevn/ui/) (66 Python files). Normative design: `about-sevn.bot/specs/24-dashboard.md`, `about-sevn.bot/specs/29-openui.md`.

### Module inventory

User interface components (scaffold).

Working with [`__init__.py`](../../src/sevn/ui/__init__.py): inspect the public entry points below.

Mission Control dashboard registration facade (about-sevn.bot/specs/24-dashboard.md §4.1).

Working with [`__init__.py`](../../src/sevn/ui/dashboard/__init__.py): inspect the public entry points below.
Start with [`register_dashboard_routes`](../../src/sevn/ui/dashboard/__init__.py#L24).

Mission Control REST API router assembly.

Working with [`__init__.py`](../../src/sevn/ui/dashboard/api/__init__.py): inspect the public entry points below.
Start with [`create_dashboard_api_router`](../../src/sevn/ui/dashboard/api/__init__.py#L43).

Shared helpers for persisting Mission Control config edits to sevn.json.

Working with [`_config_persist.py`](../../src/sevn/ui/dashboard/api/_config_persist.py): inspect the public entry points below.
Start with [`config_error`](../../src/sevn/ui/dashboard/api/_config_persist.py#L33), then [`config_validation_error`](../../src/sevn/ui/dashboard/api/_config_persist.py#L55), [`read_config_body`](../../src/sevn/ui/dashboard/api/_config_persist.py#L76), [`load_workspace_document`](../../src/sevn/ui/dashboard/api/_config_persist.py#L98).

Mission Control Agent group REST router (about-sevn.bot/specs/24-dashboard.md MC-7).

Working with [`agent.py`](../../src/sevn/ui/dashboard/api/agent.py): inspect the public entry points below.
Start with [`tools_health_list`](../../src/sevn/ui/dashboard/api/agent.py#L305), then [`skills_inventory`](../../src/sevn/ui/dashboard/api/agent.py#L341), [`skills_promote`](../../src/sevn/ui/dashboard/api/agent.py#L377), [`skills_bundled_list`](../../src/sevn/ui/dashboard/api/agent.py#L435).

Dashboard audit trail and analytics REST router.

Working with [`audit.py`](../../src/sevn/ui/dashboard/api/audit.py): inspect the public entry points below.
Start with [`audit_timeline`](../../src/sevn/ui/dashboard/api/audit.py#L57), then [`analytics_tool_frequency`](../../src/sevn/ui/dashboard/api/audit.py#L108), [`analytics_daily_volume`](../../src/sevn/ui/dashboard/api/audit.py#L138), [`analytics_approvals`](../../src/sevn/ui/dashboard/api/audit.py#L168).

Dashboard auth REST router.

Working with [`auth.py`](../../src/sevn/ui/dashboard/api/auth.py): inspect the public entry points below.
Start with [`auth_status`](../../src/sevn/ui/dashboard/api/auth.py#L33), then [`login`](../../src/sevn/ui/dashboard/api/auth.py#L70), [`logout`](../../src/sevn/ui/dashboard/api/auth.py#L126).

Dashboard OpenUI Canvas tab REST router (about-sevn.bot/specs/24-dashboard.md §4.4).

Working with [`canvas.py`](../../src/sevn/ui/dashboard/api/canvas.py): inspect the public entry points below.
Start with [`dashboard_canvas`](../../src/sevn/ui/dashboard/api/canvas.py#L81).

Dashboard channels and alert rollup REST routers (about-sevn.bot/specs/24-dashboard.md MC-5).

Working with [`channels.py`](../../src/sevn/ui/dashboard/api/channels.py): inspect the public entry points below.
Start with [`channels_status`](../../src/sevn/ui/dashboard/api/channels.py#L159), then [`alerts_rollup`](../../src/sevn/ui/dashboard/api/channels.py#L188), [`channels_config_get`](../../src/sevn/ui/dashboard/api/channels.py#L273), [`channels_config_put`](../../src/sevn/ui/dashboard/api/channels.py#L297).

Mission Control in-dashboard webchat console API (MC W6).

Working with [`chat.py`](../../src/sevn/ui/dashboard/api/chat.py): inspect the public entry points below.
Start with [`chat_token`](../../src/sevn/ui/dashboard/api/chat.py#L106), then [`chat_fork`](../../src/sevn/ui/dashboard/api/chat.py#L160).

Mission Control sevn CLI console API (MC W1 §2c).

Working with [`cli_console.py`](../../src/sevn/ui/dashboard/api/cli_console.py): inspect the public entry points below.
Start with [`cli_shortcuts`](../../src/sevn/ui/dashboard/api/cli_console.py#L169), then [`cli_run`](../../src/sevn/ui/dashboard/api/cli_console.py#L199).

Mission Control Coding Agents hub REST router (CA1 + CA6.2 artifacts).

Working with [`coding_agents.py`](../../src/sevn/ui/dashboard/api/coding_agents.py): inspect the public entry points below.
Start with [`coding_agents_list_payload`](../../src/sevn/ui/dashboard/api/coding_agents.py#L62), then [`coding_agents_list`](../../src/sevn/ui/dashboard/api/coding_agents.py#L84), [`coding_agents_put`](../../src/sevn/ui/dashboard/api/coding_agents.py#L107), [`coding_agents_artifacts_list`](../../src/sevn/ui/dashboard/api/coding_agents.py#L150).

54 more Python files under [`src/sevn/ui`](../../src/sevn/ui/) — including `src/sevn/ui/dashboard/api/deps.py`, `src/sevn/ui/dashboard/api/evolution.py`, `src/sevn/ui/dashboard/api/files.py`, `src/sevn/ui/dashboard/api/knowledge.py`.

### Extension and invariants

Follow [`24-dashboard.md`](../../about-sevn.bot/specs/24-dashboard.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/ui`](../../src/sevn/ui/), run `sevn readme update ui-mission-control` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/24-dashboard.md](../../about-sevn.bot/specs/24-dashboard.md)
- [../../about-sevn.bot/specs/29-openui.md](../../about-sevn.bot/specs/29-openui.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/24-dashboard.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/ui/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
