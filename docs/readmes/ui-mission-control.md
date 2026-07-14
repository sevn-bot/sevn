<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint ui-mission-control` -->
# Mission Control UI — Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery.

## Level 1 — Overview (non-technical)

**Mission Control** is the browser dashboard at `/mission/*` on the gateway. It gives you traces, sessions, config editors, secrets reveal, self-improve jobs, evolution pipelines, and more — **46 tabs** grouped into **8 sidebar sections**. The UI is a vanilla JS SPA under `src/sevn/ui/spa/dashboard/`; Python registers REST + WebSocket routes on the same FastAPI app as Telegram/Web UI.

**OpenUI** (Canvas tab) lets agents publish sanitized HTML/PNG/PDF surfaces via the `openui_render` tool — delivery modes include live URL, rasterized PNG, and PDF.

## Level 2 — How it works (technical)

### SPA shell

Static assets: [`src/sevn/ui/spa/dashboard/`](../../src/sevn/ui/spa/dashboard/) (`app.js`, tab panels). Mounted by the gateway HTTP server at `/mission/{slug}`. Shared design tokens at `/style/*`.

### Tab registry

[`tab_registry.py`](../../src/sevn/ui/dashboard/tab_registry.py) is the SSOT for sidebar structure:

- [`DASHBOARD_GROUPS`](../../src/sevn/ui/dashboard/tab_registry.py#L17) — 8 groups × 46 tab labels
- [`WIRED_SLUGS`](../../src/sevn/ui/dashboard/tab_registry.py#L156) — tabs with live REST backing (vs stub/post-v1 placeholders)
- [`build_nav_payload`](../../src/sevn/ui/dashboard/tab_registry.py#L210) — JSON for `GET /api/v1/dashboard/nav` ([`nav.py`](../../src/sevn/ui/dashboard/api/nav.py))
- [`registry_tab_slug`](../../src/sevn/ui/dashboard/tab_registry.py#L117) — canonical `/mission/{slug}` paths (e.g. `canvas-openui`, `rlm-training`)

Sample wired slugs: `overview`, `chat`, `canvas-openui`, `traces`, `secrets`, `egress-proxy`, `jobs`, `spec-kit`.

### Route wiring

[`register_dashboard_routes`](../../src/sevn/ui/dashboard/__init__.py#L24) on the gateway FastAPI app:

1. Installs [`create_dashboard_api_router`](../../src/sevn/ui/dashboard/api/__init__.py#L43) at `/api/v1`
2. WebSocket hubs: `/ws/dashboard`, terminal WS
3. Auth service on `app.state.dashboard_auth`

Individual tab routers live under [`src/sevn/ui/dashboard/api/`](../../src/sevn/ui/dashboard/api/) (ops, traces, secrets, evolution, …).

### OpenUI delivery matrix

| Surface | Module | Delivery |
| --- | --- | --- |
| Agent tool | [`openui_render`](../../src/sevn/ui/openui/tools_register.py#L63) via [`register_openui_tools`](../../src/sevn/ui/openui/tools_register.py) | Live URL / PNG / PDF metadata in tool result |
| Bridge | [`OpenUIBridge`](../../src/sevn/ui/openui/bridge.py) | Sanitize + publish HTML |
| MC Canvas tab | [`dashboard_canvas`](../../src/sevn/ui/dashboard/api/canvas.py) | Owner view of published surfaces |
| Store | [`OpenUIStore`](../../src/sevn/ui/openui/store.py) | Token + artifact persistence (`openui_tokens` table) |

Spec: [`37-openui.md`](../../about-sevn.bot/specs/37-openui.md).

### Configuration (`sevn.json` → `dashboard`)

- `login_password`, `jwt_secret` — owner auth ([`DashboardAuthService`](../../src/sevn/ui/dashboard/services/auth.py)); `${SECRET:…}` refs resolved at boot
- `enabled`, bind/port via gateway HTTP server

Validate: `sevn config validate`.

### Key modules

- [`tab_registry.py`](../../src/sevn/ui/dashboard/tab_registry.py) — nav SSOT, [`build_nav_payload`](../../src/sevn/ui/dashboard/tab_registry.py#L210)
- [`__init__.py`](../../src/sevn/ui/dashboard/__init__.py) — [`register_dashboard_routes`](../../src/sevn/ui/dashboard/__init__.py#L24)
- [`api/__init__.py`](../../src/sevn/ui/dashboard/api/__init__.py) — [`create_dashboard_api_router`](../../src/sevn/ui/dashboard/api/__init__.py#L43)
- [`openui/tools_register.py`](../../src/sevn/ui/openui/tools_register.py) — agent-facing OpenUI tool

Normative specs: [`24-dashboard.md`](../../about-sevn.bot/specs/24-dashboard.md), [`37-openui.md`](../../about-sevn.bot/specs/37-openui.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/ui`](../../src/sevn/ui/) (66 Python files). Normative design: `about-sevn.bot/specs/24-dashboard.md`, `about-sevn.bot/specs/37-openui.md`.

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
- [../../about-sevn.bot/specs/37-openui.md](../../about-sevn.bot/specs/37-openui.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/24-dashboard.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/ui/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
