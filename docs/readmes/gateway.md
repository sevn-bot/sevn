<!-- generated: do not edit by hand; run `sevn readme update gateway` -->
# Gateway — FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus.

## Level 1 — Overview (non-technical)

**Gateway** is a core part of sevn.bot — the personal AI assistant you run on your own machine. FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus.

In everyday use, gateway helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/gateway/`. The package contains 114 Python module(s); primary entry points include `src/sevn/gateway/__init__.py`, `src/sevn/gateway/admin_secrets.py`, `src/sevn/gateway/agent_turn.py`, `src/sevn/gateway/auth.py`, `src/sevn/gateway/boot.py`, `src/sevn/gateway/boot_registry.py`, and 108 more.

### Data and control flow

Gateway sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/17-gateway.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/gateway/admin_secrets.py` — `register_admin_secrets_routes`
- `src/sevn/gateway/agent_turn.py` — `build_intro_extra_instructions`, `build_agent_run_turn`
- `src/sevn/gateway/auth.py` — `extract_bearer`, `secrets_compare`, `verify_login_gateway_token`, `login_page_html`
- `src/sevn/gateway/boot.py` — `run_harness_boot_sweep`, `run_workspace_layout_validation`
- `src/sevn/gateway/boot_registry.py` — `register_boot_hook`, `register_cron_job`, `clear_boot_registry`, `run_boot_hooks`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/gateway/` (114 Python files). Normative design: `about-sevn.bot/specs/17-gateway.md`.

### Module inventory

- `src/sevn/gateway/__init__.py` — HTTP gateway and session handling ('about-sevn.bot/specs/17-gateway.md').
- `src/sevn/gateway/admin_secrets.py` — Gateway-delegated operator secrets API ('about-sevn.bot/specs/23-cli.md' §8, 'about-sevn.bot/specs/06-secrets.md').
- `src/sevn/gateway/agent_turn.py` — Production agent dispatch glue ('about-sevn.bot/specs/17-gateway.md' §2.6).
- `src/sevn/gateway/auth.py` — Gateway bearer + Telegram secret + Web UI JWT helpers
('about-sevn.bot/specs/17-gateway.md' §2.1, §6; 'about-sevn.bot/specs/19-channel-webui.md' §2.3-§2.5).
- `src/sevn/gateway/boot.py` — Gateway boot integration for harness discipline ('about-sevn.bot/specs/16-harness-discipline.md' §2.2).
- `src/sevn/gateway/boot_registry.py` — Gateway boot and cron reconcile hook registry (CW-2).
- `src/sevn/gateway/bootstrap_capture.py` — Deterministic USER.md fallback after bootstrap tier-B ('the design docs' Wave 3).
- `src/sevn/gateway/bootstrap_state.py` — USER.md bootstrap completion helpers without onboarding seed imports.
- `src/sevn/gateway/browser_lifecycle.py` — Gateway browser teardown hooks without static ''sevn.skills'' imports.
- `src/sevn/gateway/cascade_budget.py` — Cumulative wall-clock budget for the tier B → C/D cascade ('about-sevn.bot/specs/17-gateway.md' §3.4).
- `src/sevn/gateway/channel_boot.py` — Multi-adapter gateway boot loader.
- `src/sevn/gateway/channel_router.py` — Unified inbound/outbound orchestration ('about-sevn.bot/specs/17-gateway.md' §2.2-§2.4, §4.3-§4.4).
- … and 102 more Python modules

### Package init (`src/sevn/gateway/__init__.py`)

See `src/sevn/gateway/__init__.py` for implementation details.

### Admin Secrets (`src/sevn/gateway/admin_secrets.py`)

Public entry points:
- `register_admin_secrets_routes`

### Agent Turn (`src/sevn/gateway/agent_turn.py`)

Public entry points:
- `build_intro_extra_instructions`
- `build_agent_run_turn`

### Auth (`src/sevn/gateway/auth.py`)

Public entry points:
- `extract_bearer`
- `secrets_compare`
- `verify_login_gateway_token`
- `login_page_html`
- `verify_gateway_bearer`
- `verify_telegram_secret`
- `mint_webchat_jwt`
- `verify_webchat_jwt`

### Boot (`src/sevn/gateway/boot.py`)

Public entry points:
- `run_harness_boot_sweep`
- `run_workspace_layout_validation`

### Boot Registry (`src/sevn/gateway/boot_registry.py`)

Public entry points:
- `register_boot_hook`
- `register_cron_job`
- `clear_boot_registry`
- `run_boot_hooks`
- `run_cron_reconciles`

### Bootstrap Capture (`src/sevn/gateway/bootstrap_capture.py`)

Public entry points:
- `extract_bootstrap_name`
- `try_bootstrap_user_md_fallback`

### Bootstrap State (`src/sevn/gateway/bootstrap_state.py`)

Public entry points:
- `operator_name_from_user_md`
- `bootstrap_completion_state`

### Browser Lifecycle (`src/sevn/gateway/browser_lifecycle.py`)

Public entry points:
- `close_browser_for_rotate`

### Cascade Budget (`src/sevn/gateway/cascade_budget.py`)

Public entry points:
- `CascadeBudget.remaining_s`
- `CascadeBudget.exhausted`
- `CascadeBudget.clamp`

### Channel Boot (`src/sevn/gateway/channel_boot.py`)

See `src/sevn/gateway/channel_boot.py` for implementation details.

### Channel Router (`src/sevn/gateway/channel_router.py`)

See `src/sevn/gateway/channel_router.py` for implementation details.

### Additional modules

102 more Python files under `src/sevn/gateway/` — including `src/sevn/gateway/channel_types.py`, `src/sevn/gateway/coding_agent_router.py`, `src/sevn/gateway/commands/__init__.py`, `src/sevn/gateway/commands/ask_config.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/17-gateway.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/gateway/`, run `sevn readme update gateway` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/17-gateway.md](../../about-sevn.bot/specs/17-gateway.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/17-gateway.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/gateway/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
