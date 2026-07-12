---
id: spec-17-gateway
kind: spec
title: Gateway — Spec
status: done
owner: Alex
summary: Run the long-lived gateway process that accepts channel ingress (Telegram
  poll/webhook, webchat WS), normalises messages, enforces trust boundaries (scanner,
  rate limits), persists session history, an
last_updated: '2026-07-12'
fingerprint: sha256:a00b1d6bec6df7d1532cb710e0a81f8111f52b0c93e31e6a16d265e4c6f5f6e3
related: []
sources:
- src/sevn/gateway/**
parent_prd: prd-01-conversational-experience
depends_on:
- spec-02-config-and-workspace
- spec-05-llm-transports
- spec-13-rlm-triager
- spec-14-executor-tier-b
- spec-16-harness-discipline
build_phase: null
interfaces:
- name: SecretDeleteBody
  file: src/sevn/gateway/admin_secrets.py
  symbol: SecretDeleteBody
- name: SecretDeleteResponse
  file: src/sevn/gateway/admin_secrets.py
  symbol: SecretDeleteResponse
- name: SecretEntryOut
  file: src/sevn/gateway/admin_secrets.py
  symbol: SecretEntryOut
- name: SecretPutBody
  file: src/sevn/gateway/admin_secrets.py
  symbol: SecretPutBody
- name: SecretPutResponse
  file: src/sevn/gateway/admin_secrets.py
  symbol: SecretPutResponse
- name: SecretsListResponse
  file: src/sevn/gateway/admin_secrets.py
  symbol: SecretsListResponse
- name: register_admin_secrets_routes
  file: src/sevn/gateway/admin_secrets.py
  symbol: register_admin_secrets_routes
- name: build_agent_run_turn
  file: src/sevn/gateway/agent_turn.py
  symbol: build_agent_run_turn
- name: build_intro_extra_instructions
  file: src/sevn/gateway/agent_turn.py
  symbol: build_intro_extra_instructions
- name: JWTClaims
  file: src/sevn/gateway/auth.py
  symbol: JWTClaims
- name: extract_bearer
  file: src/sevn/gateway/auth.py
  symbol: extract_bearer
- name: login_page_html
  file: src/sevn/gateway/auth.py
  symbol: login_page_html
- name: mint_webchat_jwt
  file: src/sevn/gateway/auth.py
  symbol: mint_webchat_jwt
- name: refresh_webchat_access_token
  file: src/sevn/gateway/auth.py
  symbol: refresh_webchat_access_token
- name: secrets_compare
  file: src/sevn/gateway/auth.py
  symbol: secrets_compare
- name: verify_gateway_bearer
  file: src/sevn/gateway/auth.py
  symbol: verify_gateway_bearer
- name: verify_login_gateway_token
  file: src/sevn/gateway/auth.py
  symbol: verify_login_gateway_token
- name: verify_telegram_init_data
  file: src/sevn/gateway/auth.py
  symbol: verify_telegram_init_data
- name: verify_telegram_secret
  file: src/sevn/gateway/auth.py
  symbol: verify_telegram_secret
- name: verify_webchat_jwt
  file: src/sevn/gateway/auth.py
  symbol: verify_webchat_jwt
- name: run_harness_boot_sweep
  file: src/sevn/gateway/boot.py
  symbol: run_harness_boot_sweep
- name: run_workspace_layout_validation
  file: src/sevn/gateway/boot.py
  symbol: run_workspace_layout_validation
- name: BootContext
  file: src/sevn/gateway/boot_registry.py
  symbol: BootContext
- name: clear_boot_registry
  file: src/sevn/gateway/boot_registry.py
  symbol: clear_boot_registry
- name: register_boot_hook
  file: src/sevn/gateway/boot_registry.py
  symbol: register_boot_hook
- name: register_cron_job
  file: src/sevn/gateway/boot_registry.py
  symbol: register_cron_job
- name: run_boot_hooks
  file: src/sevn/gateway/boot_registry.py
  symbol: run_boot_hooks
- name: run_cron_reconciles
  file: src/sevn/gateway/boot_registry.py
  symbol: run_cron_reconciles
- name: extract_bootstrap_name
  file: src/sevn/gateway/bootstrap_capture.py
  symbol: extract_bootstrap_name
- name: try_bootstrap_user_md_fallback
  file: src/sevn/gateway/bootstrap_capture.py
  symbol: try_bootstrap_user_md_fallback
- name: bootstrap_completion_state
  file: src/sevn/gateway/bootstrap_state.py
  symbol: bootstrap_completion_state
- name: operator_name_from_user_md
  file: src/sevn/gateway/bootstrap_state.py
  symbol: operator_name_from_user_md
- name: close_browser_for_rotate
  file: src/sevn/gateway/browser_lifecycle.py
  symbol: close_browser_for_rotate
- name: CascadeBudget
  file: src/sevn/gateway/cascade_budget.py
  symbol: CascadeBudget
- name: ChannelBootArtifacts
  file: src/sevn/gateway/channel_boot.py
  symbol: ChannelBootArtifacts
- name: register_channel_boot_hooks
  file: src/sevn/gateway/channel_boot.py
  symbol: register_channel_boot_hooks
- name: register_enabled_channel_adapters
  file: src/sevn/gateway/channel_boot.py
  symbol: register_enabled_channel_adapters
- name: ChannelRouter
  file: src/sevn/gateway/channel_router.py
  symbol: ChannelRouter
- name: outbound_routing_metadata
  file: src/sevn/gateway/channel_router.py
  symbol: outbound_routing_metadata
- name: ChannelAdapter
  file: src/sevn/gateway/channel_types.py
  symbol: ChannelAdapter
- name: IncomingMessage
  file: src/sevn/gateway/channel_types.py
  symbol: IncomingMessage
- name: OutgoingMessage
  file: src/sevn/gateway/channel_types.py
  symbol: OutgoingMessage
- name: CodingAgentRouter
  file: src/sevn/gateway/coding_agent_router.py
  symbol: CodingAgentRouter
- name: build_ask_config_vocab
  file: src/sevn/gateway/commands/ask_config.py
  symbol: build_ask_config_vocab
- name: format_ask_config_reply
  file: src/sevn/gateway/commands/ask_config.py
  symbol: format_ask_config_reply
- name: parse_ask_config_query
  file: src/sevn/gateway/commands/ask_config.py
  symbol: parse_ask_config_query
- name: CoreCommandHandler
  file: src/sevn/gateway/commands/core_commands.py
  symbol: CoreCommandHandler
- name: DiagnosticCommandHandler
  file: src/sevn/gateway/commands/diagnostic_commands.py
  symbol: DiagnosticCommandHandler
- name: CommandDispatcher
  file: src/sevn/gateway/commands/dispatcher.py
  symbol: CommandDispatcher
- name: EvolutionChatBridge
  file: src/sevn/gateway/commands/evolution_chat_bridge.py
  symbol: EvolutionChatBridge
- name: EvolutionCommandHandler
  file: src/sevn/gateway/commands/evolution_commands.py
  symbol: EvolutionCommandHandler
- name: FileIssueCommandHandler
  file: src/sevn/gateway/commands/evolution_issue_commands.py
  symbol: FileIssueCommandHandler
- name: FileLinkCallbackHandler
  file: src/sevn/gateway/commands/file_link_callback_handler.py
  symbol: FileLinkCallbackHandler
- name: MenuActionRouter
  file: src/sevn/gateway/commands/menu_action_router.py
  symbol: MenuActionRouter
- name: infer_config_section_from_callback
  file: src/sevn/gateway/commands/menu_action_router.py
  symbol: infer_config_section_from_callback
- name: parse_action_callback
  file: src/sevn/gateway/commands/menu_action_router.py
  symbol: parse_action_callback
- name: MenuCommandInvoker
  file: src/sevn/gateway/commands/menu_command_invoke.py
  symbol: MenuCommandInvoker
- name: is_dashboard_pin_message
  file: src/sevn/gateway/commands/menu_command_invoke.py
  symbol: is_dashboard_pin_message
- name: MenuFormHandler
  file: src/sevn/gateway/commands/menu_form_handler.py
  symbol: MenuFormHandler
- name: parse_form_callback
  file: src/sevn/gateway/commands/menu_form_handler.py
  symbol: parse_form_callback
- name: PlatformCommandHandler
  file: src/sevn/gateway/commands/platform_commands.py
  symbol: PlatformCommandHandler
- name: CommandSpec
  file: src/sevn/gateway/commands/registry.py
  symbol: CommandSpec
- name: RollbackCommandHandler
  file: src/sevn/gateway/commands/rollback.py
  symbol: RollbackCommandHandler
- name: SelfImproveCommandHandler
  file: src/sevn/gateway/commands/self_improve_commands.py
  symbol: SelfImproveCommandHandler
- name: ShortcutRecord
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: ShortcutRecord
- name: add_shortcut
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: add_shortcut
- name: delete_shortcut
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: delete_shortcut
- name: find_shortcut
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: find_shortcut
- name: list_visible_shortcuts
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: list_visible_shortcuts
- name: load_shortcuts
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: load_shortcuts
- name: republish_set_my_commands
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: republish_set_my_commands
- name: save_shortcuts
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: save_shortcuts
- name: shortcuts_path
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: shortcuts_path
- name: update_shortcut
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: update_shortcut
- name: validate_shortcut_name
  file: src/sevn/gateway/commands/shortcuts_store.py
  symbol: validate_shortcut_name
- name: extract_transcript_from_user_text
  file: src/sevn/gateway/commands/voice_match.py
  symbol: extract_transcript_from_user_text
- name: format_voice_matched_message
  file: src/sevn/gateway/commands/voice_match.py
  symbol: format_voice_matched_message
- name: match_voice_shortcut
  file: src/sevn/gateway/commands/voice_match.py
  symbol: match_voice_shortcut
- name: voice_shortcut_enabled
  file: src/sevn/gateway/commands/voice_match.py
  symbol: voice_shortcut_enabled
- name: DashboardPinPublisher
  file: src/sevn/gateway/dashboard_pin.py
  symbol: DashboardPinPublisher
- name: dashboard_pin_topic_key
  file: src/sevn/gateway/dashboard_pin.py
  symbol: dashboard_pin_topic_key
- name: default_pin_keyboard
  file: src/sevn/gateway/dashboard_pin.py
  symbol: default_pin_keyboard
- name: default_pin_text
  file: src/sevn/gateway/dashboard_pin.py
  symbol: default_pin_text
- name: lookup_dashboard_pin_message_id
  file: src/sevn/gateway/dashboard_pin.py
  symbol: lookup_dashboard_pin_message_id
- name: register_dashboard_pin
  file: src/sevn/gateway/dashboard_pin.py
  symbol: register_dashboard_pin
- name: render_dashboard_pin
  file: src/sevn/gateway/dashboard_pin.py
  symbol: render_dashboard_pin
- name: unregister_dashboard_pin
  file: src/sevn/gateway/dashboard_pin.py
  symbol: unregister_dashboard_pin
- name: load_or_create_deployment_id
  file: src/sevn/gateway/deployment_id.py
  symbol: load_or_create_deployment_id
- name: format_for_telegram
  file: src/sevn/gateway/diagnostics.py
  symbol: format_for_telegram
- name: format_traces_for_telegram
  file: src/sevn/gateway/diagnostics.py
  symbol: format_traces_for_telegram
- name: get_span
  file: src/sevn/gateway/diagnostics.py
  symbol: get_span
- name: recent_traces
  file: src/sevn/gateway/diagnostics.py
  symbol: recent_traces
- name: tail_service_log
  file: src/sevn/gateway/diagnostics.py
  symbol: tail_service_log
- name: prune_dispatcher_callbacks
  file: src/sevn/gateway/dispatcher_callbacks.py
  symbol: prune_dispatcher_callbacks
- name: dispatcher_state_ttl_for_kind
  file: src/sevn/gateway/dispatcher_state.py
  symbol: dispatcher_state_ttl_for_kind
- name: insert_dispatcher_state
  file: src/sevn/gateway/dispatcher_state.py
  symbol: insert_dispatcher_state
- name: sweep_expired_dispatcher_state
  file: src/sevn/gateway/dispatcher_state.py
  symbol: sweep_expired_dispatcher_state
- name: build_echo_run_turn
  file: src/sevn/gateway/e2e_echo.py
  symbol: build_echo_run_turn
- name: GatewayEvent
  file: src/sevn/gateway/event_hooks.py
  symbol: GatewayEvent
- name: GatewayEventPayload
  file: src/sevn/gateway/event_hooks.py
  symbol: GatewayEventPayload
- name: clear_gateway_event_hooks
  file: src/sevn/gateway/event_hooks.py
  symbol: clear_gateway_event_hooks
- name: emit_gateway_event
  file: src/sevn/gateway/event_hooks.py
  symbol: emit_gateway_event
- name: register_gateway_event_hook
  file: src/sevn/gateway/event_hooks.py
  symbol: register_gateway_event_hook
- name: EvolutionApprovalCallbackHandler
  file: src/sevn/gateway/evolution_approval_gate.py
  symbol: EvolutionApprovalCallbackHandler
- name: EvolutionApprovalWaitRegistry
  file: src/sevn/gateway/evolution_approval_gate.py
  symbol: EvolutionApprovalWaitRegistry
- name: build_evolution_approval_inline_keyboard
  file: src/sevn/gateway/evolution_approval_gate.py
  symbol: build_evolution_approval_inline_keyboard
- name: parse_evolution_callback_data
  file: src/sevn/gateway/evolution_approval_gate.py
  symbol: parse_evolution_callback_data
- name: EvolutionIssueEventFanout
  file: src/sevn/gateway/evolution_issue_events.py
  symbol: EvolutionIssueEventFanout
- name: bootstrap_capture_active
  file: src/sevn/gateway/first_session.py
  symbol: bootstrap_capture_active
- name: bootstrap_capture_instructions
  file: src/sevn/gateway/first_session.py
  symbol: bootstrap_capture_instructions
- name: bootstrap_completion_state
  file: src/sevn/gateway/first_session.py
  symbol: bootstrap_completion_state
- name: clear_bootstrap_markdown_cache
  file: src/sevn/gateway/first_session.py
  symbol: clear_bootstrap_markdown_cache
- name: clear_intro_state_cache
  file: src/sevn/gateway/first_session.py
  symbol: clear_intro_state_cache
- name: count_user_messages
  file: src/sevn/gateway/first_session.py
  symbol: count_user_messages
- name: count_user_messages_in_session
  file: src/sevn/gateway/first_session.py
  symbol: count_user_messages_in_session
- name: first_session_intro_enabled
  file: src/sevn/gateway/first_session.py
  symbol: first_session_intro_enabled
- name: first_session_intro_max_output_tokens
  file: src/sevn/gateway/first_session.py
  symbol: first_session_intro_max_output_tokens
- name: intro_state_for_scope
  file: src/sevn/gateway/first_session.py
  symbol: intro_state_for_scope
- name: intro_state_for_session
  file: src/sevn/gateway/first_session.py
  symbol: intro_state_for_session
- name: is_first_session_turn
  file: src/sevn/gateway/first_session.py
  symbol: is_first_session_turn
- name: load_bootstrap_markdown
  file: src/sevn/gateway/first_session.py
  symbol: load_bootstrap_markdown
- name: load_bootstrap_markdown_cached
  file: src/sevn/gateway/first_session.py
  symbol: load_bootstrap_markdown_cached
- name: mark_intro_state
  file: src/sevn/gateway/first_session.py
  symbol: mark_intro_state
- name: maybe_mark_intro_done_if_bootstrap_complete
  file: src/sevn/gateway/first_session.py
  symbol: maybe_mark_intro_done_if_bootstrap_complete
- name: maybe_reseed_bootstrap_at_boot
  file: src/sevn/gateway/first_session.py
  symbol: maybe_reseed_bootstrap_at_boot
- name: missing_user_md_bootstrap_fields
  file: src/sevn/gateway/first_session.py
  symbol: missing_user_md_bootstrap_fields
- name: tier_b_intro_instructions
  file: src/sevn/gateway/first_session.py
  symbol: tier_b_intro_instructions
- name: user_md_bootstrap_profile_incomplete
  file: src/sevn/gateway/first_session.py
  symbol: user_md_bootstrap_profile_incomplete
- name: PendingGatewayRestart
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: PendingGatewayRestart
- name: claim_pending_gateway_restarts
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: claim_pending_gateway_restarts
- name: clear_pending_gateway_restarts
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: clear_pending_gateway_restarts
- name: conversation_snapshot_for_session
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: conversation_snapshot_for_session
- name: deliver_pending_gateway_restart_acks
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: deliver_pending_gateway_restart_acks
- name: has_pending_gateway_restart
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: has_pending_gateway_restart
- name: load_pending_gateway_restarts
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: load_pending_gateway_restarts
- name: mark_restart_ack_delivered
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: mark_restart_ack_delivered
- name: pending_restart_store_path
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: pending_restart_store_path
- name: recent_restart_ack_delivered
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: recent_restart_ack_delivered
- name: record_pending_gateway_restart
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: record_pending_gateway_restart
- name: restart_ack_delivered_path
  file: src/sevn/gateway/gateway_restart_ack.py
  symbol: restart_ack_delivered_path
- name: generate_gateway_token
  file: src/sevn/gateway/gateway_token.py
  symbol: generate_gateway_token
- name: resolve_gateway_token_ref
  file: src/sevn/gateway/gateway_token.py
  symbol: resolve_gateway_token_ref
- name: validate_gateway_token_plaintext
  file: src/sevn/gateway/gateway_token.py
  symbol: validate_gateway_token_plaintext
- name: mount_gui_proxy
  file: src/sevn/gateway/gui_proxy.py
  symbol: mount_gui_proxy
- name: DeferredGatewayOnboardingRoute
  file: src/sevn/gateway/http_server.py
  symbol: DeferredGatewayOnboardingRoute
- name: create_app
  file: src/sevn/gateway/http_server.py
  symbol: create_app
- name: deferred_json
  file: src/sevn/gateway/http_server.py
  symbol: deferred_json
- name: ingest_gateway_message_row
  file: src/sevn/gateway/lcm_ingest.py
  symbol: ingest_gateway_message_row
- name: MediaStore
  file: src/sevn/gateway/media_store.py
  symbol: MediaStore
- name: ConfigMenuHandler
  file: src/sevn/gateway/menu.py
  symbol: ConfigMenuHandler
- name: ConfigMenuNavFrame
  file: src/sevn/gateway/menu.py
  symbol: ConfigMenuNavFrame
- name: ConfigMenuRefreshContext
  file: src/sevn/gateway/menu.py
  symbol: ConfigMenuRefreshContext
- name: MenuCallbackHandler
  file: src/sevn/gateway/menu.py
  symbol: MenuCallbackHandler
- name: MenuToolSurface
  file: src/sevn/gateway/menu.py
  symbol: MenuToolSurface
- name: build_chat_menu_webapp_request
  file: src/sevn/gateway/menu.py
  symbol: build_chat_menu_webapp_request
- name: build_config_menu_keyboard
  file: src/sevn/gateway/menu.py
  symbol: build_config_menu_keyboard
- name: build_menu_keyboard
  file: src/sevn/gateway/menu.py
  symbol: build_menu_keyboard
- name: build_service_restart_confirm_keyboard
  file: src/sevn/gateway/menu.py
  symbol: build_service_restart_confirm_keyboard
- name: config_callback_matches
  file: src/sevn/gateway/menu.py
  symbol: config_callback_matches
- name: config_menu_message_text
  file: src/sevn/gateway/menu.py
  symbol: config_menu_message_text
- name: config_menu_nav_clear
  file: src/sevn/gateway/menu.py
  symbol: config_menu_nav_clear
- name: config_menu_nav_go
  file: src/sevn/gateway/menu.py
  symbol: config_menu_nav_go
- name: config_menu_nav_home
  file: src/sevn/gateway/menu.py
  symbol: config_menu_nav_home
- name: config_menu_nav_key
  file: src/sevn/gateway/menu.py
  symbol: config_menu_nav_key
- name: config_menu_nav_pop
  file: src/sevn/gateway/menu.py
  symbol: config_menu_nav_pop
- name: config_menu_nav_push_current
  file: src/sevn/gateway/menu.py
  symbol: config_menu_nav_push_current
- name: get_config_menu_nav
  file: src/sevn/gateway/menu.py
  symbol: get_config_menu_nav
- name: infer_budget_regime
  file: src/sevn/gateway/menu.py
  symbol: infer_budget_regime
- name: menu_callback_matches
  file: src/sevn/gateway/menu.py
  symbol: menu_callback_matches
- name: menu_message_text
  file: src/sevn/gateway/menu.py
  symbol: menu_message_text
- name: parse_config_callback_data
  file: src/sevn/gateway/menu.py
  symbol: parse_config_callback_data
- name: parse_menu_callback_data
  file: src/sevn/gateway/menu.py
  symbol: parse_menu_callback_data
- name: parse_models_callback_data
  file: src/sevn/gateway/menu.py
  symbol: parse_models_callback_data
- name: refresh_config_menu_message
  file: src/sevn/gateway/menu.py
  symbol: refresh_config_menu_message
- name: service_restart_confirm_message
  file: src/sevn/gateway/menu.py
  symbol: service_restart_confirm_message
- name: sync_telegram_chat_menu_button
  file: src/sevn/gateway/menu.py
  symbol: sync_telegram_chat_menu_button
- name: web_ui_url_from_workspace
  file: src/sevn/gateway/menu.py
  symbol: web_ui_url_from_workspace
- name: config_sevn_bot_section_title
  file: src/sevn/gateway/menu_branding.py
  symbol: config_sevn_bot_section_title
- name: config_menu_help_catalog_text
  file: src/sevn/gateway/menu_readiness.py
  symbol: config_menu_help_catalog_text
- name: config_menu_level_help_text
  file: src/sevn/gateway/menu_readiness.py
  symbol: config_menu_level_help_text
- name: config_section_catalog
  file: src/sevn/gateway/menu_readiness.py
  symbol: config_section_catalog
- name: gate_config_keyboard_rows
  file: src/sevn/gateway/menu_readiness.py
  symbol: gate_config_keyboard_rows
- name: readiness_for_callback
  file: src/sevn/gateway/menu_readiness.py
  symbol: readiness_for_callback
- name: readiness_user_label
  file: src/sevn/gateway/menu_readiness.py
  symbol: readiness_user_label
- name: MenuButtonSpec
  file: src/sevn/gateway/menu_registry.py
  symbol: MenuButtonSpec
- name: is_nav_chrome_callback
  file: src/sevn/gateway/menu_registry.py
  symbol: is_nav_chrome_callback
- name: is_section_tile_callback
  file: src/sevn/gateway/menu_registry.py
  symbol: is_section_tile_callback
- name: match_menu_button_spec
  file: src/sevn/gateway/menu_registry.py
  symbol: match_menu_button_spec
- name: registry_implementation_counts
  file: src/sevn/gateway/menu_registry.py
  symbol: registry_implementation_counts
- name: EmptyMissionControlState
  file: src/sevn/gateway/mission_api.py
  symbol: EmptyMissionControlState
- name: create_mission_v1_router
  file: src/sevn/gateway/mission_api.py
  symbol: create_mission_v1_router
- name: resolve_mission_control_state
  file: src/sevn/gateway/mission_api.py
  symbol: resolve_mission_control_state
- name: MissionControlState
  file: src/sevn/gateway/mission_state.py
  symbol: MissionControlState
- name: AgentActivity
  file: src/sevn/gateway/mission_state_models.py
  symbol: AgentActivity
- name: Alert
  file: src/sevn/gateway/mission_state_models.py
  symbol: Alert
- name: AlertRule
  file: src/sevn/gateway/mission_state_models.py
  symbol: AlertRule
- name: ChannelHealth
  file: src/sevn/gateway/mission_state_models.py
  symbol: ChannelHealth
- name: NotificationTarget
  file: src/sevn/gateway/mission_state_models.py
  symbol: NotificationTarget
- name: ProviderHealth
  file: src/sevn/gateway/mission_state_models.py
  symbol: ProviderHealth
- name: SessionMissionStats
  file: src/sevn/gateway/mission_state_models.py
  symbol: SessionMissionStats
- name: event_timestamp
  file: src/sevn/gateway/mission_state_models.py
  symbol: event_timestamp
- name: is_channel_trace_kind
  file: src/sevn/gateway/mission_state_models.py
  symbol: is_channel_trace_kind
- name: is_mission_telemetry_kind
  file: src/sevn/gateway/mission_state_models.py
  symbol: is_mission_telemetry_kind
- name: normalize_complexity
  file: src/sevn/gateway/mission_state_models.py
  symbol: normalize_complexity
- name: MissionControlSnapshotsMixin
  file: src/sevn/gateway/mission_state_snapshots.py
  symbol: MissionControlSnapshotsMixin
- name: MissionControlTraceSink
  file: src/sevn/gateway/mission_trace_sink.py
  symbol: MissionControlTraceSink
- name: create_mission_trace_sink
  file: src/sevn/gateway/mission_trace_sink.py
  symbol: create_mission_trace_sink
- name: detach_mission_trace_sink
  file: src/sevn/gateway/mission_trace_sink.py
  symbol: detach_mission_trace_sink
- name: resolve_mission_control_state
  file: src/sevn/gateway/mission_trace_sink.py
  symbol: resolve_mission_control_state
- name: mount_gateway_onboarding
  file: src/sevn/gateway/onboarding_mount.py
  symbol: mount_gateway_onboarding
- name: resolve_gateway_onboarding_token
  file: src/sevn/gateway/onboarding_mount.py
  symbol: resolve_gateway_onboarding_token
- name: ChatCompletionRequest
  file: src/sevn/gateway/openai_compat_api.py
  symbol: ChatCompletionRequest
- name: ChatMessage
  file: src/sevn/gateway/openai_compat_api.py
  symbol: ChatMessage
- name: build_openai_compat_router
  file: src/sevn/gateway/openai_compat_api.py
  symbol: build_openai_compat_router
- name: register_openai_compat_routes
  file: src/sevn/gateway/openai_compat_api.py
  symbol: register_openai_compat_routes
- name: sweep_outbound_retries
  file: src/sevn/gateway/outbound_sweep.py
  symbol: sweep_outbound_retries
- name: PairingStore
  file: src/sevn/gateway/pairing.py
  symbol: PairingStore
- name: pairing_dir_for_content_root
  file: src/sevn/gateway/pairing.py
  symbol: pairing_dir_for_content_root
- name: PlanGateCallbackHandler
  file: src/sevn/gateway/plan_gate.py
  symbol: PlanGateCallbackHandler
- name: PlanGateWaitRegistry
  file: src/sevn/gateway/plan_gate.py
  symbol: PlanGateWaitRegistry
- name: SqlitePlanGate
  file: src/sevn/gateway/plan_gate.py
  symbol: SqlitePlanGate
- name: build_plan_inline_keyboard
  file: src/sevn/gateway/plan_gate.py
  symbol: build_plan_inline_keyboard
- name: format_plan_message_text
  file: src/sevn/gateway/plan_gate.py
  symbol: format_plan_message_text
- name: parse_plan_callback_data
  file: src/sevn/gateway/plan_gate.py
  symbol: parse_plan_callback_data
- name: PlatformRuntimeRegistry
  file: src/sevn/gateway/platform_runtime.py
  symbol: PlatformRuntimeRegistry
- name: PlatformRuntimeState
  file: src/sevn/gateway/platform_runtime.py
  symbol: PlatformRuntimeState
- name: PostTurnContext
  file: src/sevn/gateway/post_turn_hooks.py
  symbol: PostTurnContext
- name: clear_post_turn_hooks
  file: src/sevn/gateway/post_turn_hooks.py
  symbol: clear_post_turn_hooks
- name: register_post_turn_hook
  file: src/sevn/gateway/post_turn_hooks.py
  symbol: register_post_turn_hook
- name: run_post_turn_hooks
  file: src/sevn/gateway/post_turn_hooks.py
  symbol: run_post_turn_hooks
- name: render_gateway_metrics
  file: src/sevn/gateway/prometheus_metrics.py
  symbol: render_gateway_metrics
- name: TokenBucketLimiter
  file: src/sevn/gateway/rate_limit.py
  symbol: TokenBucketLimiter
- name: redact_inline
  file: src/sevn/gateway/redact.py
  symbol: redact_inline
- name: ReplayJobEventFanout
  file: src/sevn/gateway/replay_job_events.py
  symbol: ReplayJobEventFanout
- name: ReplayJobEventFanoutFn
  file: src/sevn/gateway/replay_job_events.py
  symbol: ReplayJobEventFanoutFn
- name: ReplayJobEventPayload
  file: src/sevn/gateway/replay_job_events.py
  symbol: ReplayJobEventPayload
- name: replay_ws_topic
  file: src/sevn/gateway/replay_job_events.py
  symbol: replay_ws_topic
- name: lookup_user_text_for_turn
  file: src/sevn/gateway/replay_turn_lookup.py
  symbol: lookup_user_text_for_turn
- name: ReplayJobRequest
  file: src/sevn/gateway/replay_worker.py
  symbol: ReplayJobRequest
- name: TurnReplayWorker
  file: src/sevn/gateway/replay_worker.py
  symbol: TurnReplayWorker
- name: register_replay_worker_hooks
  file: src/sevn/gateway/replay_worker_hooks.py
  symbol: register_replay_worker_hooks
- name: is_intentional_silence_agent_result
  file: src/sevn/gateway/response_filters.py
  symbol: is_intentional_silence_agent_result
- name: is_intentional_silence_response
  file: src/sevn/gateway/response_filters.py
  symbol: is_intentional_silence_response
- name: append_routing_footer
  file: src/sevn/gateway/routing_footer.py
  symbol: append_routing_footer
- name: format_routing_footer
  file: src/sevn/gateway/routing_footer.py
  symbol: format_routing_footer
- name: strip_model_emitted_footer
  file: src/sevn/gateway/routing_footer.py
  symbol: strip_model_emitted_footer
- name: telegram_show_routing_enabled
  file: src/sevn/gateway/routing_footer.py
  symbol: telegram_show_routing_enabled
- name: SelfImproveJobEventFanout
  file: src/sevn/gateway/self_improve_job_events.py
  symbol: SelfImproveJobEventFanout
- name: resolve_owner_telegram_user_id
  file: src/sevn/gateway/self_improve_job_events.py
  symbol: resolve_owner_telegram_user_id
- name: SessionManager
  file: src/sevn/gateway/session_manager.py
  symbol: SessionManager
- name: SessionRow
  file: src/sevn/gateway/session_manager.py
  symbol: SessionRow
- name: format_lcm_status_lines
  file: src/sevn/gateway/session_manager.py
  symbol: format_lcm_status_lines
- name: get_tts_mode_override
  file: src/sevn/gateway/session_manager.py
  symbol: get_tts_mode_override
- name: latest_messages
  file: src/sevn/gateway/session_manager.py
  symbol: latest_messages
- name: load_session_row
  file: src/sevn/gateway/session_manager.py
  symbol: load_session_row
- name: set_tts_mode_override
  file: src/sevn/gateway/session_manager.py
  symbol: set_tts_mode_override
- name: unanswered_tail_message_id
  file: src/sevn/gateway/session_manager.py
  symbol: unanswered_tail_message_id
- name: mark_session_superseded
  file: src/sevn/gateway/session_mirror.py
  symbol: mark_session_superseded
- name: mirror_gateway_message
  file: src/sevn/gateway/session_mirror.py
  symbol: mirror_gateway_message
- name: session_mirror_enabled
  file: src/sevn/gateway/session_mirror.py
  symbol: session_mirror_enabled
- name: SessionResetPolicy
  file: src/sevn/gateway/session_reset.py
  symbol: SessionResetPolicy
- name: resolve_session_reset_policy
  file: src/sevn/gateway/session_reset.py
  symbol: resolve_session_reset_policy
- name: session_should_reset
  file: src/sevn/gateway/session_reset.py
  symbol: session_should_reset
- name: can_access_session
  file: src/sevn/gateway/sessions_query.py
  symbol: can_access_session
- name: cap_history_limit
  file: src/sevn/gateway/sessions_query.py
  symbol: cap_history_limit
- name: fetch_session_history
  file: src/sevn/gateway/sessions_query.py
  symbol: fetch_session_history
- name: insert_message
  file: src/sevn/gateway/sessions_query.py
  symbol: insert_message
- name: list_sessions
  file: src/sevn/gateway/sessions_query.py
  symbol: list_sessions
- name: list_sessions_active_between
  file: src/sevn/gateway/sessions_query.py
  symbol: list_sessions_active_between
- name: parse_session_metadata
  file: src/sevn/gateway/sessions_query.py
  symbol: parse_session_metadata
- name: record_yield
  file: src/sevn/gateway/sessions_query.py
  symbol: record_yield
- name: search_messages
  file: src/sevn/gateway/sessions_query.py
  symbol: search_messages
- name: send_to_session
  file: src/sevn/gateway/sessions_query.py
  symbol: send_to_session
- name: session_operator_timezone
  file: src/sevn/gateway/sessions_query.py
  symbol: session_operator_timezone
- name: session_status_snapshot
  file: src/sevn/gateway/sessions_query.py
  symbol: session_status_snapshot
- name: spawn_subagent
  file: src/sevn/gateway/sessions_query.py
  symbol: spawn_subagent
- name: release_leaked_multiprocessing_semaphores
  file: src/sevn/gateway/shutdown_cleanup.py
  symbol: release_leaked_multiprocessing_semaphores
- name: SlashAccessPolicy
  file: src/sevn/gateway/slash_access.py
  symbol: SlashAccessPolicy
- name: canonical_slash_command
  file: src/sevn/gateway/slash_access.py
  symbol: canonical_slash_command
- name: is_admin_slash_command
  file: src/sevn/gateway/slash_access.py
  symbol: is_admin_slash_command
- name: policy_for_message
  file: src/sevn/gateway/slash_access.py
  symbol: policy_for_message
- name: policy_from_channel_extra
  file: src/sevn/gateway/slash_access.py
  symbol: policy_from_channel_extra
- name: slash_allowed_for_actor
  file: src/sevn/gateway/slash_access.py
  symbol: slash_allowed_for_actor
- name: SessionBoundSteerInject
  file: src/sevn/gateway/steer_store.py
  symbol: SessionBoundSteerInject
- name: SessionSteerStore
  file: src/sevn/gateway/steer_store.py
  symbol: SessionSteerStore
- name: SteerEnqueueResult
  file: src/sevn/gateway/steer_store.py
  symbol: SteerEnqueueResult
- name: owner_user_ids_from_workspace
  file: src/sevn/gateway/steer_store.py
  symbol: owner_user_ids_from_workspace
- name: parse_steer_command_text
  file: src/sevn/gateway/steer_store.py
  symbol: parse_steer_command_text
- name: blocked_inbound_user_message
  file: src/sevn/gateway/strings.py
  symbol: blocked_inbound_user_message
- name: dispatch_telegram_inline_query
  file: src/sevn/gateway/telegram_inline.py
  symbol: dispatch_telegram_inline_query
- name: handle_chosen_inline_result_feedback
  file: src/sevn/gateway/telegram_inline.py
  symbol: handle_chosen_inline_result_feedback
- name: maybe_emit_botfather_inline_warning
  file: src/sevn/gateway/telegram_inline.py
  symbol: maybe_emit_botfather_inline_warning
- name: try_route_telegram_inline
  file: src/sevn/gateway/telegram_inline.py
  symbol: try_route_telegram_inline
- name: build_agent_inline_results
  file: src/sevn/gateway/telegram_inline_agent.py
  symbol: build_agent_inline_results
- name: capture_router_outbound_text
  file: src/sevn/gateway/telegram_inline_agent.py
  symbol: capture_router_outbound_text
- name: make_run_turn_agent_answer_fn
  file: src/sevn/gateway/telegram_inline_agent.py
  symbol: make_run_turn_agent_answer_fn
- name: InlineArticleResult
  file: src/sevn/gateway/telegram_inline_base.py
  symbol: InlineArticleResult
- name: InlineBuildContext
  file: src/sevn/gateway/telegram_inline_base.py
  symbol: InlineBuildContext
- name: InlineInputMessageContent
  file: src/sevn/gateway/telegram_inline_base.py
  symbol: InlineInputMessageContent
- name: InlineSourceResult
  file: src/sevn/gateway/telegram_inline_base.py
  symbol: InlineSourceResult
- name: inline_article_result
  file: src/sevn/gateway/telegram_inline_base.py
  symbol: inline_article_result
- name: build_answer_inline_query_payload
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: build_answer_inline_query_payload
- name: build_inline_input_message_content
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: build_inline_input_message_content
- name: compute_inline_answer_cache_time
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: compute_inline_answer_cache_time
- name: dedupe_inline_results
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: dedupe_inline_results
- name: is_inline_botfather_setup_error
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: is_inline_botfather_setup_error
- name: paginate_inline_results
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: paginate_inline_results
- name: parse_inline_result_offset
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: parse_inline_result_offset
- name: sanitize_inline_results_for_api
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: sanitize_inline_results_for_api
- name: upgrade_inline_results_for_capability
  file: src/sevn/gateway/telegram_inline_dispatch.py
  symbol: upgrade_inline_results_for_capability
- name: build_printing_press_inline_results
  file: src/sevn/gateway/telegram_inline_printing_press.py
  symbol: build_printing_press_inline_results
- name: build_all_inline_source_results
  file: src/sevn/gateway/telegram_inline_sources.py
  symbol: build_all_inline_source_results
- name: build_artifacts_inline_results
  file: src/sevn/gateway/telegram_inline_sources.py
  symbol: build_artifacts_inline_results
- name: build_second_brain_inline_results
  file: src/sevn/gateway/telegram_inline_sources.py
  symbol: build_second_brain_inline_results
- name: inline_sources_module_ready
  file: src/sevn/gateway/telegram_inline_sources.py
  symbol: inline_sources_module_ready
- name: merge_inline_query_results
  file: src/sevn/gateway/telegram_inline_sources.py
  symbol: merge_inline_query_results
- name: InlineAuthContext
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: InlineAuthContext
- name: InlineDispatchContext
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: InlineDispatchContext
- name: build_inline_dispatch_context
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: build_inline_dispatch_context
- name: inline_source_cache_time
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: inline_source_cache_time
- name: inline_user_may_use_agent_source
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: inline_user_may_use_agent_source
- name: resolve_inline_config
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: resolve_inline_config
- name: telegram_allowed_updates
  file: src/sevn/gateway/telegram_inline_types.py
  symbol: telegram_allowed_updates
- name: QuickActionCallbackHandler
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: QuickActionCallbackHandler
- name: build_quick_action_inline_keyboard
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: build_quick_action_inline_keyboard
- name: is_telegram_fast_callback_ack
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: is_telegram_fast_callback_ack
- name: lookup_assistant_row_by_platform_message
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: lookup_assistant_row_by_platform_message
- name: lookup_origin_user_text_for_assistant
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: lookup_origin_user_text_for_assistant
- name: parse_qa_callback_data
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: parse_qa_callback_data
- name: record_assistant_platform_message
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: record_assistant_platform_message
- name: telegram_fast_callback_ack_text
  file: src/sevn/gateway/telegram_quick_actions.py
  symbol: telegram_fast_callback_ack_text
- name: resolve_telegram_bot_token
  file: src/sevn/gateway/telegram_resolve.py
  symbol: resolve_telegram_bot_token
- name: ensure_webhook_secret_token
  file: src/sevn/gateway/telegram_webhook_secret.py
  symbol: ensure_webhook_secret_token
- name: register_telemetry_boot_hooks
  file: src/sevn/gateway/telemetry_boot.py
  symbol: register_telemetry_boot_hooks
- name: operator_local_date_iso
  file: src/sevn/gateway/timestamps.py
  symbol: operator_local_date_iso
- name: resolve_time_range
  file: src/sevn/gateway/timestamps.py
  symbol: resolve_time_range
- name: to_user_tz
  file: src/sevn/gateway/timestamps.py
  symbol: to_user_tz
- name: register_trajectory_ingest_hooks
  file: src/sevn/gateway/trajectory_ingest_hooks.py
  symbol: register_trajectory_ingest_hooks
- name: persist_triage_decision
  file: src/sevn/gateway/triage_audit.py
  symbol: persist_triage_decision
- name: group_triage_block_would_inject
  file: src/sevn/gateway/triage_context.py
  symbol: group_triage_block_would_inject
- name: is_triager_enabled
  file: src/sevn/gateway/triage_context.py
  symbol: is_triager_enabled
- name: latest_prior_triage_result
  file: src/sevn/gateway/triage_context.py
  symbol: latest_prior_triage_result
- name: lcm_summary_stub_for_session
  file: src/sevn/gateway/triage_context.py
  symbol: lcm_summary_stub_for_session
- name: load_workspace_personality
  file: src/sevn/gateway/triage_context.py
  symbol: load_workspace_personality
- name: passthrough_triage_result
  file: src/sevn/gateway/triage_context.py
  symbol: passthrough_triage_result
- name: registry_snapshot_from_tool_set
  file: src/sevn/gateway/triage_context.py
  symbol: registry_snapshot_from_tool_set
- name: session_view_from_session
  file: src/sevn/gateway/triage_context.py
  symbol: session_view_from_session
- name: tier_b_personality_instructions
  file: src/sevn/gateway/triage_context.py
  symbol: tier_b_personality_instructions
- name: triage_context_from_session
  file: src/sevn/gateway/triage_context.py
  symbol: triage_context_from_session
- name: window_transcript
  file: src/sevn/gateway/triage_context.py
  symbol: window_transcript
- name: TurnBundleIndex
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundleIndex
- name: TurnBundleIndexEntry
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundleIndexEntry
- name: TurnBundleLogRecord
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundleLogRecord
- name: TurnBundleMessageRecord
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundleMessageRecord
- name: TurnBundleMetaRecord
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundleMetaRecord
- name: TurnBundlePaths
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundlePaths
- name: TurnBundleTraceRecord
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnBundleTraceRecord
- name: TurnExportCandidate
  file: src/sevn/gateway/turn_bundle.py
  symbol: TurnExportCandidate
- name: bundle_paths
  file: src/sevn/gateway/turn_bundle.py
  symbol: bundle_paths
- name: bundle_record_is_error
  file: src/sevn/gateway/turn_bundle.py
  symbol: bundle_record_is_error
- name: collect_turn_bundle_records
  file: src/sevn/gateway/turn_bundle.py
  symbol: collect_turn_bundle_records
- name: compute_has_error
  file: src/sevn/gateway/turn_bundle.py
  symbol: compute_has_error
- name: effective_turn_bundles_enabled
  file: src/sevn/gateway/turn_bundle.py
  symbol: effective_turn_bundles_enabled
- name: export_turn_bundles
  file: src/sevn/gateway/turn_bundle.py
  symbol: export_turn_bundles
- name: format_turn_bundle_record
  file: src/sevn/gateway/turn_bundle.py
  symbol: format_turn_bundle_record
- name: format_turn_bundle_summary
  file: src/sevn/gateway/turn_bundle.py
  symbol: format_turn_bundle_summary
- name: list_turn_export_candidates
  file: src/sevn/gateway/turn_bundle.py
  symbol: list_turn_export_candidates
- name: load_turn_bundle_index
  file: src/sevn/gateway/turn_bundle.py
  symbol: load_turn_bundle_index
- name: load_turn_bundle_records
  file: src/sevn/gateway/turn_bundle.py
  symbol: load_turn_bundle_records
- name: log_line_matches_turn
  file: src/sevn/gateway/turn_bundle.py
  symbol: log_line_matches_turn
- name: parse_channel_from_turn_id
  file: src/sevn/gateway/turn_bundle.py
  symbol: parse_channel_from_turn_id
- name: parse_since_timestamp
  file: src/sevn/gateway/turn_bundle.py
  symbol: parse_since_timestamp
- name: resolve_turn_bundle_file
  file: src/sevn/gateway/turn_bundle.py
  symbol: resolve_turn_bundle_file
- name: resolve_turn_terminal_status
  file: src/sevn/gateway/turn_bundle.py
  symbol: resolve_turn_terminal_status
- name: safe_turn_id
  file: src/sevn/gateway/turn_bundle.py
  symbol: safe_turn_id
- name: turn_log_grep_needles
  file: src/sevn/gateway/turn_bundle.py
  symbol: turn_log_grep_needles
- name: turn_msg_hex_suffix
  file: src/sevn/gateway/turn_bundle.py
  symbol: turn_msg_hex_suffix
- name: upsert_turn_bundle_index_entry
  file: src/sevn/gateway/turn_bundle.py
  symbol: upsert_turn_bundle_index_entry
- name: view_turn_bundle
  file: src/sevn/gateway/turn_bundle.py
  symbol: view_turn_bundle
- name: write_turn_bundle
  file: src/sevn/gateway/turn_bundle.py
  symbol: write_turn_bundle
- name: register_turn_bundle_hooks
  file: src/sevn/gateway/turn_bundle_hooks.py
  symbol: register_turn_bundle_hooks
- name: TierBAnswerFinalizer
  file: src/sevn/gateway/turn_finalizer.py
  symbol: TierBAnswerFinalizer
- name: TurnMediaItem
  file: src/sevn/gateway/turn_media.py
  symbol: TurnMediaItem
- name: attachment_hints_for_triager
  file: src/sevn/gateway/turn_media.py
  symbol: attachment_hints_for_triager
- name: build_turn_media_summaries
  file: src/sevn/gateway/turn_media.py
  symbol: build_turn_media_summaries
- name: hydrate_turn_media
  file: src/sevn/gateway/turn_media.py
  symbol: hydrate_turn_media
- name: infer_modality_flags
  file: src/sevn/gateway/turn_media.py
  symbol: infer_modality_flags
- name: load_turn_media_summaries
  file: src/sevn/gateway/turn_media.py
  symbol: load_turn_media_summaries
- name: TurnMetadata
  file: src/sevn/gateway/turn_metadata.py
  symbol: TurnMetadata
- name: format_intent_footer_from_metadata
  file: src/sevn/gateway/turn_metadata.py
  symbol: format_intent_footer_from_metadata
- name: load_turn_metadata
  file: src/sevn/gateway/turn_metadata.py
  symbol: load_turn_metadata
- name: record_turn_finished
  file: src/sevn/gateway/turn_metadata.py
  symbol: record_turn_finished
- name: record_turn_start
  file: src/sevn/gateway/turn_metadata.py
  symbol: record_turn_start
- name: register_user_model_hooks
  file: src/sevn/gateway/user_model_hooks.py
  symbol: register_user_model_hooks
- name: lookup_user_text_for_turn
  file: src/sevn/gateway/user_model_turn.py
  symbol: lookup_user_text_for_turn
- name: maybe_schedule_user_model_extraction_after_turn
  file: src/sevn/gateway/user_model_turn.py
  symbol: maybe_schedule_user_model_extraction_after_turn
- name: UserProfile
  file: src/sevn/gateway/user_profile.py
  symbol: UserProfile
- name: get_user_profile
  file: src/sevn/gateway/user_profile.py
  symbol: get_user_profile
- name: set_user_language_code
  file: src/sevn/gateway/user_profile.py
  symbol: set_user_language_code
- name: set_user_timezone
  file: src/sevn/gateway/user_profile.py
  symbol: set_user_timezone
- name: WebChannelTransport
  file: src/sevn/gateway/web_transport.py
  symbol: WebChannelTransport
- name: WebSocketLike
  file: src/sevn/gateway/web_transport.py
  symbol: WebSocketLike
- name: consume_webapp_dispatcher_token
  file: src/sevn/gateway/webapp_qa.py
  symbol: consume_webapp_dispatcher_token
- name: insert_structured_feedback
  file: src/sevn/gateway/webapp_qa.py
  symbol: insert_structured_feedback
- name: load_webapp_dispatcher_payload
  file: src/sevn/gateway/webapp_qa.py
  symbol: load_webapp_dispatcher_payload
- name: maybe_log_qa_bar_webapp_disabled
  file: src/sevn/gateway/webapp_qa.py
  symbol: maybe_log_qa_bar_webapp_disabled
- name: mint_webapp_dispatcher_token
  file: src/sevn/gateway/webapp_qa.py
  symbol: mint_webapp_dispatcher_token
- name: quick_action_visibility
  file: src/sevn/gateway/webapp_qa.py
  symbol: quick_action_visibility
- name: resolve_thumbs_polarity
  file: src/sevn/gateway/webapp_qa.py
  symbol: resolve_thumbs_polarity
- name: resolve_thumbs_transition
  file: src/sevn/gateway/webapp_qa.py
  symbol: resolve_thumbs_transition
- name: resolve_webapp_public_base
  file: src/sevn/gateway/webapp_qa.py
  symbol: resolve_webapp_public_base
- name: webapp_https_disabled_notice
  file: src/sevn/gateway/webapp_qa.py
  symbol: webapp_https_disabled_notice
- name: webapp_inline_buttons_allowed
  file: src/sevn/gateway/webapp_qa.py
  symbol: webapp_inline_buttons_allowed
- name: append_viewer_stream_chunk
  file: src/sevn/gateway/webapp_viewer.py
  symbol: append_viewer_stream_chunk
- name: attach_inline_viewer_launch_buttons
  file: src/sevn/gateway/webapp_viewer.py
  symbol: attach_inline_viewer_launch_buttons
- name: build_chat_menu_webapp_request
  file: src/sevn/gateway/webapp_viewer.py
  symbol: build_chat_menu_webapp_request
- name: build_viewer_web_app_button
  file: src/sevn/gateway/webapp_viewer.py
  symbol: build_viewer_web_app_button
- name: build_viewer_webapp_url
  file: src/sevn/gateway/webapp_viewer.py
  symbol: build_viewer_webapp_url
- name: cast_viewer_kind
  file: src/sevn/gateway/webapp_viewer.py
  symbol: cast_viewer_kind
- name: evict_stale_viewer_streams
  file: src/sevn/gateway/webapp_viewer.py
  symbol: evict_stale_viewer_streams
- name: infer_viewer_payload_from_markdown
  file: src/sevn/gateway/webapp_viewer.py
  symbol: infer_viewer_payload_from_markdown
- name: load_webapp_viewer_payload
  file: src/sevn/gateway/webapp_viewer.py
  symbol: load_webapp_viewer_payload
- name: mark_viewer_stream_done
  file: src/sevn/gateway/webapp_viewer.py
  symbol: mark_viewer_stream_done
- name: mint_webapp_viewer_token
  file: src/sevn/gateway/webapp_viewer.py
  symbol: mint_webapp_viewer_token
- name: register_viewer_stream
  file: src/sevn/gateway/webapp_viewer.py
  symbol: register_viewer_stream
- name: sync_telegram_chat_menu_button
  file: src/sevn/gateway/webapp_viewer.py
  symbol: sync_telegram_chat_menu_button
- name: viewer_stream_snapshot
  file: src/sevn/gateway/webapp_viewer.py
  symbol: viewer_stream_snapshot
- name: webapp_share_to_story_enabled
  file: src/sevn/gateway/webapp_viewer.py
  symbol: webapp_share_to_story_enabled
- name: webapp_viewer_launch_allowed
  file: src/sevn/gateway/webapp_viewer.py
  symbol: webapp_viewer_launch_allowed
- name: del_nested
  file: src/sevn/gateway/workspace_config_io.py
  symbol: del_nested
- name: load_raw_sevn_json
  file: src/sevn/gateway/workspace_config_io.py
  symbol: load_raw_sevn_json
- name: mutate_sevn_json
  file: src/sevn/gateway/workspace_config_io.py
  symbol: mutate_sevn_json
- name: set_nested
  file: src/sevn/gateway/workspace_config_io.py
  symbol: set_nested
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Gateway — Spec (spec-17-gateway) — Purpose.

## Public Interface

Offline scaffold for Gateway — Spec (spec-17-gateway) — Public Interface.

## Data Model

Offline scaffold for Gateway — Spec (spec-17-gateway) — Data Model.

## Internal Architecture

Offline scaffold for Gateway — Spec (spec-17-gateway) — Internal Architecture.

## Behavior

Offline scaffold for Gateway — Spec (spec-17-gateway) — Behavior.

## Failure Modes

Offline scaffold for Gateway — Spec (spec-17-gateway) — Failure Modes.

## Amendments (spec-36-sub-agents)

`gateway.queue_mode` and per-channel `busy_input_mode` gain `"multi"`.
`session_manager.enqueue_dispatch` classifies busy input via relatedness labels
and may spawn concurrent L1 tier-B runs (`src/sevn/gateway/queue_multi.py`).
`routing_footer.py` tags parallel L1 replies with short sub-agent ids (D7).

## Test Strategy

Offline scaffold for Gateway — Spec (spec-17-gateway) — Test Strategy.
