<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint gateway` -->
# Gateway — FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus.

## Level 1 — Overview (non-technical)

**Gateway** is the long-running **control plane** you start with `sevn gateway start` (or the installed daemon). Every channel — Telegram, Web UI, voice hooks — connects here. The gateway owns sessions, queues your messages, runs the security scanner, and dispatches work to the agent stack. Provider API keys never load in this process; outbound LLM traffic goes through the paired **egress proxy**.

In everyday terms: you send a message on Telegram; the gateway receives it, checks it, remembers the conversation, picks the right executor tier, and sends the reply back on the same channel.

## Level 2 — How it works (technical)

The gateway is a **FastAPI** app under `src/sevn/gateway/`. The inbound path is centered on `ChannelRouter` (`channel_router.py`).

### Turn spine

1. **Inbound** — A channel adapter delivers a normalized message to `ChannelRouter.route_inbound`.
2. **Scan** — `LLMGuardScanner.scan_inbound` runs before triage (unless owner override skips the guard).
3. **Session** — Message persisted to SQLite (`sessions` store); blocked content gets a `kind="blocked"` row instead.
4. **Dispatch** — `build_agent_run_turn` (`agent_turn.py`) returns the production `RunTurnFn`: `triage_turn` → tier **A** (triager-only reply), **B** (`run_b_turn`), or **C/D** (`run_cd_turn`).
5. **Outbound** — Assistant text streams back through the same channel adapter; trace events land in `.sevn/traces` / `traces.db`.

### Queue and steer modes

`gateway.queue_mode` in `sevn.json` controls behavior when a session is already busy:

| Mode | Behavior |
| --- | --- |
| `cancel` (default) | New inbound cancels the in-flight turn |
| `steer` | Owner `/steer <text>` queues corrections at the next safe LLM boundary (`steer_store.py`) |
| `multi` | Triager classifies busy input as steer, supersede, or a new level-1 task (`queue_multi.py`) |

Per-channel overrides exist via `channels.*.busy_input_mode`.

### Channels and boot

`channel_boot.py` loads configured adapters (Telegram, Web UI, Discord, Slack, stubs). `run_boot_hooks` (`boot_registry.py`) runs harness discipline sweeps, layout validation, cron reconciles, and subsystem registration at startup.

### Configuration (`sevn.json` → `gateway`)

Key knobs (full schema: [`infra/sevn.schema.json`](../../infra/sevn.schema.json)):

- `queue_mode` — `cancel` \| `steer` \| `multi`
- `steer.max_pending` — bounded `/steer` queue per session
- `budget.*` — cascade wall-clock budget for tier B → C/D (`cascade_budget.py`)
- `first_session_intro`, `session_mirror`, `restart` — UX and lifecycle helpers

Validate after edits: `sevn config validate`; `sevn doctor` for install health.

### Key modules

- `src/sevn/gateway/agent_turn.py` — `build_agent_run_turn`, production turn dispatch glue
- `src/sevn/gateway/channel_router.py` — inbound/outbound orchestration, LLM Guard gate
- `src/sevn/gateway/channel_boot.py` — multi-adapter boot loader
- `src/sevn/gateway/steer_store.py` — session-scoped `/steer` buffer
- `src/sevn/gateway/queue_multi.py` — `multi` queue-mode classification
- `src/sevn/gateway/boot.py` — harness boot sweep + workspace layout validation

Normative spec: [`about-sevn.bot/specs/17-gateway.md`](../../about-sevn.bot/specs/17-gateway.md).

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
