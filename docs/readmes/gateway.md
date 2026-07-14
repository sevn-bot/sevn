<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint gateway` -->
# Gateway — FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus.

## Level 1 — Overview (non-technical)

**Gateway** is the always-on program that runs Sevn on your machine. You start it with `sevn gateway start` (or install it as a background service). Every way you talk to Sevn — Telegram, the browser chat, voice — connects through the gateway first.

Think of it as the front desk: it receives your message, checks it for safety, remembers the conversation, decides how much "thinking power" the task needs, and sends the answer back on the same channel you used. Your AI provider keys never live inside this process; outbound model calls go through a separate **egress proxy** so secrets stay isolated.

When you send "What's on my calendar?" on Telegram, the gateway picks it up, runs the safety scan, keeps the chat history, routes the work to the right agent tier, and delivers the reply — without you managing any of those steps manually.

## Level 2 — How it works (technical)

The gateway is a long-running web service built with [FastAPI](https://github.com/tiangolo/fastapi) under [`src/sevn/gateway/`](../../src/sevn/gateway/). FastAPI gives the process HTTP endpoints for webhooks, the browser chat, Mission Control APIs, and health checks while the core conversation loop runs asynchronously. The inbound path centers on [`ChannelRouter`](../../src/sevn/gateway/channel_router.py#L391), which normalises channel-specific events into one internal message shape before any agent work begins.

### Turn spine

Every user message follows the same five-step path — the **turn spine** — regardless of channel:

1. **Inbound** — A channel adapter (Telegram, Web UI, voice, etc.) delivers a normalised message to [`ChannelRouter.route_incoming`](../../src/sevn/gateway/channel_router.py#L1348). Adapters hide platform quirks; the router sees a uniform event.
2. **Scan** — In [`llm_guard_scanner.py`](../../src/sevn/security/llm_guard_scanner.py), [`LLMGuardScanner.scan_inbound`](../../src/sevn/security/llm_guard_scanner.py#L564) inspects content before triage. Blocked input is stored as a `kind="blocked"` session row instead of reaching the agent stack (owner override can skip the guard when configured).
3. **Session** — The message is persisted to SQLite via the sessions store so history, diagnostics, and Mission Control views stay consistent across restarts.
4. **Dispatch** — [`build_agent_run_turn`](../../src/sevn/gateway/agent_turn.py#L702) returns the production `RunTurnFn` closure. It calls [`triage_turn`](../../src/sevn/agent/triager/run.py#L1171) and then routes to tier **A** (triager-only reply), **B** ([`run_b_turn`](../../src/sevn/agent/executors/b_harness.py#L924) — everyday tool use), or **C/D** ([`run_cd_turn`](../../src/sevn/agent/executors/cd_harness.py#L888) — multi-step planning).
5. **Outbound** — Assistant text streams back through the same channel adapter. Trace events land under `.sevn/traces` and in `traces.db` for inspection in Mission Control.

Provider API calls are brokered by the egress proxy — keys never load in the gateway process.

### Queue and steer modes

When a session is already processing a turn, `gateway.queue_mode` in `sevn.json` decides what happens to new input:

| Mode | Behavior |
| --- | --- |
| `cancel` (default) | A new inbound message cancels the in-flight turn so the latest message wins |
| `steer` | Owner `/steer <text>` queues corrections in [`steer_store.py`](../../src/sevn/gateway/steer_store.py); they apply at the next safe LLM boundary without aborting the whole turn |
| `multi` | The triager classifies busy input as steer, supersede, or a new level-1 task via [`queue_multi.py`](../../src/sevn/gateway/queue_multi.py) — useful when sub-agents run in parallel |

Per-channel overrides are available through `channels.*.busy_input_mode` when Telegram and Web UI need different behaviour.

### Channels and boot

At startup, [`channel_boot.py`](../../src/sevn/gateway/channel_boot.py) loads configured adapters (Telegram, Web UI, Discord, Slack, stubs) and registers their webhook or polling loops. [`run_boot_hooks`](../../src/sevn/gateway/boot_registry.py#L123) in [`boot_registry.py`](../../src/sevn/gateway/boot_registry.py) runs harness-discipline sweeps, workspace layout validation, cron reconciles, and subsystem registration so every package wires itself in without a central import list.

The HTTP server itself is assembled in [`http_server.py`](../../src/sevn/gateway/http_server.py); authentication helpers in [`auth.py`](../../src/sevn/gateway/auth.py) enforce bearer tokens, Telegram webhook secrets, and Web UI JWT cookies on protected routes.

### Telegram menus and slash commands

Telegram `/config` menus, inline keyboards, and slash commands are gateway-owned. [`menu.py`](../../src/sevn/gateway/menu.py) and [`menu_registry.py`](../../src/sevn/gateway/menu_registry.py) build the operator menu tree; the [`commands/`](../../src/sevn/gateway/commands/) subpackage dispatches `/steer`, diagnostics, evolution, self-improve, and config actions through [`commands/dispatcher.py`](../../src/sevn/gateway/commands/dispatcher.py). After menu changes, run `make telegram-menu-docs-check`.

### Configuration (`sevn.json` → `gateway`)

Key knobs (full schema: [`infra/sevn.schema.json`](../../infra/sevn.schema.json)):

- `queue_mode` — `cancel` \| `steer` \| `multi`
- `steer.max_pending` — bounded `/steer` queue depth per session
- `budget.*` — per-turn executor ceilings via [`gateway.py`](../../src/sevn/config/sections/gateway.py) ([`GatewayBudgetConfig`](../../src/sevn/config/sections/gateway.py#L155)): `tier_b_rounds`, `tier_b_rounds_expanded`, `count_planning`, per-slot `*_max_output_tokens` (triager, tier B/C/D, guard, LCM, dreaming, user model), `tier_b_executor_timeout_s`, `tier_cd_executor_timeout_s`, and cumulative `cascade_budget_s` enforced by [`cascade_budget.py`](../../src/sevn/gateway/cascade_budget.py)
- `first_session_intro`, `session_mirror`, `restart` — first-chat UX, cross-channel session mirroring, and graceful restart acknowledgement

Validate after edits: `sevn config validate`; `sevn doctor` for install health.

### Key modules

- [`agent_turn.py`](../../src/sevn/gateway/agent_turn.py) — [`build_agent_run_turn`](../../src/sevn/gateway/agent_turn.py#L702): production turn dispatch glue from triage through tier B/C/D
- [`channel_router.py`](../../src/sevn/gateway/channel_router.py) — [`route_incoming`](../../src/sevn/gateway/channel_router.py#L1348): inbound/outbound orchestration, LLM Guard gate, session enqueue
- [`channel_boot.py`](../../src/sevn/gateway/channel_boot.py) — multi-adapter boot loader and webhook registration
- [`session_manager.py`](../../src/sevn/gateway/session_manager.py) — SQLite session persistence, turn queue, and busy-session detection
- [`steer_store.py`](../../src/sevn/gateway/steer_store.py) — session-scoped `/steer` buffer for `steer` queue mode
- [`queue_multi.py`](../../src/sevn/gateway/queue_multi.py) — `multi` queue-mode triager classification
- [`boot.py`](../../src/sevn/gateway/boot.py) — harness boot sweep + workspace layout validation
- [`mission_api.py`](../../src/sevn/gateway/mission_api.py) — Mission Control REST/WebSocket surfaces

Normative spec: [`about-sevn.bot/specs/17-gateway.md`](../../about-sevn.bot/specs/17-gateway.md). Related: [Channels README](channels.md), [Agent runtime README](agent.md), [Security README](security.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/gateway`](../../src/sevn/gateway/) (114 Python files). Normative design: [`17-gateway.md`](../../about-sevn.bot/specs/17-gateway.md).

### Module inventory

HTTP gateway and session handling (about-sevn.bot/specs/17-gateway.md).

Working with [`__init__.py`](../../src/sevn/gateway/__init__.py): inspect the public entry points below.

Gateway-delegated operator secrets API (about-sevn.bot/specs/23-cli.md §8, about-sevn.bot/specs/06-secrets.md).

