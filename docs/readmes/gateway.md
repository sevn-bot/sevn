<!-- generated: do not edit by hand; run `sevn readme update gateway` -->
# Gateway — FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus.

## Level 1 — Overview (non-technical)

**Gateway** is a core part of sevn.bot — the personal AI assistant you run on your own machine. FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus.

In everyday use, gateway helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Run the long-lived gateway process that accepts channel ingress (Telegram poll/webhook, webchat WS), normalises messages, enforces trust boundaries (scanner, rate limits), persists session history, an

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/gateway/`. The package contains 110 Python module(s); primary entry points include `src/sevn/gateway/__init__.py`, `src/sevn/gateway/admin_secrets.py`, `src/sevn/gateway/agent_turn.py`, `src/sevn/gateway/auth.py`, and 2 more.

### Data and control flow

Gateway sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/17-gateway.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/gateway/admin_secrets.py` — `register_admin_secrets_routes`
- `src/sevn/gateway/agent_turn.py` — `build_intro_extra_instructions`, `build_agent_run_turn`
- `src/sevn/gateway/auth.py` — `extract_bearer`, `secrets_compare`, `verify_login_gateway_token`, `login_page_html`
- `src/sevn/gateway/boot.py` — `run_harness_boot_sweep`, `run_workspace_layout_validation`
- `src/sevn/gateway/boot_registry.py` — `register_boot_hook`, `register_cron_job`, `clear_boot_registry`, `run_boot_hooks`

### Spec context

From specs/17-gateway.md:
Run the long-lived gateway process that accepts channel ingress (Telegram poll/webhook, webchat WS), normalises messages, enforces trust boundaries (scanner, rate limits), persists session history, an

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/gateway/` (110 Python files). Normative design: `specs/17-gateway.md`.

### Module inventory

- `src/sevn/gateway/__init__.py` — """HTTP gateway and session handling ('specs/17-gateway.md').
- `src/sevn/gateway/admin_secrets.py` — """Gateway-delegated operator secrets API ('specs/23-cli.md' §8, 'specs/06-secrets.md').
- `src/sevn/gateway/agent_turn.py` — """Production agent dispatch glue ('specs/17-gateway.md' §2.6).
- `src/sevn/gateway/auth.py` — """Gateway bearer + Telegram secret + Web UI JWT helpers
- `src/sevn/gateway/boot.py` — """Gateway boot integration for harness discipline ('specs/16-harness-discipline.md' §2.2).
- `src/sevn/gateway/boot_registry.py` — """Gateway boot and cron reconcile hook registry (CW-2).
- `src/sevn/gateway/bootstrap_capture.py` — """Deterministic USER.md fallback after bootstrap tier-B ('plan/operator-experience-wave-plan.md' Wave 3).
- `src/sevn/gateway/bootstrap_state.py` — """USER.md bootstrap completion helpers without onboarding seed imports.
- `src/sevn/gateway/browser_lifecycle.py` — """Gateway browser teardown hooks without static ''sevn.skills'' imports.
- `src/sevn/gateway/cascade_budget.py` — """Cumulative wall-clock budget for the tier B → C/D cascade ('specs/17-gateway.md' §3.4).
- `src/sevn/gateway/channel_boot.py` — """Multi-adapter gateway boot loader.
- `src/sevn/gateway/channel_router.py` — """Unified inbound/outbound orchestration ('specs/17-gateway.md' §2.2-§2.4, §4.3-§4.4).
- … and 98 more Python modules

### Admin Secrets (`src/sevn/gateway/admin_secrets.py`)

Public entry points:
- `register_admin_secrets_routes` — see `src/sevn/gateway/admin_secrets.py`

### Agent Turn (`src/sevn/gateway/agent_turn.py`)

Public entry points:
- `build_intro_extra_instructions` — see `src/sevn/gateway/agent_turn.py`
- `build_agent_run_turn` — see `src/sevn/gateway/agent_turn.py`

### Auth (`src/sevn/gateway/auth.py`)

Public entry points:
- `extract_bearer` — see `src/sevn/gateway/auth.py`
- `secrets_compare` — see `src/sevn/gateway/auth.py`
- `verify_login_gateway_token` — see `src/sevn/gateway/auth.py`
- `login_page_html` — see `src/sevn/gateway/auth.py`
- `verify_gateway_bearer` — see `src/sevn/gateway/auth.py`
- `verify_telegram_secret` — see `src/sevn/gateway/auth.py`
- `mint_webchat_jwt` — see `src/sevn/gateway/auth.py`
- `verify_webchat_jwt` — see `src/sevn/gateway/auth.py`

### Boot (`src/sevn/gateway/boot.py`)

Public entry points:
- `run_harness_boot_sweep` — see `src/sevn/gateway/boot.py`
- `run_workspace_layout_validation` — see `src/sevn/gateway/boot.py`

### Boot Registry (`src/sevn/gateway/boot_registry.py`)

Public entry points:
- `register_boot_hook` — see `src/sevn/gateway/boot_registry.py`
- `register_cron_job` — see `src/sevn/gateway/boot_registry.py`
- `clear_boot_registry` — see `src/sevn/gateway/boot_registry.py`
- `run_boot_hooks` — see `src/sevn/gateway/boot_registry.py`
- `run_cron_reconciles` — see `src/sevn/gateway/boot_registry.py`

### Bootstrap Capture (`src/sevn/gateway/bootstrap_capture.py`)

Public entry points:
- `extract_bootstrap_name` — see `src/sevn/gateway/bootstrap_capture.py`
- `try_bootstrap_user_md_fallback` — see `src/sevn/gateway/bootstrap_capture.py`

### Bootstrap State (`src/sevn/gateway/bootstrap_state.py`)

Public entry points:
- `operator_name_from_user_md` — see `src/sevn/gateway/bootstrap_state.py`
- `bootstrap_completion_state` — see `src/sevn/gateway/bootstrap_state.py`

### Browser Lifecycle (`src/sevn/gateway/browser_lifecycle.py`)

Public entry points:
- `close_browser_for_rotate` — see `src/sevn/gateway/browser_lifecycle.py`

### Cascade Budget (`src/sevn/gateway/cascade_budget.py`)

Public entry points:
- `CascadeBudget.remaining_s` — see `src/sevn/gateway/cascade_budget.py`
- `CascadeBudget.exhausted` — see `src/sevn/gateway/cascade_budget.py`
- `CascadeBudget.clamp` — see `src/sevn/gateway/cascade_budget.py`

### Additional modules

98 more Python files under `src/sevn/gateway/` — including `src/sevn/gateway/channel_types.py`, `src/sevn/gateway/coding_agent_router.py`, `src/sevn/gateway/commands/__init__.py`, `src/sevn/gateway/commands/ask_config.py`.

### Extension and invariants

Follow `specs/17-gateway.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/gateway/`, run `sevn readme update gateway` and `make readme-check`.

## References

- [specs/17-gateway.md](specs/17-gateway.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/17-gateway.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/gateway/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