CLI sevn secrets calls these routes with SEVN_GATEWAY_TOKEN; the gateway
mutates the workspace encrypted store — not a direct proxy admin path
(about-sevn.bot/specs/07-egress-proxy.md).

Working with [`admin_secrets.py`](../../src/sevn/gateway/admin_secrets.py): inspect the public entry points below.
Start with [`register_admin_secrets_routes`](../../src/sevn/gateway/admin_secrets.py#L121).

Production agent dispatch glue (about-sevn.bot/specs/17-gateway.md §2.6).

Working with [`agent_turn.py`](../../src/sevn/gateway/agent_turn.py): inspect the public entry points below.
Start with [`build_intro_extra_instructions`](../../src/sevn/gateway/agent_turn.py#L607), then [`build_agent_run_turn`](../../src/sevn/gateway/agent_turn.py#L702).

Gateway bearer + Telegram secret + Web UI JWT helpers
(about-sevn.bot/specs/17-gateway.md §2.1, §6; about-sevn.bot/specs/19-channel-webui.md §2.3-§2.5).

Working with [`auth.py`](../../src/sevn/gateway/auth.py): inspect the public entry points below.
Start with [`extract_bearer`](../../src/sevn/gateway/auth.py#L91), then [`secrets_compare`](../../src/sevn/gateway/auth.py#L115), [`verify_login_gateway_token`](../../src/sevn/gateway/auth.py#L137), [`login_page_html`](../../src/sevn/gateway/auth.py#L168).

Gateway boot integration for harness discipline (about-sevn.bot/specs/16-harness-discipline.md §2.2).

Working with [`boot.py`](../../src/sevn/gateway/boot.py): inspect the public entry points below.
Start with [`run_harness_boot_sweep`](../../src/sevn/gateway/boot.py#L36), then [`run_workspace_layout_validation`](../../src/sevn/gateway/boot.py#L67).

Gateway boot and cron reconcile hook registry (CW-2).

Working with [`boot_registry.py`](../../src/sevn/gateway/boot_registry.py): inspect the public entry points below.
Start with [`register_boot_hook`](../../src/sevn/gateway/boot_registry.py#L52), then [`register_cron_job`](../../src/sevn/gateway/boot_registry.py#L76), [`clear_boot_registry`](../../src/sevn/gateway/boot_registry.py#L100), [`run_boot_hooks`](../../src/sevn/gateway/boot_registry.py#L123).

Deterministic USER.md fallback after bootstrap tier-B (the design docs Wave 3).

Working with [`bootstrap_capture.py`](../../src/sevn/gateway/bootstrap_capture.py): inspect the public entry points below.
Start with [`extract_bootstrap_name`](../../src/sevn/gateway/bootstrap_capture.py#L274), then [`try_bootstrap_user_md_fallback`](../../src/sevn/gateway/bootstrap_capture.py#L434).

USER.md bootstrap completion helpers without onboarding seed imports.

Working with [`bootstrap_state.py`](../../src/sevn/gateway/bootstrap_state.py): inspect the public entry points below.
Start with [`operator_name_from_user_md`](../../src/sevn/gateway/bootstrap_state.py#L66), then [`bootstrap_completion_state`](../../src/sevn/gateway/bootstrap_state.py#L101).

Gateway browser teardown hooks without static sevn.skills imports.

session_manager is reachable from sevn.channels; import-linter forbids a
transitive channels → skills chain. Browser close helpers therefore load
sevn.skills.browser_session via importlib.import_module at call time.

Working with [`browser_lifecycle.py`](../../src/sevn/gateway/browser_lifecycle.py): inspect the public entry points below.
Start with [`close_browser_for_rotate`](../../src/sevn/gateway/browser_lifecycle.py#L25).

Cumulative wall-clock budget for the tier B → C/D cascade (about-sevn.bot/specs/17-gateway.md §3.4).

Working with [`cascade_budget.py`](../../src/sevn/gateway/cascade_budget.py): inspect the public entry points below.
Start with [`CascadeBudget.remaining_s`](../../src/sevn/gateway/cascade_budget.py#L68), then [`CascadeBudget.exhausted`](../../src/sevn/gateway/cascade_budget.py#L87), [`CascadeBudget.clamp`](../../src/sevn/gateway/cascade_budget.py#L104).

Multi-adapter gateway boot loader.

Working with [`channel_boot.py`](../../src/sevn/gateway/channel_boot.py): inspect the public entry points below.
Start with [`register_enabled_channel_adapters`](../../src/sevn/gateway/channel_boot.py#L76), then [`register_channel_boot_hooks`](../../src/sevn/gateway/channel_boot.py#L199).

Unified inbound/outbound orchestration (about-sevn.bot/specs/17-gateway.md §2.2-§2.4, §4.3-§4.4).

Working with [`channel_router.py`](../../src/sevn/gateway/channel_router.py): inspect the public entry points below.
Start with [`ChannelRouter.platform_runtime`](../../src/sevn/gateway/channel_router.py#L523), then [`ChannelRouter.pairing_store`](../../src/sevn/gateway/channel_router.py#L537), [`ChannelRouter.adapter_names`](../../src/sevn/gateway/channel_router.py#L550), [`outbound_routing_metadata`](../../src/sevn/gateway/channel_router.py#L2309).

Leaf channel message types and adapter contract (about-sevn.bot/specs/17-gateway.md §2.2).

Working with [`channel_types.py`](../../src/sevn/gateway/channel_types.py): inspect the public entry points below.
Start with [`ChannelAdapter.name`](../../src/sevn/gateway/channel_types.py#L92), then [`ChannelAdapter.parse_webhook`](../../src/sevn/gateway/channel_types.py#L105), [`ChannelAdapter.send`](../../src/sevn/gateway/channel_types.py#L121).

Dedicated Telegram routing for bound Coding Agents (bypass Triager).

Working with [`coding_agent_router.py`](../../src/sevn/gateway/coding_agent_router.py): inspect the public entry points below.
Start with [`CodingAgentRouter.match_binding`](../../src/sevn/gateway/coding_agent_router.py#L104), then [`CodingAgentRouter.handle_operator_message`](../../src/sevn/gateway/coding_agent_router.py#L267).

Gateway-owned slash commands and callback dispatch scaffold.

Working with [`__init__.py`](../../src/sevn/gateway/commands/__init__.py): inspect the public entry points below.

Closed-vocabulary /ask-config helper (the design docs §8.8).

Working with [`ask_config.py`](../../src/sevn/gateway/commands/ask_config.py): inspect the public entry points below.
Start with [`build_ask_config_vocab`](../../src/sevn/gateway/commands/ask_config.py#L49), then [`parse_ask_config_query`](../../src/sevn/gateway/commands/ask_config.py#L70), [`format_ask_config_reply`](../../src/sevn/gateway/commands/ask_config.py#L106).

Option-B core slash command handlers (the design docs §3).

Working with [`core_commands.py`](../../src/sevn/gateway/commands/core_commands.py): inspect the public entry points below.
Start with [`CoreCommandHandler.matches_slash`](../../src/sevn/gateway/commands/core_commands.py#L98), then [`CoreCommandHandler.handle`](../../src/sevn/gateway/commands/core_commands.py#L132).

Owner-only /logs and /traces slash commands (about-sevn.bot/specs/17-gateway.md §2.9, §10.14 TE-3).

Working with [`diagnostic_commands.py`](../../src/sevn/gateway/commands/diagnostic_commands.py): inspect the public entry points below.
Start with [`DiagnosticCommandHandler.matches_slash`](../../src/sevn/gateway/commands/diagnostic_commands.py#L73), then [`DiagnosticCommandHandler.handle`](../../src/sevn/gateway/commands/diagnostic_commands.py#L103).

Gateway command / callback short-circuit (about-sevn.bot/specs/17-gateway.md §2.4).

Working with [`dispatcher.py`](../../src/sevn/gateway/commands/dispatcher.py): inspect the public entry points below.
Start with [`CommandDispatcher.callback_auth_blocked_user_toast`](../../src/sevn/gateway/commands/dispatcher.py#L62), then [`CommandDispatcher.bypass_reply_text`](../../src/sevn/gateway/commands/dispatcher.py#L72), [`CommandDispatcher.try_dispatch`](../../src/sevn/gateway/commands/dispatcher.py#L164).

Frozen dispatcher_state.kind vocabulary (about-sevn.bot/specs/17-gateway.md).

Working with [`dispatcher_kinds.py`](../../src/sevn/gateway/commands/dispatcher_kinds.py): inspect the public entry points below.

Natural-language evolution issue-fix bridge (the design docs FL-4B).

Detects phrases like "fix issue #42", "fix evolution abc-1", "implement feature xyz" from
natural-language (no slash prefix) owner messages and drives the **chat executor track**:

  1. Resolve or import the evolution issue (FL-4B.1).
  2. If plan_approval.enabled, the pipeline allocates a worktree, dispatches the plan
     via the existing PlanGate approval loop (FL-2), and blocks until the operator approves.
     On approval, run_pipeline(stage="implement", executor="chat") runs tier-B implement
     + CI + promote (FL-4B.2).
  3. If plan_approval is disabled (or the issue is already beyond the plan stage),
     run_pipeline(executor="chat") falls through immediately to implement + CI + promote.

**Layering note (FL-4B adaptation):** evolution/ must not import gateway/.
Gateway-coupled orchestration (PlanGate dispatch via _run_cd_dispatch) therefore lives
here in the bridge, NOT inside evolution/pipeline_runner.py.  pipeline_runner.py
remains gateway-free; the bridge is the sole gateway→evolution choreographer for the chat
track.

Working with [`evolution_chat_bridge.py`](../../src/sevn/gateway/commands/evolution_chat_bridge.py): inspect the public entry points below.
Start with [`EvolutionChatBridge.matches_nl`](../../src/sevn/gateway/commands/evolution_chat_bridge.py#L183), then [`EvolutionChatBridge.handle`](../../src/sevn/gateway/commands/evolution_chat_bridge.py#L212).

Owner-only evolution slash commands (about-sevn.bot/specs/35-bot-evolution.md §2.9).

Working with [`evolution_commands.py`](../../src/sevn/gateway/commands/evolution_commands.py): inspect the public entry points below.
Start with [`EvolutionCommandHandler.matches_slash`](../../src/sevn/gateway/commands/evolution_commands.py#L63), then [`EvolutionCommandHandler.handle`](../../src/sevn/gateway/commands/evolution_commands.py#L83).

Owner-only /file_issue slash command (about-sevn.bot/specs/35-bot-evolution.md §2.9).

Working with [`evolution_issue_commands.py`](../../src/sevn/gateway/commands/evolution_issue_commands.py): inspect the public entry points below.
Start with [`FileIssueCommandHandler.matches_slash`](../../src/sevn/gateway/commands/evolution_issue_commands.py#L49), then [`FileIssueCommandHandler.handle`](../../src/sevn/gateway/commands/evolution_issue_commands.py#L69).

Dispatch sf:<path> Telegram callbacks to send_file without an LLM round.

When tier-B drops a [📎 send: <path>] marker, the Telegram outbound layer
turns it into an inline button whose callback_data is sf:<path> (or a
ds: overflow token expanding to the same). Pressing the button generates a
callback_query update; this handler intercepts those callbacks at the
gateway layer (alongside menu / config / form handlers) and ships the file
directly via ChannelRouter.route_outgoing with the attachment metadata that
sevn.tools.outbound.send_file_tool already understands.

Working with [`file_link_callback_handler.py`](../../src/sevn/gateway/commands/file_link_callback_handler.py): inspect the public entry points below.
Start with [`FileLinkCallbackHandler.matches`](../../src/sevn/gateway/commands/file_link_callback_handler.py#L53), then [`FileLinkCallbackHandler.handle`](../../src/sevn/gateway/commands/file_link_callback_handler.py#L75).

Polymorphic cfg:* / shortcut action dispatch (the design docs §4.5).

Working with [`menu_action_router.py`](../../src/sevn/gateway/commands/menu_action_router.py): inspect the public entry points below.
Start with [`infer_config_section_from_callback`](../../src/sevn/gateway/commands/menu_action_router.py#L132), then [`parse_action_callback`](../../src/sevn/gateway/commands/menu_action_router.py#L202), [`MenuActionRouter.matches`](../../src/sevn/gateway/commands/menu_action_router.py#L310), [`MenuActionRouter.handle`](../../src/sevn/gateway/commands/menu_action_router.py#L339).

Execute core slash handlers from Telegram menu button contexts (TMF Wave 2).

Working with [`menu_command_invoke.py`](../../src/sevn/gateway/commands/menu_command_invoke.py): inspect the public entry points below.
Start with [`is_dashboard_pin_message`](../../src/sevn/gateway/commands/menu_command_invoke.py#L32), then [`MenuCommandInvoker.invoke`](../../src/sevn/gateway/commands/menu_command_invoke.py#L96).

Multi-step Telegram form flows for shortcuts and secrets (TMF Wave 3).

Working with [`menu_form_handler.py`](../../src/sevn/gateway/commands/menu_form_handler.py): inspect the public entry points below.
Start with [`parse_form_callback`](../../src/sevn/gateway/commands/menu_form_handler.py#L59), then [`MenuFormHandler.matches`](../../src/sevn/gateway/commands/menu_form_handler.py#L129), [`MenuFormHandler.handle`](../../src/sevn/gateway/commands/menu_form_handler.py#L166).

/platform slash command handler.

Working with [`platform_commands.py`](../../src/sevn/gateway/commands/platform_commands.py): inspect the public entry points below.
Start with [`PlatformCommandHandler.matches_slash`](../../src/sevn/gateway/commands/platform_commands.py#L30), then [`PlatformCommandHandler.handle`](../../src/sevn/gateway/commands/platform_commands.py#L48).

Command / callback registry (about-sevn.bot/specs/17-gateway.md §2.4, §4.1).

Working with [`registry.py`](../../src/sevn/gateway/commands/registry.py): inspect the public entry points below.

/rollback slash command stub (checkpoint restore not yet implemented).

Working with [`rollback.py`](../../src/sevn/gateway/commands/rollback.py): inspect the public entry points below.
Start with [`RollbackCommandHandler.matches_slash`](../../src/sevn/gateway/commands/rollback.py#L34), then [`RollbackCommandHandler.handle`](../../src/sevn/gateway/commands/rollback.py#L53).

Owner-only /improve slash command (about-sevn.bot/specs/35-bot-evolution.md §2.9).

Working with [`self_improve_commands.py`](../../src/sevn/gateway/commands/self_improve_commands.py): inspect the public entry points below.
Start with [`SelfImproveCommandHandler.matches_slash`](../../src/sevn/gateway/commands/self_improve_commands.py#L54), then [`SelfImproveCommandHandler.handle`](../../src/sevn/gateway/commands/self_improve_commands.py#L74).

Workspace shortcut CRUD for workspace/shortcuts.json.

Working with [`shortcuts_store.py`](../../src/sevn/gateway/commands/shortcuts_store.py): inspect the public entry points below.
Start with [`shortcuts_path`](../../src/sevn/gateway/commands/shortcuts_store.py#L73), then [`load_shortcuts`](../../src/sevn/gateway/commands/shortcuts_store.py#L103), [`save_shortcuts`](../../src/sevn/gateway/commands/shortcuts_store.py#L138), [`validate_shortcut_name`](../../src/sevn/gateway/commands/shortcuts_store.py#L166).

Voice transcript first-token shortcut matching (the design docs §8.6).

Working with [`voice_match.py`](../../src/sevn/gateway/commands/voice_match.py): inspect the public entry points below.
Start with [`voice_shortcut_enabled`](../../src/sevn/gateway/commands/voice_match.py#L28), then [`match_voice_shortcut`](../../src/sevn/gateway/commands/voice_match.py#L69), [`format_voice_matched_message`](../../src/sevn/gateway/commands/voice_match.py#L114), [`extract_transcript_from_user_text`](../../src/sevn/gateway/commands/voice_match.py#L131).

Pinned dashboard message publisher (the design docs §8.1).

Working with [`dashboard_pin.py`](../../src/sevn/gateway/dashboard_pin.py): inspect the public entry points below.
Start with [`dashboard_pin_topic_key`](../../src/sevn/gateway/dashboard_pin.py#L35), then [`register_dashboard_pin`](../../src/sevn/gateway/dashboard_pin.py#L55), [`lookup_dashboard_pin_message_id`](../../src/sevn/gateway/dashboard_pin.py#L85), [`unregister_dashboard_pin`](../../src/sevn/gateway/dashboard_pin.py#L115).

Persistent gateway deployment identifier (about-sevn.bot/specs/17-gateway.md §10.14 TE-1).

Working with [`deployment_id.py`](../../src/sevn/gateway/deployment_id.py): inspect the public entry points below.
Start with [`load_or_create_deployment_id`](../../src/sevn/gateway/deployment_id.py#L77).

Backend wrappers for /logs and /traces operator diagnostics.

Working with [`diagnostics.py`](../../src/sevn/gateway/diagnostics.py): inspect the public entry points below.
Start with [`tail_service_log`](../../src/sevn/gateway/diagnostics.py#L73), then [`recent_traces`](../../src/sevn/gateway/diagnostics.py#L104), [`get_span`](../../src/sevn/gateway/diagnostics.py#L148), [`format_for_telegram`](../../src/sevn/gateway/diagnostics.py#L208).

dispatcher_callbacks table maintenance (about-sevn.bot/specs/17-gateway.md §3.4).

Working with [`dispatcher_callbacks.py`](../../src/sevn/gateway/dispatcher_callbacks.py): inspect the public entry points below.
Start with [`prune_dispatcher_callbacks`](../../src/sevn/gateway/dispatcher_callbacks.py#L16).

dispatcher_state insert + expiry sweeper (about-sevn.bot/specs/17-gateway.md §3.4).

Working with [`dispatcher_state.py`](../../src/sevn/gateway/dispatcher_state.py): inspect the public entry points below.
Start with [`dispatcher_state_ttl_for_kind`](../../src/sevn/gateway/dispatcher_state.py#L26), then [`insert_dispatcher_state`](../../src/sevn/gateway/dispatcher_state.py#L47), [`sweep_expired_dispatcher_state`](../../src/sevn/gateway/dispatcher_state.py#L110).

E2E-only echo dispatch for Playwright (the design docs Wave 6).

Working with [`e2e_echo.py`](../../src/sevn/gateway/e2e_echo.py): inspect the public entry points below.
Start with [`build_echo_run_turn`](../../src/sevn/gateway/e2e_echo.py#L65).

Gateway lifecycle event hooks.

Working with [`event_hooks.py`](../../src/sevn/gateway/event_hooks.py): inspect the public entry points below.
Start with [`register_gateway_event_hook`](../../src/sevn/gateway/event_hooks.py#L45), then [`clear_gateway_event_hooks`](../../src/sevn/gateway/event_hooks.py#L71), [`emit_gateway_event`](../../src/sevn/gateway/event_hooks.py#L82).

Gateway evolution approval Telegram callbacks (about-sevn.bot/specs/35-bot-evolution.md §2.8).

Working with [`evolution_approval_gate.py`](../../src/sevn/gateway/evolution_approval_gate.py): inspect the public entry points below.
Start with [`EvolutionApprovalWaitRegistry.resolve`](../../src/sevn/gateway/evolution_approval_gate.py#L55), then [`build_evolution_approval_inline_keyboard`](../../src/sevn/gateway/evolution_approval_gate.py#L78), [`parse_evolution_callback_data`](../../src/sevn/gateway/evolution_approval_gate.py#L103), [`EvolutionApprovalCallbackHandler.matches`](../../src/sevn/gateway/evolution_approval_gate.py#L169).

Fan evolution issue transitions to Mission Control WS + Telegram (about-sevn.bot/specs/35-bot-evolution.md §2.8).

Working with [`evolution_issue_events.py`](../../src/sevn/gateway/evolution_issue_events.py): inspect the public entry points below.
Start with [`EvolutionIssueEventFanout.publish`](../../src/sevn/gateway/evolution_issue_events.py#L137).

First-session BOOTSTRAP intro state (about-sevn.bot/specs/17-gateway.md §2.6).

Working with [`first_session.py`](../../src/sevn/gateway/first_session.py): inspect the public entry points below.
Start with [`first_session_intro_enabled`](../../src/sevn/gateway/first_session.py#L77), then [`first_session_intro_max_output_tokens`](../../src/sevn/gateway/first_session.py#L94), [`intro_state_for_scope`](../../src/sevn/gateway/first_session.py#L189), [`intro_state_for_session`](../../src/sevn/gateway/first_session.py#L233).

Persist Telegram context across owner-initiated gateway/proxy restarts.

Working with [`gateway_restart_ack.py`](../../src/sevn/gateway/gateway_restart_ack.py): inspect the public entry points below.
Start with [`pending_restart_store_path`](../../src/sevn/gateway/gateway_restart_ack.py#L64), then [`restart_ack_delivered_path`](../../src/sevn/gateway/gateway_restart_ack.py#L80), [`conversation_snapshot_for_session`](../../src/sevn/gateway/gateway_restart_ack.py#L152), [`record_pending_gateway_restart`](../../src/sevn/gateway/gateway_restart_ack.py#L188).

Gateway bearer token constants, generation, and secret-ref resolution.

Working with [`gateway_token.py`](../../src/sevn/gateway/gateway_token.py): inspect the public entry points below.
Start with [`generate_gateway_token`](../../src/sevn/gateway/gateway_token.py#L57), then [`validate_gateway_token_plaintext`](../../src/sevn/gateway/gateway_token.py#L73), [`resolve_config_ref`](../../src/sevn/gateway/gateway_token.py#L197), [`resolve_gateway_token_ref`](../../src/sevn/gateway/gateway_token.py#L286).

Reverse-proxy noVNC behind the gateway when SEVN_NOVNC_UPSTREAM is set.

HTTP assets and the viewer HTML are served under /gui; WebSocket VNC traffic
is proxied at /gui/websockify. Browsers authenticate via ?token= (or a
session cookie minted from it); API clients may use Authorization: Bearer.
Port 6080 stays container-internal.

Working with [`gui_proxy.py`](../../src/sevn/gateway/gui_proxy.py): inspect the public entry points below.
Start with [`mount_gui_proxy`](../../src/sevn/gateway/gui_proxy.py#L319).

FastAPI gateway surface (about-sevn.bot/specs/17-gateway.md §2.1, §4.2).

Working with [`http_server.py`](../../src/sevn/gateway/http_server.py): inspect the public entry points below.
Start with [`deferred_json`](../../src/sevn/gateway/http_server.py#L955), then [`create_app`](../../src/sevn/gateway/http_server.py#L980).

Gateway → LCM ingest glue (about-sevn.bot/specs/17-gateway.md §2.6 Wave 8).

Working with [`lcm_ingest.py`](../../src/sevn/gateway/lcm_ingest.py): inspect the public entry points below.
Start with [`ingest_gateway_message_row`](../../src/sevn/gateway/lcm_ingest.py#L25).

Signed media paths + DB index (about-sevn.bot/specs/17-gateway.md §3.3).

Working with [`media_store.py`](../../src/sevn/gateway/media_store.py): inspect the public entry points below.
Start with [`MediaStore.channel_files_dir`](../../src/sevn/gateway/media_store.py#L42), then [`MediaStore.persist_attachment_descriptors`](../../src/sevn/gateway/media_store.py#L59), [`MediaStore.register_token`](../../src/sevn/gateway/media_store.py#L109).

Telegram /menu inline keyboard builder (about-sevn.bot/specs/18-channel-telegram.md §4).

Working with [`menu.py`](../../src/sevn/gateway/menu.py): inspect the public entry points below.
Start with [`config_menu_nav_key`](../../src/sevn/gateway/menu.py#L195), then [`get_config_menu_nav`](../../src/sevn/gateway/menu.py#L212), [`config_menu_nav_go`](../../src/sevn/gateway/menu.py#L240), [`config_menu_nav_push_current`](../../src/sevn/gateway/menu.py#L272).

Branding helpers for Telegram /config tiles (styles/sevn/style/logos).

Working with [`menu_branding.py`](../../src/sevn/gateway/menu_branding.py): inspect the public entry points below.
Start with [`config_sevn_bot_section_title`](../../src/sevn/gateway/menu_branding.py#L25).

Operator readiness gating for Telegram /config buttons.

Working with [`menu_readiness.py`](../../src/sevn/gateway/menu_readiness.py): inspect the public entry points below.
Start with [`readiness_for_callback`](../../src/sevn/gateway/menu_readiness.py#L282), then [`gate_config_keyboard_rows`](../../src/sevn/gateway/menu_readiness.py#L346), [`config_section_catalog`](../../src/sevn/gateway/menu_readiness.py#L379), [`readiness_user_label`](../../src/sevn/gateway/menu_readiness.py#L401).

Declarative Telegram control-surface button inventory (the design docs).

Working with [`menu_registry.py`](../../src/sevn/gateway/menu_registry.py): inspect the public entry points below.
Start with [`match_menu_button_spec`](../../src/sevn/gateway/menu_registry.py#L1281), then [`is_nav_chrome_callback`](../../src/sevn/gateway/menu_registry.py#L1303), [`is_section_tile_callback`](../../src/sevn/gateway/menu_registry.py#L1321), [`registry_implementation_counts`](../../src/sevn/gateway/menu_registry.py#L1340).

Deprecated Mission Control recovery API under /api/v1/mission/* (MC-14).

Working with [`mission_api.py`](../../src/sevn/gateway/mission_api.py): inspect the public entry points below.
Start with [`fetch_subagents_mission_payload`](../../src/sevn/gateway/mission_api.py#L55), then [`kill_subagent_mission`](../../src/sevn/gateway/mission_api.py#L95), [`kill_all_subagents_mission`](../../src/sevn/gateway/mission_api.py#L128), [`EmptyMissionControlState.get_activity_feed`](../../src/sevn/gateway/mission_api.py#L167).

Mission Control in-process state fed by gateway trace events (about-sevn.bot/specs/24-dashboard.md).

Working with [`mission_state.py`](../../src/sevn/gateway/mission_state.py): inspect the public entry points below.
Start with [`MissionControlState.apply_trace_event`](../../src/sevn/gateway/mission_state.py#L126), then [`MissionControlState.apply_telemetry_trace_event`](../../src/sevn/gateway/mission_state.py#L247), [`MissionControlState.register_provider`](../../src/sevn/gateway/mission_state.py#L416).

Mission Control dataclasses and trace-normalization helpers.

Working with [`mission_state_models.py`](../../src/sevn/gateway/mission_state_models.py): inspect the public entry points below.
Start with [`is_channel_trace_kind`](../../src/sevn/gateway/mission_state_models.py#L60), then [`is_mission_telemetry_kind`](../../src/sevn/gateway/mission_state_models.py#L78), [`event_timestamp`](../../src/sevn/gateway/mission_state_models.py#L197), [`normalize_complexity`](../../src/sevn/gateway/mission_state_models.py#L224).

REST snapshot assembly for ~sevn.gateway.mission_state.MissionControlState.

Working with [`mission_state_snapshots.py`](../../src/sevn/gateway/mission_state_snapshots.py): inspect the public entry points below.
Start with [`MissionControlSnapshotsMixin.get_gateway_metrics`](../../src/sevn/gateway/mission_state_snapshots.py#L55), then [`MissionControlSnapshotsMixin.get_channel_status`](../../src/sevn/gateway/mission_state_snapshots.py#L95), [`MissionControlSnapshotsMixin.get_percentile_latency`](../../src/sevn/gateway/mission_state_snapshots.py#L124).

Mission Control sub-agent snapshot assembly (registry + telemetry + storage).

Working with [`mission_subagents_snapshot.py`](../../src/sevn/gateway/mission_subagents_snapshot.py): inspect the public entry points below.
Start with [`build_subagents_mission_snapshot`](../../src/sevn/gateway/mission_subagents_snapshot.py#L122).

Gateway trace subscriber that feeds ~sevn.gateway.mission_state.MissionControlState.

Working with [`mission_trace_sink.py`](../../src/sevn/gateway/mission_trace_sink.py): inspect the public entry points below.
Start with [`MissionControlTraceSink.emit`](../../src/sevn/gateway/mission_trace_sink.py#L49), then [`MissionControlTraceSink.flush`](../../src/sevn/gateway/mission_trace_sink.py#L64), [`MissionControlTraceSink.close`](../../src/sevn/gateway/mission_trace_sink.py#L73), [`create_mission_trace_sink`](../../src/sevn/gateway/mission_trace_sink.py#L83).

Mount onboarding wizard on the gateway (about-sevn.bot/specs/17-gateway.md, about-sevn.bot/specs/22-onboarding.md).

Working with [`onboarding_mount.py`](../../src/sevn/gateway/onboarding_mount.py): inspect the public entry points below.
Start with [`resolve_gateway_onboarding_token`](../../src/sevn/gateway/onboarding_mount.py#L18), then [`mount_gateway_onboarding`](../../src/sevn/gateway/onboarding_mount.py#L35).

OpenAI-compatible HTTP API mount on the sevn gateway.

Working with [`openai_compat_api.py`](../../src/sevn/gateway/openai_compat_api.py): inspect the public entry points below.
Start with [`build_openai_compat_router`](../../src/sevn/gateway/openai_compat_api.py#L94), then [`register_openai_compat_routes`](../../src/sevn/gateway/openai_compat_api.py#L221).

Boot-time retry for stuck assistant deliveries (about-sevn.bot/specs/17-gateway.md §4.4).

Working with [`outbound_sweep.py`](../../src/sevn/gateway/outbound_sweep.py): inspect the public entry points below.
Start with [`sweep_outbound_retries`](../../src/sevn/gateway/outbound_sweep.py#L25).

DM pairing store for channel access.

Working with [`pairing.py`](../../src/sevn/gateway/pairing.py): inspect the public entry points below.
Start with [`pairing_dir_for_content_root`](../../src/sevn/gateway/pairing.py#L35), then [`PairingStore.storage_dir`](../../src/sevn/gateway/pairing.py#L99), [`PairingStore.is_approved`](../../src/sevn/gateway/pairing.py#L206), [`PairingStore.list_approved`](../../src/sevn/gateway/pairing.py#L225).

Gateway PlanGate adapter + Telegram callback resume (about-sevn.bot/specs/17-gateway.md §2.6 Wave 6).

Working with [`plan_gate.py`](../../src/sevn/gateway/plan_gate.py): inspect the public entry points below.
Start with [`PlanGateWaitRegistry.register`](../../src/sevn/gateway/plan_gate.py#L55), then [`PlanGateWaitRegistry.resolve`](../../src/sevn/gateway/plan_gate.py#L74), [`PlanGateWaitRegistry.supersede_all`](../../src/sevn/gateway/plan_gate.py#L99), [`build_plan_inline_keyboard`](../../src/sevn/gateway/plan_gate.py#L116).

Per-channel runtime status, pause/resume, and circuit breaker.

Working with [`platform_runtime.py`](../../src/sevn/gateway/platform_runtime.py): inspect the public entry points below.
Start with [`PlatformRuntimeState.connection_state`](../../src/sevn/gateway/platform_runtime.py#L34), then [`PlatformRuntimeRegistry.register`](../../src/sevn/gateway/platform_runtime.py#L61), [`PlatformRuntimeRegistry.mark_connected`](../../src/sevn/gateway/platform_runtime.py#L84), [`PlatformRuntimeRegistry.pause`](../../src/sevn/gateway/platform_runtime.py#L101).

Ordered post-turn hook registry for gateway agent turns.

Working with [`post_turn_hooks.py`](../../src/sevn/gateway/post_turn_hooks.py): inspect the public entry points below.
Start with [`register_post_turn_hook`](../../src/sevn/gateway/post_turn_hooks.py#L44), then [`clear_post_turn_hooks`](../../src/sevn/gateway/post_turn_hooks.py#L68), [`run_post_turn_hooks`](../../src/sevn/gateway/post_turn_hooks.py#L79).

Prometheus text exposition for the gateway (about-sevn.bot/specs/17-gateway.md, about-sevn.bot/specs/24-dashboard.md).

Working with [`prometheus_metrics.py`](../../src/sevn/gateway/prometheus_metrics.py): inspect the public entry points below.
Start with [`render_gateway_metrics`](../../src/sevn/gateway/prometheus_metrics.py#L26).

multi queue-mode orchestration helpers (D6, about-sevn.bot/specs/36-sub-agents.md).

Working with [`queue_multi.py`](../../src/sevn/gateway/queue_multi.py): inspect the public entry points below.
Start with [`in_flight_task_summary_for_session`](../../src/sevn/gateway/queue_multi.py#L52), then [`spawn_multi_l1_via_supervisor`](../../src/sevn/gateway/queue_multi.py#L82).

Per-scope token bucket limiter (about-sevn.bot/specs/17-gateway.md §4.3 step 3).

Parallel level-1 sub-agent replies in multi queue mode each call
sevn.gateway.channel_router.ChannelRouter.route_outgoing, which
consumes one token per scope via TokenBucketLimiter.allow — the
same path as classic single-turn sends, so interleaved multi-agent footers
do not bypass rate limiting.

Working with [`rate_limit.py`](../../src/sevn/gateway/rate_limit.py): inspect the public entry points below.
Start with [`TokenBucketLimiter.allow`](../../src/sevn/gateway/rate_limit.py#L42).

Log-safe redaction helper (about-sevn.bot/specs/17-gateway.md §8).

Working with [`redact.py`](../../src/sevn/gateway/redact.py): inspect the public entry points below.
Start with [`redact_inline`](../../src/sevn/gateway/redact.py#L13).

Fan dashboard turn-replay job transitions to Mission Control WS.

Working with [`replay_job_events.py`](../../src/sevn/gateway/replay_job_events.py): inspect the public entry points below.
Start with [`replay_ws_topic`](../../src/sevn/gateway/replay_job_events.py#L62), then [`ReplayJobEventFanout.publish`](../../src/sevn/gateway/replay_job_events.py#L94).

Lookup replayable user text for dashboard turn replay.

Working with [`replay_turn_lookup.py`](../../src/sevn/gateway/replay_turn_lookup.py): inspect the public entry points below.
Start with [`lookup_user_text_for_turn`](../../src/sevn/gateway/replay_turn_lookup.py#L15).

Async dashboard turn-replay worker (about-sevn.bot/specs/16-harness-discipline.md §4.4).

Working with [`replay_worker.py`](../../src/sevn/gateway/replay_worker.py): inspect the public entry points below.
Start with [`TurnReplayWorker.schedule`](../../src/sevn/gateway/replay_worker.py#L73), then [`TurnReplayWorker.start`](../../src/sevn/gateway/replay_worker.py#L104), [`TurnReplayWorker.stop`](../../src/sevn/gateway/replay_worker.py#L119).

Gateway hook registration for dashboard turn replay (Batch D lane #5).

Working with [`replay_worker_hooks.py`](../../src/sevn/gateway/replay_worker_hooks.py): inspect the public entry points below.
Start with [`register_replay_worker_hooks`](../../src/sevn/gateway/replay_worker_hooks.py#L82).

Gateway response filtering helpers.

Working with [`response_filters.py`](../../src/sevn/gateway/response_filters.py): inspect the public entry points below.
Start with [`is_intentional_silence_response`](../../src/sevn/gateway/response_filters.py#L47), then [`is_intentional_silence_agent_result`](../../src/sevn/gateway/response_filters.py#L76).

Telegram routing footer on first outbound bubble (the design docs Wave 6).

Working with [`routing_footer.py`](../../src/sevn/gateway/routing_footer.py): inspect the public entry points below.
Start with [`telegram_show_routing_enabled`](../../src/sevn/gateway/routing_footer.py#L45), then [`format_subagent_tag`](../../src/sevn/gateway/routing_footer.py#L65), [`format_routing_footer`](../../src/sevn/gateway/routing_footer.py#L82), [`strip_model_emitted_footer`](../../src/sevn/gateway/routing_footer.py#L142).

Fan improve-job transitions to Mission Control WS + Telegram (about-sevn.bot/specs/24-dashboard.md §2.3).

Working with [`self_improve_job_events.py`](../../src/sevn/gateway/self_improve_job_events.py): inspect the public entry points below.
Start with [`resolve_owner_telegram_user_id`](../../src/sevn/gateway/self_improve_job_events.py#L57), then [`SelfImproveJobEventFanout.publish`](../../src/sevn/gateway/self_improve_job_events.py#L111).

Durable gateway sessions + message rows (about-sevn.bot/specs/17-gateway.md §2.5, §3.1).

Working with [`session_manager.py`](../../src/sevn/gateway/session_manager.py): inspect the public entry points below.
Start with [`SessionManager.connection`](../../src/sevn/gateway/session_manager.py#L220), then [`SessionManager.get_tts_mode_override`](../../src/sevn/gateway/session_manager.py#L234), [`SessionManager.set_tts_mode_override`](../../src/sevn/gateway/session_manager.py#L254), [`format_lcm_status_lines`](../../src/sevn/gateway/session_manager.py#L1099).

Append-only workspace session mirror (about-sevn.bot/specs/17-gateway.md §3.x).

Working with [`session_mirror.py`](../../src/sevn/gateway/session_mirror.py): inspect the public entry points below.
Start with [`session_mirror_enabled`](../../src/sevn/gateway/session_mirror.py#L99), then [`mark_session_superseded`](../../src/sevn/gateway/session_mirror.py#L244), [`mirror_gateway_message`](../../src/sevn/gateway/session_mirror.py#L302).

Per-channel session reset policies.

Working with [`session_reset.py`](../../src/sevn/gateway/session_reset.py): inspect the public entry points below.
Start with [`SessionResetPolicy.enabled`](../../src/sevn/gateway/session_reset.py#L31), then [`resolve_session_reset_policy`](../../src/sevn/gateway/session_reset.py#L46), [`session_should_reset`](../../src/sevn/gateway/session_reset.py#L110).

Read/write gateway session helpers for bundled skill scripts (about-sevn.bot/specs/17-gateway.md).

Working with [`sessions_query.py`](../../src/sevn/gateway/sessions_query.py): inspect the public entry points below.
Start with [`parse_session_metadata`](../../src/sevn/gateway/sessions_query.py#L58), then [`can_access_session`](../../src/sevn/gateway/sessions_query.py#L143), [`list_sessions`](../../src/sevn/gateway/sessions_query.py#L235), [`list_sessions_active_between`](../../src/sevn/gateway/sessions_query.py#L298).

Gateway shutdown helpers for third-party resource-tracker gaps.

Working with [`shutdown_cleanup.py`](../../src/sevn/gateway/shutdown_cleanup.py): inspect the public entry points below.
Start with [`release_leaked_multiprocessing_semaphores`](../../src/sevn/gateway/shutdown_cleanup.py#L72).

Per-platform slash command access control.

Working with [`slash_access.py`](../../src/sevn/gateway/slash_access.py): inspect the public entry points below.
Start with [`SlashAccessPolicy.is_admin`](../../src/sevn/gateway/slash_access.py#L56), then [`SlashAccessPolicy.can_run`](../../src/sevn/gateway/slash_access.py#L76), [`is_admin_slash_command`](../../src/sevn/gateway/slash_access.py#L102), [`canonical_slash_command`](../../src/sevn/gateway/slash_access.py#L124).

Session-scoped /steer buffer for gateway agent glue (about-sevn.bot/specs/17-gateway.md Wave 7).

Working with [`steer_store.py`](../../src/sevn/gateway/steer_store.py): inspect the public entry points below.
Start with [`SessionBoundSteerInject.pop_pending`](../../src/sevn/gateway/steer_store.py#L50), then [`SessionBoundSteerInject.inject_pending`](../../src/sevn/gateway/steer_store.py#L66), [`SessionSteerStore.from_workspace`](../../src/sevn/gateway/steer_store.py#L99), [`SessionSteerStore.enqueue`](../../src/sevn/gateway/steer_store.py#L115).

English-only gateway user-visible copy (about-sevn.bot/specs/17-gateway.md §10.6, PRD 01).

Working with [`strings.py`](../../src/sevn/gateway/strings.py): inspect the public entry points below.
Start with [`blocked_inbound_user_message`](../../src/sevn/gateway/strings.py#L47).

Level-2 sub-agent completion announce-back (D9, about-sevn.bot/specs/36-sub-agents.md).

Fire-and-forget is the default spawn mode (W3.3): the spawn_subagent tool
returns a run id immediately, and this module's hook delivers the result once
the level-2 run finishes — steer-injected into the parent session when a turn
is still in flight there, otherwise sent outbound with a short sub-agent tag.

Working with [`subagents_announce.py`](../../src/sevn/gateway/subagents_announce.py): inspect the public entry points below.
Start with [`build_announce_back_hook`](../../src/sevn/gateway/subagents_announce.py#L68).

Gateway boot hook: construct the process-wide sub-agent supervisor (D3/D4/D10).

Working with [`subagents_boot.py`](../../src/sevn/gateway/subagents_boot.py): inspect the public entry points below.
Start with [`register_subagents_boot_hook`](../../src/sevn/gateway/subagents_boot.py#L74).

Telegram inline-query router (I1 plumbing; I2 sources; I3 answer assembly).

Working with [`telegram_inline.py`](../../src/sevn/gateway/telegram_inline.py): inspect the public entry points below.
Start with [`maybe_emit_botfather_inline_warning`](../../src/sevn/gateway/telegram_inline.py#L81), then [`handle_chosen_inline_result_feedback`](../../src/sevn/gateway/telegram_inline.py#L114), [`dispatch_telegram_inline_query`](../../src/sevn/gateway/telegram_inline.py#L149), [`try_route_telegram_inline`](../../src/sevn/gateway/telegram_inline.py#L311).

Inline source (a): agent-answer rows + run_turn outbound capture (I2.1).

Working with [`telegram_inline_agent.py`](../../src/sevn/gateway/telegram_inline_agent.py): inspect the public entry points below.
Start with [`build_agent_inline_results`](../../src/sevn/gateway/telegram_inline_agent.py#L68), then [`capture_router_outbound_text`](../../src/sevn/gateway/telegram_inline_agent.py#L158), [`make_run_turn_agent_answer_fn`](../../src/sevn/gateway/telegram_inline_agent.py#L209).

Shared inline-source primitives, payload types, and result containers (I2).

Working with [`telegram_inline_base.py`](../../src/sevn/gateway/telegram_inline_base.py): inspect the public entry points below.
Start with [`inline_article_result`](../../src/sevn/gateway/telegram_inline_base.py#L118).

Inline answer-assembly helpers: offset, dedupe, paginate, content (I3.1-I3.2).

Working with [`telegram_inline_dispatch.py`](../../src/sevn/gateway/telegram_inline_dispatch.py): inspect the public entry points below.
Start with [`parse_inline_result_offset`](../../src/sevn/gateway/telegram_inline_dispatch.py#L43), then [`dedupe_inline_results`](../../src/sevn/gateway/telegram_inline_dispatch.py#L69), [`compute_inline_answer_cache_time`](../../src/sevn/gateway/telegram_inline_dispatch.py#L104), [`build_inline_input_message_content`](../../src/sevn/gateway/telegram_inline_dispatch.py#L170).

Inline source (c): printing-press CLI cards (I2; D9).

Working with [`telegram_inline_printing_press.py`](../../src/sevn/gateway/telegram_inline_printing_press.py): inspect the public entry points below.
Start with [`build_printing_press_inline_results`](../../src/sevn/gateway/telegram_inline_printing_press.py#L151).

Inline-query content-source aggregator (I2; I3 assembles answerInlineQuery).

Working with [`telegram_inline_sources.py`](../../src/sevn/gateway/telegram_inline_sources.py): inspect the public entry points below.
Start with [`inline_sources_module_ready`](../../src/sevn/gateway/telegram_inline_sources.py#L75), then [`build_second_brain_inline_results`](../../src/sevn/gateway/telegram_inline_sources.py#L88), [`build_artifacts_inline_results`](../../src/sevn/gateway/telegram_inline_sources.py#L177), [`build_all_inline_source_results`](../../src/sevn/gateway/telegram_inline_sources.py#L279).

Shared inline-query types, config, and auth helpers (I1; W6 boundary).

Working with [`telegram_inline_types.py`](../../src/sevn/gateway/telegram_inline_types.py): inspect the public entry points below.
Start with [`resolve_inline_config`](../../src/sevn/gateway/telegram_inline_types.py#L90), then [`telegram_allowed_updates`](../../src/sevn/gateway/telegram_inline_types.py#L113), [`inline_user_may_use_agent_source`](../../src/sevn/gateway/telegram_inline_types.py#L139), [`inline_source_cache_time`](../../src/sevn/gateway/telegram_inline_types.py#L175).

Telegram streaming edits + quick-action callbacks (about-sevn.bot/specs/18-channel-telegram.md §4.4-4.5).

Working with [`telegram_quick_actions.py`](../../src/sevn/gateway/telegram_quick_actions.py): inspect the public entry points below.
Start with [`build_quick_action_inline_keyboard`](../../src/sevn/gateway/telegram_quick_actions.py#L60), then [`parse_qa_callback_data`](../../src/sevn/gateway/telegram_quick_actions.py#L177), [`is_telegram_fast_callback_ack`](../../src/sevn/gateway/telegram_quick_actions.py#L233), [`telegram_fast_callback_ack_text`](../../src/sevn/gateway/telegram_quick_actions.py#L272).

Resolve Telegram bot token via env + secrets chain (about-sevn.bot/specs/06-secrets.md §2.5, §4).

Working with [`telegram_resolve.py`](../../src/sevn/gateway/telegram_resolve.py): inspect the public entry points below.
Start with [`resolve_telegram_bot_token`](../../src/sevn/gateway/telegram_resolve.py#L80).

Auto-mint Telegram webhook secret on first setup (about-sevn.bot/specs/18-channel-telegram.md).

Working with [`telegram_webhook_secret.py`](../../src/sevn/gateway/telegram_webhook_secret.py): inspect the public entry points below.
Start with [`ensure_webhook_secret_token`](../../src/sevn/gateway/telegram_webhook_secret.py#L43).

Gateway boot hooks for provider/channel telemetry registration (lane #1 W2.4).

Working with [`telemetry_boot.py`](../../src/sevn/gateway/telemetry_boot.py): inspect the public entry points below.
Start with [`register_telemetry_boot_hooks`](../../src/sevn/gateway/telemetry_boot.py#L40).

Render-time timezone conversion for outbound payloads (PROBLEMS.md §4).

Working with [`timestamps.py`](../../src/sevn/gateway/timestamps.py): inspect the public entry points below.
Start with [`to_user_tz`](../../src/sevn/gateway/timestamps.py#L31), then [`operator_local_date_iso`](../../src/sevn/gateway/timestamps.py#L83), [`resolve_time_range`](../../src/sevn/gateway/timestamps.py#L230).

Gateway hook registration for trajectory ingest (Batch C lane #3).

Working with [`trajectory_ingest_hooks.py`](../../src/sevn/gateway/trajectory_ingest_hooks.py): inspect the public entry points below.
Start with [`register_trajectory_ingest_hooks`](../../src/sevn/gateway/trajectory_ingest_hooks.py#L102).

Gateway-owned Triager audit rows (about-sevn.bot/specs/13-rlm-triager.md §10.2, about-sevn.bot/specs/17-gateway.md §3).

Working with [`triage_audit.py`](../../src/sevn/gateway/triage_audit.py): inspect the public entry points below.
Start with [`persist_triage_decision`](../../src/sevn/gateway/triage_audit.py#L57).

Gateway builders for Triager inputs (about-sevn.bot/specs/17-gateway.md §2.6 Wave 2-8).

Working with [`triage_context.py`](../../src/sevn/gateway/triage_context.py): inspect the public entry points below.
Start with [`is_triager_enabled`](../../src/sevn/gateway/triage_context.py#L69), then [`passthrough_triage_result`](../../src/sevn/gateway/triage_context.py#L92), [`registry_snapshot_from_tool_set`](../../src/sevn/gateway/triage_context.py#L123), [`session_view_from_session`](../../src/sevn/gateway/triage_context.py#L215).

Turn-bundle diagnostics — schemas, collector, and index writer (W0 + W1).

Working with [`turn_bundle.py`](../../src/sevn/gateway/turn_bundle.py): inspect the public entry points below.
Start with [`safe_turn_id`](../../src/sevn/gateway/turn_bundle.py#L186), then [`parse_channel_from_turn_id`](../../src/sevn/gateway/turn_bundle.py#L206), [`turn_msg_hex_suffix`](../../src/sevn/gateway/turn_bundle.py#L223), [`turn_log_grep_needles`](../../src/sevn/gateway/turn_bundle.py#L244).

Gateway hook registration for per-turn diagnostic bundles (W1).

Working with [`turn_bundle_hooks.py`](../../src/sevn/gateway/turn_bundle_hooks.py): inspect the public entry points below.
Start with [`register_turn_bundle_hooks`](../../src/sevn/gateway/turn_bundle_hooks.py#L76).

Tier-B answer placeholder + finalizer for Priority 2 (PROBLEMS.md).

Working with [`turn_finalizer.py`](../../src/sevn/gateway/turn_finalizer.py): inspect the public entry points below.
Start with [`TierBAnswerFinalizer.placeholder_message_id`](../../src/sevn/gateway/turn_finalizer.py#L87), then [`TierBAnswerFinalizer.partial_progress_text`](../../src/sevn/gateway/turn_finalizer.py#L101), [`TierBAnswerFinalizer.is_finalized`](../../src/sevn/gateway/turn_finalizer.py#L118).

Turn-bound channel media for multimodal input (about-sevn.bot/specs/17-gateway.md §3.3).

Working with [`turn_media.py`](../../src/sevn/gateway/turn_media.py): inspect the public entry points below.
Start with [`build_turn_media_summaries`](../../src/sevn/gateway/turn_media.py#L78), then [`load_turn_media_summaries`](../../src/sevn/gateway/turn_media.py#L133), [`hydrate_turn_media`](../../src/sevn/gateway/turn_media.py#L198), [`attachment_hints_for_triager`](../../src/sevn/gateway/turn_media.py#L243).

Repo layer for gateway_turn_metadata (PROBLEMS.md §7 / Step §7).

Working with [`turn_metadata.py`](../../src/sevn/gateway/turn_metadata.py): inspect the public entry points below.
Start with [`record_turn_start`](../../src/sevn/gateway/turn_metadata.py#L89), then [`record_turn_finished`](../../src/sevn/gateway/turn_metadata.py#L165), [`load_turn_metadata`](../../src/sevn/gateway/turn_metadata.py#L193), [`format_intent_footer_from_metadata`](../../src/sevn/gateway/turn_metadata.py#L236).

Gateway hook registration for user-model extraction (Batch D lane #6).

Working with [`user_model_hooks.py`](../../src/sevn/gateway/user_model_hooks.py): inspect the public entry points below.
Start with [`register_user_model_hooks`](../../src/sevn/gateway/user_model_hooks.py#L16).

Post-turn user-model extraction orchestration (Batch D lane #6).

Working with [`user_model_turn.py`](../../src/sevn/gateway/user_model_turn.py): inspect the public entry points below.
Start with [`lookup_user_text_for_turn`](../../src/sevn/gateway/user_model_turn.py#L45), then [`maybe_schedule_user_model_extraction_after_turn`](../../src/sevn/gateway/user_model_turn.py#L319).

Repo layer for gateway_user_profile (PROBLEMS.md §4 / Step §4).

Working with [`user_profile.py`](../../src/sevn/gateway/user_profile.py): inspect the public entry points below.
Start with [`get_user_profile`](../../src/sevn/gateway/user_profile.py#L102), then [`set_user_timezone`](../../src/sevn/gateway/user_profile.py#L216), [`set_user_language_code`](../../src/sevn/gateway/user_profile.py#L248).

Web UI WebSocket connection registry (about-sevn.bot/specs/19-channel-webui.md §3.2, §4.3).

Working with [`web_transport.py`](../../src/sevn/gateway/web_transport.py): inspect the public entry points below.
Start with [`WebSocketLike.send_text`](../../src/sevn/gateway/web_transport.py#L23), then [`WebChannelTransport.register`](../../src/sevn/gateway/web_transport.py#L69), [`WebChannelTransport.unregister`](../../src/sevn/gateway/web_transport.py#L98), [`WebChannelTransport.session_count`](../../src/sevn/gateway/web_transport.py#L123).

Telegram/Web App quick-action helpers (share + structured feedback).

Working with [`webapp_qa.py`](../../src/sevn/gateway/webapp_qa.py): inspect the public entry points below.
Start with [`resolve_webapp_public_base`](../../src/sevn/gateway/webapp_qa.py#L54), then [`webapp_inline_buttons_allowed`](../../src/sevn/gateway/webapp_qa.py#L90), [`webapp_https_disabled_notice`](../../src/sevn/gateway/webapp_qa.py#L114), [`maybe_log_qa_bar_webapp_disabled`](../../src/sevn/gateway/webapp_qa.py#L137).

Telegram Mini App rich artifact viewer helpers (about-sevn.bot/specs/19-channel-webui.md §2.5).

Working with [`webapp_viewer.py`](../../src/sevn/gateway/webapp_viewer.py): inspect the public entry points below.
Start with [`webapp_viewer_launch_allowed`](../../src/sevn/gateway/webapp_viewer.py#L120), then [`webapp_share_to_story_enabled`](../../src/sevn/gateway/webapp_viewer.py#L142), [`build_viewer_webapp_url`](../../src/sevn/gateway/webapp_viewer.py#L179), [`infer_viewer_payload_from_markdown`](../../src/sevn/gateway/webapp_viewer.py#L217).

Atomic sevn.json read/write for gateway menu toggles.

Working with [`workspace_config_io.py`](../../src/sevn/gateway/workspace_config_io.py): inspect the public entry points below.
Start with [`set_nested`](../../src/sevn/gateway/workspace_config_io.py#L31), then [`del_nested`](../../src/sevn/gateway/workspace_config_io.py#L58), [`load_raw_sevn_json`](../../src/sevn/gateway/workspace_config_io.py#L83), [`mutate_sevn_json`](../../src/sevn/gateway/workspace_config_io.py#L113).

### Extension and invariants

Follow [`17-gateway.md`](../../about-sevn.bot/specs/17-gateway.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/gateway`](../../src/sevn/gateway/), run `sevn readme fingerprint gateway` (curated body) or `sevn readme update gateway --force` to regenerate, then `make readme-check`.

## References

- [../../about-sevn.bot/specs/17-gateway.md](../../about-sevn.bot/specs/17-gateway.md)
- [../../about-sevn.bot/specs/18-channel-telegram.md](../../about-sevn.bot/specs/18-channel-telegram.md)
- [../../about-sevn.bot/specs/19-channel-webui.md](../../about-sevn.bot/specs/19-channel-webui.md)
- [../../about-sevn.bot/specs/16-harness-discipline.md](../../about-sevn.bot/specs/16-harness-discipline.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/17-gateway.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/gateway/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
