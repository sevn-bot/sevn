---
id: spec-17-gateway
kind: spec
title: Gateway — Spec
status: done
owner: Alex
summary: Run the long-lived gateway process that accepts channel ingress (Telegram
  poll/webhook, webchat WS), normalises messages, enforces trust boundaries (scanner,
  rate limits), persists session history, an
last_updated: '2026-07-21'
fingerprint: sha256:db9260dc51010d540007139fd1086909adac795d62055b33b961fee13dec1fd3
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
- name: SlashAccessPolicy
  file: src/sevn/gateway/access/slash_access.py
  symbol: SlashAccessPolicy
- name: canonical_slash_command
  file: src/sevn/gateway/access/slash_access.py
  symbol: canonical_slash_command
- name: is_admin_slash_command
  file: src/sevn/gateway/access/slash_access.py
  symbol: is_admin_slash_command
- name: policy_for_message
  file: src/sevn/gateway/access/slash_access.py
  symbol: policy_for_message
- name: policy_from_channel_extra
  file: src/sevn/gateway/access/slash_access.py
  symbol: policy_from_channel_extra
- name: slash_allowed_for_actor
  file: src/sevn/gateway/access/slash_access.py
  symbol: slash_allowed_for_actor
- name: SecretDeleteBody
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: SecretDeleteBody
- name: SecretDeleteResponse
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: SecretDeleteResponse
- name: SecretEntryOut
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: SecretEntryOut
- name: SecretPutBody
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: SecretPutBody
- name: SecretPutResponse
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: SecretPutResponse
- name: SecretsListResponse
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: SecretsListResponse
- name: register_admin_secrets_routes
  file: src/sevn/gateway/admin/admin_secrets.py
  symbol: register_admin_secrets_routes
- name: build_agent_run_turn
  file: src/sevn/gateway/agent_turn.py
  symbol: build_agent_run_turn
- name: build_intro_extra_instructions
  file: src/sevn/gateway/agent_turn.py
  symbol: build_intro_extra_instructions
- name: turn_progress_signal_text
  file: src/sevn/gateway/agent_turn.py
  symbol: turn_progress_signal_text
- name: build_echo_run_turn
  file: src/sevn/gateway/api/e2e_echo.py
  symbol: build_echo_run_turn
- name: mount_gui_proxy
  file: src/sevn/gateway/api/gui_proxy.py
  symbol: mount_gui_proxy
- name: ChatCompletionRequest
  file: src/sevn/gateway/api/openai_compat_api.py
  symbol: ChatCompletionRequest
- name: ChatMessage
  file: src/sevn/gateway/api/openai_compat_api.py
  symbol: ChatMessage
- name: build_openai_compat_router
  file: src/sevn/gateway/api/openai_compat_api.py
  symbol: build_openai_compat_router
- name: register_openai_compat_routes
  file: src/sevn/gateway/api/openai_compat_api.py
  symbol: register_openai_compat_routes
- name: WebChannelTransport
  file: src/sevn/gateway/api/web_transport.py
  symbol: WebChannelTransport
- name: WebSocketLike
  file: src/sevn/gateway/api/web_transport.py
  symbol: WebSocketLike
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
  file: src/sevn/gateway/bootstrap/bootstrap_capture.py
  symbol: extract_bootstrap_name
- name: try_bootstrap_user_md_fallback
  file: src/sevn/gateway/bootstrap/bootstrap_capture.py
  symbol: try_bootstrap_user_md_fallback
- name: bootstrap_completion_state
  file: src/sevn/gateway/bootstrap/bootstrap_state.py
  symbol: bootstrap_completion_state
- name: operator_name_from_user_md
  file: src/sevn/gateway/bootstrap/bootstrap_state.py
  symbol: operator_name_from_user_md
- name: close_browser_for_rotate
  file: src/sevn/gateway/browser/browser_lifecycle.py
  symbol: close_browser_for_rotate
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
- name: CoreCommandReply
  file: src/sevn/gateway/commands/core_commands.py
  symbol: CoreCommandReply
- name: core_command_outbound
  file: src/sevn/gateway/commands/core_commands.py
  symbol: core_command_outbound
- name: DiagnosticCommandHandler
  file: src/sevn/gateway/commands/diagnostic_commands.py
  symbol: DiagnosticCommandHandler
- name: advance_discogs_oauth
  file: src/sevn/gateway/commands/discogs_oauth_wizard.py
  symbol: advance_discogs_oauth
- name: cleanup_discogs_oauth_interim_secrets
  file: src/sevn/gateway/commands/discogs_oauth_wizard.py
  symbol: cleanup_discogs_oauth_interim_secrets
- name: oauth_payload_has_no_secrets
  file: src/sevn/gateway/commands/discogs_oauth_wizard.py
  symbol: oauth_payload_has_no_secrets
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
- name: del_nested
  file: src/sevn/gateway/config_io/workspace_config_io.py
  symbol: del_nested
- name: load_raw_sevn_json
  file: src/sevn/gateway/config_io/workspace_config_io.py
  symbol: load_raw_sevn_json
- name: mutate_sevn_json
  file: src/sevn/gateway/config_io/workspace_config_io.py
  symbol: mutate_sevn_json
- name: set_nested
  file: src/sevn/gateway/config_io/workspace_config_io.py
  symbol: set_nested
- name: DashboardPinPublisher
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: DashboardPinPublisher
- name: dashboard_pin_topic_key
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: dashboard_pin_topic_key
- name: default_pin_keyboard
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: default_pin_keyboard
- name: default_pin_text
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: default_pin_text
- name: lookup_dashboard_pin_message_id
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: lookup_dashboard_pin_message_id
- name: register_dashboard_pin
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: register_dashboard_pin
- name: render_dashboard_pin
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: render_dashboard_pin
- name: unregister_dashboard_pin
  file: src/sevn/gateway/dashboard/dashboard_pin.py
  symbol: unregister_dashboard_pin
- name: format_for_telegram
  file: src/sevn/gateway/diagnostics/diagnostics.py
  symbol: format_for_telegram
- name: format_traces_for_telegram
  file: src/sevn/gateway/diagnostics/diagnostics.py
  symbol: format_traces_for_telegram
- name: get_span
  file: src/sevn/gateway/diagnostics/diagnostics.py
  symbol: get_span
- name: recent_traces
  file: src/sevn/gateway/diagnostics/diagnostics.py
  symbol: recent_traces
- name: tail_service_log
  file: src/sevn/gateway/diagnostics/diagnostics.py
  symbol: tail_service_log
- name: prune_dispatcher_callbacks
  file: src/sevn/gateway/dispatcher/dispatcher_callbacks.py
  symbol: prune_dispatcher_callbacks
- name: dispatcher_state_ttl_for_kind
  file: src/sevn/gateway/dispatcher/dispatcher_state.py
  symbol: dispatcher_state_ttl_for_kind
- name: insert_dispatcher_state
  file: src/sevn/gateway/dispatcher/dispatcher_state.py
  symbol: insert_dispatcher_state
- name: sweep_expired_dispatcher_state
  file: src/sevn/gateway/dispatcher/dispatcher_state.py
  symbol: sweep_expired_dispatcher_state
- name: EvolutionApprovalCallbackHandler
  file: src/sevn/gateway/evolution/evolution_approval_gate.py
  symbol: EvolutionApprovalCallbackHandler
- name: EvolutionApprovalWaitRegistry
  file: src/sevn/gateway/evolution/evolution_approval_gate.py
  symbol: EvolutionApprovalWaitRegistry
- name: build_evolution_approval_inline_keyboard
  file: src/sevn/gateway/evolution/evolution_approval_gate.py
  symbol: build_evolution_approval_inline_keyboard
- name: parse_evolution_callback_data
  file: src/sevn/gateway/evolution/evolution_approval_gate.py
  symbol: parse_evolution_callback_data
- name: EvolutionIssueEventFanout
  file: src/sevn/gateway/evolution/evolution_issue_events.py
  symbol: EvolutionIssueEventFanout
- name: GatewayEvent
  file: src/sevn/gateway/hooks/event_hooks.py
  symbol: GatewayEvent
- name: GatewayEventPayload
  file: src/sevn/gateway/hooks/event_hooks.py
  symbol: GatewayEventPayload
- name: clear_gateway_event_hooks
  file: src/sevn/gateway/hooks/event_hooks.py
  symbol: clear_gateway_event_hooks
- name: emit_gateway_event
  file: src/sevn/gateway/hooks/event_hooks.py
  symbol: emit_gateway_event
- name: register_gateway_event_hook
  file: src/sevn/gateway/hooks/event_hooks.py
  symbol: register_gateway_event_hook
- name: PostTurnContext
  file: src/sevn/gateway/hooks/post_turn_hooks.py
  symbol: PostTurnContext
- name: clear_post_turn_hooks
  file: src/sevn/gateway/hooks/post_turn_hooks.py
  symbol: clear_post_turn_hooks
- name: register_post_turn_hook
  file: src/sevn/gateway/hooks/post_turn_hooks.py
  symbol: register_post_turn_hook
- name: run_post_turn_hooks
  file: src/sevn/gateway/hooks/post_turn_hooks.py
  symbol: run_post_turn_hooks
- name: register_trajectory_ingest_hooks
  file: src/sevn/gateway/hooks/trajectory_ingest_hooks.py
  symbol: register_trajectory_ingest_hooks
- name: DeferredGatewayOnboardingRoute
  file: src/sevn/gateway/http_server.py
  symbol: DeferredGatewayOnboardingRoute
- name: create_app
  file: src/sevn/gateway/http_server.py
  symbol: create_app
- name: deferred_json
  file: src/sevn/gateway/http_server.py
  symbol: deferred_json
- name: handle_my_sevn_sync_cron_failure
  file: src/sevn/gateway/http_server.py
  symbol: handle_my_sevn_sync_cron_failure
- name: wait_for_proxy_boot_health
  file: src/sevn/gateway/http_server.py
  symbol: wait_for_proxy_boot_health
- name: ingest_gateway_message_row
  file: src/sevn/gateway/lcm/lcm_ingest.py
  symbol: ingest_gateway_message_row
- name: MediaStore
  file: src/sevn/gateway/media/media_store.py
  symbol: MediaStore
- name: build_discogs_keyboard_rows
  file: src/sevn/gateway/menu/discogs_menu.py
  symbol: build_discogs_keyboard_rows
- name: build_discogs_setup_keyboard_rows
  file: src/sevn/gateway/menu/discogs_menu.py
  symbol: build_discogs_setup_keyboard_rows
- name: discogs_menu_caption
  file: src/sevn/gateway/menu/discogs_menu.py
  symbol: discogs_menu_caption
- name: discogs_setup_caption
  file: src/sevn/gateway/menu/discogs_menu.py
  symbol: discogs_setup_caption
- name: ConfigMenuHandler
  file: src/sevn/gateway/menu/menu.py
  symbol: ConfigMenuHandler
- name: ConfigMenuNavFrame
  file: src/sevn/gateway/menu/menu.py
  symbol: ConfigMenuNavFrame
- name: ConfigMenuRefreshContext
  file: src/sevn/gateway/menu/menu.py
  symbol: ConfigMenuRefreshContext
- name: MenuCallbackHandler
  file: src/sevn/gateway/menu/menu.py
  symbol: MenuCallbackHandler
- name: MenuToolSurface
  file: src/sevn/gateway/menu/menu.py
  symbol: MenuToolSurface
- name: build_chat_menu_webapp_request
  file: src/sevn/gateway/menu/menu.py
  symbol: build_chat_menu_webapp_request
- name: build_config_menu_keyboard
  file: src/sevn/gateway/menu/menu.py
  symbol: build_config_menu_keyboard
- name: build_menu_keyboard
  file: src/sevn/gateway/menu/menu.py
  symbol: build_menu_keyboard
- name: build_service_restart_confirm_keyboard
  file: src/sevn/gateway/menu/menu.py
  symbol: build_service_restart_confirm_keyboard
- name: config_callback_matches
  file: src/sevn/gateway/menu/menu.py
  symbol: config_callback_matches
- name: config_menu_message_text
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_message_text
- name: config_menu_nav_clear
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_nav_clear
- name: config_menu_nav_go
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_nav_go
- name: config_menu_nav_home
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_nav_home
- name: config_menu_nav_key
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_nav_key
- name: config_menu_nav_pop
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_nav_pop
- name: config_menu_nav_push_current
  file: src/sevn/gateway/menu/menu.py
  symbol: config_menu_nav_push_current
- name: get_config_menu_nav
  file: src/sevn/gateway/menu/menu.py
  symbol: get_config_menu_nav
- name: infer_budget_regime
  file: src/sevn/gateway/menu/menu.py
  symbol: infer_budget_regime
- name: is_registered_config_menu_host
  file: src/sevn/gateway/menu/menu.py
  symbol: is_registered_config_menu_host
- name: menu_callback_matches
  file: src/sevn/gateway/menu/menu.py
  symbol: menu_callback_matches
- name: menu_message_text
  file: src/sevn/gateway/menu/menu.py
  symbol: menu_message_text
- name: parse_config_callback_data
  file: src/sevn/gateway/menu/menu.py
  symbol: parse_config_callback_data
- name: parse_menu_callback_data
  file: src/sevn/gateway/menu/menu.py
  symbol: parse_menu_callback_data
- name: parse_models_callback_data
  file: src/sevn/gateway/menu/menu.py
  symbol: parse_models_callback_data
- name: refresh_config_menu_message
  file: src/sevn/gateway/menu/menu.py
  symbol: refresh_config_menu_message
- name: service_restart_confirm_message
  file: src/sevn/gateway/menu/menu.py
  symbol: service_restart_confirm_message
- name: sync_telegram_chat_menu_button
  file: src/sevn/gateway/menu/menu.py
  symbol: sync_telegram_chat_menu_button
- name: web_ui_url_from_workspace
  file: src/sevn/gateway/menu/menu.py
  symbol: web_ui_url_from_workspace
- name: config_sevn_bot_section_title
  file: src/sevn/gateway/menu/menu_branding.py
  symbol: config_sevn_bot_section_title
- name: config_menu_help_catalog_text
  file: src/sevn/gateway/menu/menu_readiness.py
  symbol: config_menu_help_catalog_text
- name: config_menu_level_help_text
  file: src/sevn/gateway/menu/menu_readiness.py
  symbol: config_menu_level_help_text
- name: config_section_catalog
  file: src/sevn/gateway/menu/menu_readiness.py
  symbol: config_section_catalog
- name: gate_config_keyboard_rows
  file: src/sevn/gateway/menu/menu_readiness.py
  symbol: gate_config_keyboard_rows
- name: readiness_for_callback
  file: src/sevn/gateway/menu/menu_readiness.py
  symbol: readiness_for_callback
- name: readiness_user_label
  file: src/sevn/gateway/menu/menu_readiness.py
  symbol: readiness_user_label
- name: MenuButtonSpec
  file: src/sevn/gateway/menu/menu_registry.py
  symbol: MenuButtonSpec
- name: is_nav_chrome_callback
  file: src/sevn/gateway/menu/menu_registry.py
  symbol: is_nav_chrome_callback
- name: is_section_tile_callback
  file: src/sevn/gateway/menu/menu_registry.py
  symbol: is_section_tile_callback
- name: match_menu_button_spec
  file: src/sevn/gateway/menu/menu_registry.py
  symbol: match_menu_button_spec
- name: registry_implementation_counts
  file: src/sevn/gateway/menu/menu_registry.py
  symbol: registry_implementation_counts
- name: register_discogs_menu_entries
  file: src/sevn/gateway/menu/menu_registry_discogs.py
  symbol: register_discogs_menu_entries
- name: build_social_media_manager_keyboard_rows
  file: src/sevn/gateway/menu/social_media_manager_menu.py
  symbol: build_social_media_manager_keyboard_rows
- name: social_media_manager_menu_caption
  file: src/sevn/gateway/menu/social_media_manager_menu.py
  symbol: social_media_manager_menu_caption
- name: EmptyMissionControlState
  file: src/sevn/gateway/mission/mission_api.py
  symbol: EmptyMissionControlState
- name: create_mission_v1_router
  file: src/sevn/gateway/mission/mission_api.py
  symbol: create_mission_v1_router
- name: fetch_subagents_mission_payload
  file: src/sevn/gateway/mission/mission_api.py
  symbol: fetch_subagents_mission_payload
- name: kill_all_subagents_mission
  file: src/sevn/gateway/mission/mission_api.py
  symbol: kill_all_subagents_mission
- name: kill_subagent_mission
  file: src/sevn/gateway/mission/mission_api.py
  symbol: kill_subagent_mission
- name: resolve_mission_control_state
  file: src/sevn/gateway/mission/mission_api.py
  symbol: resolve_mission_control_state
- name: MissionControlState
  file: src/sevn/gateway/mission/mission_state.py
  symbol: MissionControlState
- name: AgentActivity
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: AgentActivity
- name: Alert
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: Alert
- name: AlertRule
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: AlertRule
- name: ChannelHealth
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: ChannelHealth
- name: NotificationTarget
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: NotificationTarget
- name: ProviderHealth
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: ProviderHealth
- name: SessionMissionStats
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: SessionMissionStats
- name: event_timestamp
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: event_timestamp
- name: is_channel_trace_kind
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: is_channel_trace_kind
- name: is_mission_telemetry_kind
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: is_mission_telemetry_kind
- name: normalize_complexity
  file: src/sevn/gateway/mission/mission_state_models.py
  symbol: normalize_complexity
- name: MissionControlSnapshotsMixin
  file: src/sevn/gateway/mission/mission_state_snapshots.py
  symbol: MissionControlSnapshotsMixin
- name: build_subagents_mission_snapshot
  file: src/sevn/gateway/mission/mission_subagents_snapshot.py
  symbol: build_subagents_mission_snapshot
- name: MissionControlTraceSink
  file: src/sevn/gateway/mission/mission_trace_sink.py
  symbol: MissionControlTraceSink
- name: create_mission_trace_sink
  file: src/sevn/gateway/mission/mission_trace_sink.py
  symbol: create_mission_trace_sink
- name: detach_mission_trace_sink
  file: src/sevn/gateway/mission/mission_trace_sink.py
  symbol: detach_mission_trace_sink
- name: resolve_mission_control_state
  file: src/sevn/gateway/mission/mission_trace_sink.py
  symbol: resolve_mission_control_state
- name: bootstrap_capture_active
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: bootstrap_capture_active
- name: bootstrap_capture_instructions
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: bootstrap_capture_instructions
- name: bootstrap_completion_state
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: bootstrap_completion_state
- name: clear_bootstrap_markdown_cache
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: clear_bootstrap_markdown_cache
- name: clear_intro_state_cache
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: clear_intro_state_cache
- name: count_user_messages
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: count_user_messages
- name: count_user_messages_in_session
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: count_user_messages_in_session
- name: first_session_intro_enabled
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: first_session_intro_enabled
- name: first_session_intro_max_output_tokens
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: first_session_intro_max_output_tokens
- name: intro_state_for_scope
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: intro_state_for_scope
- name: intro_state_for_session
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: intro_state_for_session
- name: is_first_session_turn
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: is_first_session_turn
- name: load_bootstrap_markdown
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: load_bootstrap_markdown
- name: load_bootstrap_markdown_cached
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: load_bootstrap_markdown_cached
- name: mark_intro_state
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: mark_intro_state
- name: maybe_mark_intro_done_if_bootstrap_complete
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: maybe_mark_intro_done_if_bootstrap_complete
- name: maybe_reseed_bootstrap_at_boot
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: maybe_reseed_bootstrap_at_boot
- name: missing_user_md_bootstrap_fields
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: missing_user_md_bootstrap_fields
- name: tier_b_intro_instructions
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: tier_b_intro_instructions
- name: user_md_bootstrap_profile_incomplete
  file: src/sevn/gateway/onboarding/first_session.py
  symbol: user_md_bootstrap_profile_incomplete
- name: mount_gateway_onboarding
  file: src/sevn/gateway/onboarding/onboarding_mount.py
  symbol: mount_gateway_onboarding
- name: resolve_gateway_onboarding_token
  file: src/sevn/gateway/onboarding/onboarding_mount.py
  symbol: resolve_gateway_onboarding_token
- name: PairingStore
  file: src/sevn/gateway/onboarding/pairing.py
  symbol: PairingStore
- name: pairing_dir_for_content_root
  file: src/sevn/gateway/onboarding/pairing.py
  symbol: pairing_dir_for_content_root
- name: CascadeBudget
  file: src/sevn/gateway/queue/cascade_budget.py
  symbol: CascadeBudget
- name: MultiDispatchHooks
  file: src/sevn/gateway/queue/queue_multi.py
  symbol: MultiDispatchHooks
- name: MultiSpawnOutcome
  file: src/sevn/gateway/queue/queue_multi.py
  symbol: MultiSpawnOutcome
- name: in_flight_task_summary_for_session
  file: src/sevn/gateway/queue/queue_multi.py
  symbol: in_flight_task_summary_for_session
- name: spawn_multi_l1_via_supervisor
  file: src/sevn/gateway/queue/queue_multi.py
  symbol: spawn_multi_l1_via_supervisor
- name: SessionBoundSteerInject
  file: src/sevn/gateway/queue/steer_store.py
  symbol: SessionBoundSteerInject
- name: SessionSteerStore
  file: src/sevn/gateway/queue/steer_store.py
  symbol: SessionSteerStore
- name: SteerEnqueueResult
  file: src/sevn/gateway/queue/steer_store.py
  symbol: SteerEnqueueResult
- name: owner_user_ids_from_workspace
  file: src/sevn/gateway/queue/steer_store.py
  symbol: owner_user_ids_from_workspace
- name: parse_steer_command_text
  file: src/sevn/gateway/queue/steer_store.py
  symbol: parse_steer_command_text
- name: ReplayJobEventFanout
  file: src/sevn/gateway/replay/replay_job_events.py
  symbol: ReplayJobEventFanout
- name: ReplayJobEventFanoutFn
  file: src/sevn/gateway/replay/replay_job_events.py
  symbol: ReplayJobEventFanoutFn
- name: ReplayJobEventPayload
  file: src/sevn/gateway/replay/replay_job_events.py
  symbol: ReplayJobEventPayload
- name: replay_ws_topic
  file: src/sevn/gateway/replay/replay_job_events.py
  symbol: replay_ws_topic
- name: lookup_user_text_for_turn
  file: src/sevn/gateway/replay/replay_turn_lookup.py
  symbol: lookup_user_text_for_turn
- name: ReplayJobRequest
  file: src/sevn/gateway/replay/replay_worker.py
  symbol: ReplayJobRequest
- name: TurnReplayWorker
  file: src/sevn/gateway/replay/replay_worker.py
  symbol: TurnReplayWorker
- name: register_replay_worker_hooks
  file: src/sevn/gateway/replay/replay_worker_hooks.py
  symbol: register_replay_worker_hooks
- name: CodingAgentRouter
  file: src/sevn/gateway/routing/coding_agent_router.py
  symbol: CodingAgentRouter
- name: sweep_outbound_retries
  file: src/sevn/gateway/routing/outbound_sweep.py
  symbol: sweep_outbound_retries
- name: PlanGateCallbackHandler
  file: src/sevn/gateway/routing/plan_gate.py
  symbol: PlanGateCallbackHandler
- name: PlanGateWaitRegistry
  file: src/sevn/gateway/routing/plan_gate.py
  symbol: PlanGateWaitRegistry
- name: SqlitePlanGate
  file: src/sevn/gateway/routing/plan_gate.py
  symbol: SqlitePlanGate
- name: build_plan_inline_keyboard
  file: src/sevn/gateway/routing/plan_gate.py
  symbol: build_plan_inline_keyboard
- name: format_plan_message_text
  file: src/sevn/gateway/routing/plan_gate.py
  symbol: format_plan_message_text
- name: parse_plan_callback_data
  file: src/sevn/gateway/routing/plan_gate.py
  symbol: parse_plan_callback_data
- name: is_intentional_silence_agent_result
  file: src/sevn/gateway/routing/response_filters.py
  symbol: is_intentional_silence_agent_result
- name: is_intentional_silence_response
  file: src/sevn/gateway/routing/response_filters.py
  symbol: is_intentional_silence_response
- name: append_routing_footer
  file: src/sevn/gateway/routing/routing_footer.py
  symbol: append_routing_footer
- name: format_routing_footer
  file: src/sevn/gateway/routing/routing_footer.py
  symbol: format_routing_footer
- name: format_subagent_tag
  file: src/sevn/gateway/routing/routing_footer.py
  symbol: format_subagent_tag
- name: strip_model_emitted_footer
  file: src/sevn/gateway/routing/routing_footer.py
  symbol: strip_model_emitted_footer
- name: telegram_show_routing_enabled
  file: src/sevn/gateway/routing/routing_footer.py
  symbol: telegram_show_routing_enabled
- name: load_or_create_deployment_id
  file: src/sevn/gateway/runtime/deployment_id.py
  symbol: load_or_create_deployment_id
- name: PendingGatewayRestart
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: PendingGatewayRestart
- name: claim_pending_gateway_restarts
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: claim_pending_gateway_restarts
- name: clear_pending_gateway_restarts
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: clear_pending_gateway_restarts
- name: conversation_snapshot_for_session
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: conversation_snapshot_for_session
- name: deliver_pending_gateway_restart_acks
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: deliver_pending_gateway_restart_acks
- name: has_pending_gateway_restart
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: has_pending_gateway_restart
- name: load_pending_gateway_restarts
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: load_pending_gateway_restarts
- name: mark_restart_ack_delivered
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: mark_restart_ack_delivered
- name: pending_restart_store_path
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: pending_restart_store_path
- name: recent_restart_ack_delivered
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: recent_restart_ack_delivered
- name: record_pending_gateway_restart
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: record_pending_gateway_restart
- name: restart_ack_delivered_path
  file: src/sevn/gateway/runtime/gateway_restart_ack.py
  symbol: restart_ack_delivered_path
- name: generate_gateway_token
  file: src/sevn/gateway/runtime/gateway_token.py
  symbol: generate_gateway_token
- name: resolve_config_ref
  file: src/sevn/gateway/runtime/gateway_token.py
  symbol: resolve_config_ref
- name: resolve_gateway_token_ref
  file: src/sevn/gateway/runtime/gateway_token.py
  symbol: resolve_gateway_token_ref
- name: validate_gateway_token_plaintext
  file: src/sevn/gateway/runtime/gateway_token.py
  symbol: validate_gateway_token_plaintext
- name: PlatformRuntimeRegistry
  file: src/sevn/gateway/runtime/platform_runtime.py
  symbol: PlatformRuntimeRegistry
- name: PlatformRuntimeState
  file: src/sevn/gateway/runtime/platform_runtime.py
  symbol: PlatformRuntimeState
- name: render_gateway_metrics
  file: src/sevn/gateway/runtime/prometheus_metrics.py
  symbol: render_gateway_metrics
- name: TokenBucketLimiter
  file: src/sevn/gateway/runtime/rate_limit.py
  symbol: TokenBucketLimiter
- name: release_leaked_multiprocessing_semaphores
  file: src/sevn/gateway/runtime/shutdown_cleanup.py
  symbol: release_leaked_multiprocessing_semaphores
- name: register_telemetry_boot_hooks
  file: src/sevn/gateway/runtime/telemetry_boot.py
  symbol: register_telemetry_boot_hooks
- name: SelfImproveJobEventFanout
  file: src/sevn/gateway/self_improve/self_improve_job_events.py
  symbol: SelfImproveJobEventFanout
- name: resolve_owner_telegram_user_id
  file: src/sevn/gateway/self_improve/self_improve_job_events.py
  symbol: resolve_owner_telegram_user_id
- name: SessionPathNameLookup
  file: src/sevn/gateway/session/path_names.py
  symbol: SessionPathNameLookup
- name: SessionPathNameResolver
  file: src/sevn/gateway/session/path_names.py
  symbol: SessionPathNameResolver
- name: chat_path_segment
  file: src/sevn/gateway/session/path_names.py
  symbol: chat_path_segment
- name: coerce_name_lookup
  file: src/sevn/gateway/session/path_names.py
  symbol: coerce_name_lookup
- name: format_named_path_segment
  file: src/sevn/gateway/session/path_names.py
  symbol: format_named_path_segment
- name: parse_telegram_scope_rel
  file: src/sevn/gateway/session/path_names.py
  symbol: parse_telegram_scope_rel
- name: safe_path_segment
  file: src/sevn/gateway/session/path_names.py
  symbol: safe_path_segment
- name: topic_path_segment
  file: src/sevn/gateway/session/path_names.py
  symbol: topic_path_segment
- name: mark_session_superseded
  file: src/sevn/gateway/session/session_mirror.py
  symbol: mark_session_superseded
- name: mirror_gateway_message
  file: src/sevn/gateway/session/session_mirror.py
  symbol: mirror_gateway_message
- name: session_mirror_enabled
  file: src/sevn/gateway/session/session_mirror.py
  symbol: session_mirror_enabled
- name: SessionResetPolicy
  file: src/sevn/gateway/session/session_reset.py
  symbol: SessionResetPolicy
- name: resolve_session_reset_policy
  file: src/sevn/gateway/session/session_reset.py
  symbol: resolve_session_reset_policy
- name: session_should_reset
  file: src/sevn/gateway/session/session_reset.py
  symbol: session_should_reset
- name: can_access_session
  file: src/sevn/gateway/session/sessions_query.py
  symbol: can_access_session
- name: cap_history_limit
  file: src/sevn/gateway/session/sessions_query.py
  symbol: cap_history_limit
- name: fetch_session_history
  file: src/sevn/gateway/session/sessions_query.py
  symbol: fetch_session_history
- name: insert_message
  file: src/sevn/gateway/session/sessions_query.py
  symbol: insert_message
- name: list_sessions
  file: src/sevn/gateway/session/sessions_query.py
  symbol: list_sessions
- name: list_sessions_active_between
  file: src/sevn/gateway/session/sessions_query.py
  symbol: list_sessions_active_between
- name: parse_session_metadata
  file: src/sevn/gateway/session/sessions_query.py
  symbol: parse_session_metadata
- name: record_yield
  file: src/sevn/gateway/session/sessions_query.py
  symbol: record_yield
- name: search_messages
  file: src/sevn/gateway/session/sessions_query.py
  symbol: search_messages
- name: send_to_session
  file: src/sevn/gateway/session/sessions_query.py
  symbol: send_to_session
- name: session_operator_timezone
  file: src/sevn/gateway/session/sessions_query.py
  symbol: session_operator_timezone
- name: session_status_snapshot
  file: src/sevn/gateway/session/sessions_query.py
  symbol: session_status_snapshot
- name: spawn_subagent
  file: src/sevn/gateway/session/sessions_query.py
  symbol: spawn_subagent
- name: SessionManager
  file: src/sevn/gateway/session_manager.py
  symbol: SessionManager
- name: SessionRow
  file: src/sevn/gateway/session_manager.py
  symbol: SessionRow
- name: clear_dispatch_routing
  file: src/sevn/gateway/session_manager.py
  symbol: clear_dispatch_routing
- name: dispatch_routing_for
  file: src/sevn/gateway/session_manager.py
  symbol: dispatch_routing_for
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
- name: merge_dispatch_routing
  file: src/sevn/gateway/session_manager.py
  symbol: merge_dispatch_routing
- name: outbound_routing_for_session
  file: src/sevn/gateway/session_manager.py
  symbol: outbound_routing_for_session
- name: set_tts_mode_override
  file: src/sevn/gateway/session_manager.py
  symbol: set_tts_mode_override
- name: unanswered_tail_message_id
  file: src/sevn/gateway/session_manager.py
  symbol: unanswered_tail_message_id
- name: validate_dispatch_routing_identity
  file: src/sevn/gateway/session_manager.py
  symbol: validate_dispatch_routing_identity
- name: build_announce_back_hook
  file: src/sevn/gateway/subagents/subagents_announce.py
  symbol: build_announce_back_hook
- name: register_subagents_boot_hook
  file: src/sevn/gateway/subagents/subagents_boot.py
  symbol: register_subagents_boot_hook
- name: build_stop_l1_keyboard
  file: src/sevn/gateway/subagents/surfaces.py
  symbol: build_stop_l1_keyboard
- name: build_subagent_kill_keyboard_rows
  file: src/sevn/gateway/subagents/surfaces.py
  symbol: build_subagent_kill_keyboard_rows
- name: format_running_agents_inventory
  file: src/sevn/gateway/subagents/surfaces.py
  symbol: format_running_agents_inventory
- name: stop_l1_button_label
  file: src/sevn/gateway/subagents/surfaces.py
  symbol: stop_l1_button_label
- name: subagent_kill_button_label_config
  file: src/sevn/gateway/subagents/surfaces.py
  symbol: subagent_kill_button_label_config
- name: subagent_menu_snapshot_from_router
  file: src/sevn/gateway/subagents/surfaces.py
  symbol: subagent_menu_snapshot_from_router
- name: dispatch_telegram_inline_query
  file: src/sevn/gateway/telegram/telegram_inline.py
  symbol: dispatch_telegram_inline_query
- name: handle_chosen_inline_result_feedback
  file: src/sevn/gateway/telegram/telegram_inline.py
  symbol: handle_chosen_inline_result_feedback
- name: maybe_emit_botfather_inline_warning
  file: src/sevn/gateway/telegram/telegram_inline.py
  symbol: maybe_emit_botfather_inline_warning
- name: try_route_telegram_inline
  file: src/sevn/gateway/telegram/telegram_inline.py
  symbol: try_route_telegram_inline
- name: build_agent_inline_results
  file: src/sevn/gateway/telegram/telegram_inline_agent.py
  symbol: build_agent_inline_results
- name: capture_router_outbound_text
  file: src/sevn/gateway/telegram/telegram_inline_agent.py
  symbol: capture_router_outbound_text
- name: make_run_turn_agent_answer_fn
  file: src/sevn/gateway/telegram/telegram_inline_agent.py
  symbol: make_run_turn_agent_answer_fn
- name: InlineArticleResult
  file: src/sevn/gateway/telegram/telegram_inline_base.py
  symbol: InlineArticleResult
- name: InlineBuildContext
  file: src/sevn/gateway/telegram/telegram_inline_base.py
  symbol: InlineBuildContext
- name: InlineInputMessageContent
  file: src/sevn/gateway/telegram/telegram_inline_base.py
  symbol: InlineInputMessageContent
- name: InlineSourceResult
  file: src/sevn/gateway/telegram/telegram_inline_base.py
  symbol: InlineSourceResult
- name: inline_article_result
  file: src/sevn/gateway/telegram/telegram_inline_base.py
  symbol: inline_article_result
- name: build_answer_inline_query_payload
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: build_answer_inline_query_payload
- name: build_inline_input_message_content
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: build_inline_input_message_content
- name: compute_inline_answer_cache_time
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: compute_inline_answer_cache_time
- name: dedupe_inline_results
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: dedupe_inline_results
- name: is_inline_botfather_setup_error
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: is_inline_botfather_setup_error
- name: paginate_inline_results
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: paginate_inline_results
- name: parse_inline_result_offset
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: parse_inline_result_offset
- name: sanitize_inline_results_for_api
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: sanitize_inline_results_for_api
- name: upgrade_inline_results_for_capability
  file: src/sevn/gateway/telegram/telegram_inline_dispatch.py
  symbol: upgrade_inline_results_for_capability
- name: build_printing_press_inline_results
  file: src/sevn/gateway/telegram/telegram_inline_printing_press.py
  symbol: build_printing_press_inline_results
- name: build_all_inline_source_results
  file: src/sevn/gateway/telegram/telegram_inline_sources.py
  symbol: build_all_inline_source_results
- name: build_artifacts_inline_results
  file: src/sevn/gateway/telegram/telegram_inline_sources.py
  symbol: build_artifacts_inline_results
- name: build_second_brain_inline_results
  file: src/sevn/gateway/telegram/telegram_inline_sources.py
  symbol: build_second_brain_inline_results
- name: inline_sources_module_ready
  file: src/sevn/gateway/telegram/telegram_inline_sources.py
  symbol: inline_sources_module_ready
- name: merge_inline_query_results
  file: src/sevn/gateway/telegram/telegram_inline_sources.py
  symbol: merge_inline_query_results
- name: InlineAuthContext
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: InlineAuthContext
- name: InlineDispatchContext
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: InlineDispatchContext
- name: build_inline_dispatch_context
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: build_inline_dispatch_context
- name: inline_source_cache_time
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: inline_source_cache_time
- name: inline_user_may_use_agent_source
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: inline_user_may_use_agent_source
- name: resolve_inline_config
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: resolve_inline_config
- name: telegram_allowed_updates
  file: src/sevn/gateway/telegram/telegram_inline_types.py
  symbol: telegram_allowed_updates
- name: QuickActionCallbackHandler
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: QuickActionCallbackHandler
- name: build_quick_action_inline_keyboard
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: build_quick_action_inline_keyboard
- name: is_telegram_fast_callback_ack
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: is_telegram_fast_callback_ack
- name: lookup_assistant_row_by_platform_message
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: lookup_assistant_row_by_platform_message
- name: lookup_origin_user_text_for_assistant
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: lookup_origin_user_text_for_assistant
- name: parse_qa_callback_data
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: parse_qa_callback_data
- name: record_assistant_platform_message
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: record_assistant_platform_message
- name: telegram_fast_callback_ack_text
  file: src/sevn/gateway/telegram/telegram_quick_actions.py
  symbol: telegram_fast_callback_ack_text
- name: resolve_telegram_bot_token
  file: src/sevn/gateway/telegram/telegram_resolve.py
  symbol: resolve_telegram_bot_token
- name: ensure_webhook_secret_token
  file: src/sevn/gateway/telegram/telegram_webhook_secret.py
  symbol: ensure_webhook_secret_token
- name: persist_triage_decision
  file: src/sevn/gateway/triage/triage_audit.py
  symbol: persist_triage_decision
- name: group_triage_block_would_inject
  file: src/sevn/gateway/triage/triage_context.py
  symbol: group_triage_block_would_inject
- name: is_triager_enabled
  file: src/sevn/gateway/triage/triage_context.py
  symbol: is_triager_enabled
- name: latest_prior_triage_result
  file: src/sevn/gateway/triage/triage_context.py
  symbol: latest_prior_triage_result
- name: lcm_summary_stub_for_session
  file: src/sevn/gateway/triage/triage_context.py
  symbol: lcm_summary_stub_for_session
- name: load_workspace_personality
  file: src/sevn/gateway/triage/triage_context.py
  symbol: load_workspace_personality
- name: passthrough_triage_result
  file: src/sevn/gateway/triage/triage_context.py
  symbol: passthrough_triage_result
- name: registry_snapshot_from_tool_set
  file: src/sevn/gateway/triage/triage_context.py
  symbol: registry_snapshot_from_tool_set
- name: session_view_from_session
  file: src/sevn/gateway/triage/triage_context.py
  symbol: session_view_from_session
- name: tier_b_personality_instructions
  file: src/sevn/gateway/triage/triage_context.py
  symbol: tier_b_personality_instructions
- name: triage_context_from_session
  file: src/sevn/gateway/triage/triage_context.py
  symbol: triage_context_from_session
- name: window_transcript
  file: src/sevn/gateway/triage/triage_context.py
  symbol: window_transcript
- name: TurnBundleIndex
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundleIndex
- name: TurnBundleIndexEntry
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundleIndexEntry
- name: TurnBundleLogRecord
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundleLogRecord
- name: TurnBundleMessageRecord
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundleMessageRecord
- name: TurnBundleMetaRecord
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundleMetaRecord
- name: TurnBundlePaths
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundlePaths
- name: TurnBundleTraceRecord
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnBundleTraceRecord
- name: TurnExportCandidate
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: TurnExportCandidate
- name: bundle_paths
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: bundle_paths
- name: bundle_record_is_error
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: bundle_record_is_error
- name: collect_turn_bundle_records
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: collect_turn_bundle_records
- name: compute_has_error
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: compute_has_error
- name: effective_turn_bundles_enabled
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: effective_turn_bundles_enabled
- name: export_turn_bundles
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: export_turn_bundles
- name: format_turn_bundle_record
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: format_turn_bundle_record
- name: format_turn_bundle_summary
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: format_turn_bundle_summary
- name: list_turn_export_candidates
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: list_turn_export_candidates
- name: load_turn_bundle_index
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: load_turn_bundle_index
- name: load_turn_bundle_records
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: load_turn_bundle_records
- name: log_line_matches_turn
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: log_line_matches_turn
- name: parse_channel_from_turn_id
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: parse_channel_from_turn_id
- name: parse_since_timestamp
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: parse_since_timestamp
- name: resolve_turn_bundle_file
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: resolve_turn_bundle_file
- name: resolve_turn_terminal_status
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: resolve_turn_terminal_status
- name: safe_turn_id
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: safe_turn_id
- name: turn_log_grep_needles
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: turn_log_grep_needles
- name: turn_msg_hex_suffix
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: turn_msg_hex_suffix
- name: upsert_turn_bundle_index_entry
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: upsert_turn_bundle_index_entry
- name: view_turn_bundle
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: view_turn_bundle
- name: write_turn_bundle
  file: src/sevn/gateway/turn/turn_bundle.py
  symbol: write_turn_bundle
- name: register_turn_bundle_hooks
  file: src/sevn/gateway/turn/turn_bundle_hooks.py
  symbol: register_turn_bundle_hooks
- name: TierBAnswerFinalizer
  file: src/sevn/gateway/turn/turn_finalizer.py
  symbol: TierBAnswerFinalizer
- name: TurnMediaItem
  file: src/sevn/gateway/turn/turn_media.py
  symbol: TurnMediaItem
- name: attachment_hints_for_triager
  file: src/sevn/gateway/turn/turn_media.py
  symbol: attachment_hints_for_triager
- name: build_turn_media_summaries
  file: src/sevn/gateway/turn/turn_media.py
  symbol: build_turn_media_summaries
- name: hydrate_turn_media
  file: src/sevn/gateway/turn/turn_media.py
  symbol: hydrate_turn_media
- name: infer_modality_flags
  file: src/sevn/gateway/turn/turn_media.py
  symbol: infer_modality_flags
- name: load_turn_media_summaries
  file: src/sevn/gateway/turn/turn_media.py
  symbol: load_turn_media_summaries
- name: TurnMetadata
  file: src/sevn/gateway/turn/turn_metadata.py
  symbol: TurnMetadata
- name: format_intent_footer_from_metadata
  file: src/sevn/gateway/turn/turn_metadata.py
  symbol: format_intent_footer_from_metadata
- name: load_turn_metadata
  file: src/sevn/gateway/turn/turn_metadata.py
  symbol: load_turn_metadata
- name: record_turn_finished
  file: src/sevn/gateway/turn/turn_metadata.py
  symbol: record_turn_finished
- name: record_turn_start
  file: src/sevn/gateway/turn/turn_metadata.py
  symbol: record_turn_start
- name: register_user_model_hooks
  file: src/sevn/gateway/user/user_model_hooks.py
  symbol: register_user_model_hooks
- name: lookup_user_text_for_turn
  file: src/sevn/gateway/user/user_model_turn.py
  symbol: lookup_user_text_for_turn
- name: maybe_schedule_user_model_extraction_after_turn
  file: src/sevn/gateway/user/user_model_turn.py
  symbol: maybe_schedule_user_model_extraction_after_turn
- name: UserProfile
  file: src/sevn/gateway/user/user_profile.py
  symbol: UserProfile
- name: get_user_profile
  file: src/sevn/gateway/user/user_profile.py
  symbol: get_user_profile
- name: set_user_language_code
  file: src/sevn/gateway/user/user_profile.py
  symbol: set_user_language_code
- name: set_user_timezone
  file: src/sevn/gateway/user/user_profile.py
  symbol: set_user_timezone
- name: redact_inline
  file: src/sevn/gateway/util/redact.py
  symbol: redact_inline
- name: blocked_inbound_user_message
  file: src/sevn/gateway/util/strings.py
  symbol: blocked_inbound_user_message
- name: operator_local_date_iso
  file: src/sevn/gateway/util/timestamps.py
  symbol: operator_local_date_iso
- name: resolve_time_range
  file: src/sevn/gateway/util/timestamps.py
  symbol: resolve_time_range
- name: to_user_tz
  file: src/sevn/gateway/util/timestamps.py
  symbol: to_user_tz
- name: consume_webapp_dispatcher_token
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: consume_webapp_dispatcher_token
- name: insert_structured_feedback
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: insert_structured_feedback
- name: load_webapp_dispatcher_payload
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: load_webapp_dispatcher_payload
- name: maybe_log_qa_bar_webapp_disabled
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: maybe_log_qa_bar_webapp_disabled
- name: mint_webapp_dispatcher_token
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: mint_webapp_dispatcher_token
- name: quick_action_visibility
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: quick_action_visibility
- name: resolve_thumbs_polarity
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: resolve_thumbs_polarity
- name: resolve_thumbs_transition
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: resolve_thumbs_transition
- name: resolve_webapp_public_base
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: resolve_webapp_public_base
- name: webapp_https_disabled_notice
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: webapp_https_disabled_notice
- name: webapp_inline_buttons_allowed
  file: src/sevn/gateway/webapp/webapp_qa.py
  symbol: webapp_inline_buttons_allowed
- name: append_viewer_stream_chunk
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: append_viewer_stream_chunk
- name: attach_inline_viewer_launch_buttons
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: attach_inline_viewer_launch_buttons
- name: build_chat_menu_webapp_request
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: build_chat_menu_webapp_request
- name: build_viewer_web_app_button
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: build_viewer_web_app_button
- name: build_viewer_webapp_url
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: build_viewer_webapp_url
- name: cast_viewer_kind
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: cast_viewer_kind
- name: evict_stale_viewer_streams
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: evict_stale_viewer_streams
- name: infer_viewer_payload_from_markdown
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: infer_viewer_payload_from_markdown
- name: load_webapp_viewer_payload
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: load_webapp_viewer_payload
- name: mark_viewer_stream_done
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: mark_viewer_stream_done
- name: mint_webapp_viewer_token
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: mint_webapp_viewer_token
- name: register_viewer_stream
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: register_viewer_stream
- name: sync_telegram_chat_menu_button
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: sync_telegram_chat_menu_button
- name: viewer_stream_snapshot
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: viewer_stream_snapshot
- name: webapp_share_to_story_enabled
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: webapp_share_to_story_enabled
- name: webapp_viewer_launch_allowed
  file: src/sevn/gateway/webapp/webapp_viewer.py
  symbol: webapp_viewer_launch_allowed
---

## Purpose

Run the long-lived **gateway** process: accept channel ingress (Telegram poll/webhook,
webchat WebSocket), normalize messages, enforce trust boundaries, persist session
history, dispatch the agent turn spine (triager → tier executors), and deliver outbound
replies. This spec is the normative home for session queue semantics, turn finalization,
and channel routing.

## Public Interface

| Symbol | Module | Role |
|--------|--------|------|
| `build_agent_run_turn` | `src/sevn/gateway/agent_turn.py` | Turn factory → `RunTurnFn` |
| `SessionManager` | `src/sevn/gateway/session_manager.py` | Per-session queue + worker |
| `ChannelRouter` | `src/sevn/gateway/channel_router.py` | Ingress/egress routing |
| `IncomingMessage` / `OutgoingMessage` | `src/sevn/gateway/channel_types.py` | Channel envelopes |
| `triage_context_from_session` | `src/sevn/gateway/triage/triage_context.py` | Triager inputs |
| `CascadeBudget` | `src/sevn/gateway/queue/cascade_budget.py` | Tier-B retry budget |
| `TierBAnswerFinalizer` | `src/sevn/gateway/turn/turn_finalizer.py` | Placeholder/edit dance |
| HTTP lifespan | `src/sevn/gateway/http_server.py` | ASGI server boot |

Amendments from spec-36: `queue_mode`/`busy_input_mode` `"multi"`, relatedness classify,
routing footers for parallel L1 replies — see **Behavior**.

## Data Model

### Session queue

Per-session: message queue, active dispatch task, regen/replay targets, cancel
supersede timestamps, multi-queue summaries, global turn semaphore.

### Queue modes (`enqueue_dispatch`)

| Mode | Behavior |
|------|----------|
| `cancel` | Supersede in-flight turn |
| `steer` | Inject into running tier-B turn |
| `queue` | FIFO wait |
| `multi` | Classify busy input → steer / supersede / spawn new L1 tier-B |

### Turn states

Persisted in storage + JSONL session mirror; spans under `gateway.turn.*` and
`gateway.triage.completed`.

## Internal Architecture

```text
Channel adapter → ChannelRouter.route_incoming
    → SessionManager.enqueue_dispatch → _session_worker
    → build_agent_run_turn._run_guarded → _run
        → triage_turn | passthrough
        → tier A | run_b_turn | run_cd_turn
    → ChannelRouter outbound (+ TierBAnswerFinalizer)
```

Sub-agent L1 registration/finalize hooks in `_run_guarded` (spec-36).

## Behavior

1. **`_run`** loads session, resolves user text (replay/regen/backref/burst merge).
2. Triager when enabled; early exit on `disregard`, identity/list-tools shortcuts.
3. Emit `first_message` — tier A final; B/C/D persist opener (+ optional routing footer).
4. Tier B cascade: narrow → summarize retry → full-index retry → escalate to C.
5. Grounding guard + `TierBAnswerFinalizer`; no-answer fallback on failures.
6. **`multi` mode:** `classify_busy_relatedness` with timeout fallback to steer.
7. **Slow turns:** `_schedule_turn_progress_signal` routes `turn_progress_signal_text()`
   ("Still working…") after the progress delay so channels are not left in dead-air.
8. **Stage latency:** `_record_turn_stage_latencies` pushes samples into Mission Control when
   wired; when MC is missing it logs `agent_turn_stage_latency_unwired` (debug) instead of
   silently dropping attribution.
9. **Menu-action callbacks:** `MenuActionRouter._answer_callback` answers via production
   `answer_callback` (legacy `answer_callback_query` / `_api` fallbacks); identity toasts
   (`cfg:logs:version_id` / `deployment_id`) fall back to chat text when the inline answer fails.

## Failure Modes

| Condition | Handling |
|-----------|----------|
| Missing session / empty user text | Log + return |
| `TriagerUnavailable` | User fallback message |
| Cancel supersession | `cancelled_by_new_message` no-answer (unless replacement queued) |
| Unhandled exception | `_run_guarded` catch-all fallback |
| Tier B timeout / budget exhausted | `_emit_no_answer_fallback` |
| CD dispatch failure | No-answer + optional re-triage |
| Browser reap on shutdown raises | Log `browser_reap_on_shutdown_failed` (exception); do not swallow via `suppress` |
| Mission Control unwired on stage latency | Log `agent_turn_stage_latency_unwired`; continue without MC samples |

**Operator notify (boot):** Gateway lifespan calls `wire_operator_notify` so issue-watch / cron notify can deliver via `ChannelRouter.route_outgoing` when an owner Telegram id is configured; otherwise LOG fallback under `.sevn/trigger_runs/`.

## Amendments (spec-36-sub-agents)

`gateway.queue_mode` and per-channel `busy_input_mode` gain `"multi"`.
`session_manager.enqueue_dispatch` classifies busy input via relatedness labels
and may spawn concurrent L1 tier-B runs (`src/sevn/gateway/queue/queue_multi.py`).
`routing_footer.py` tags parallel L1 replies with short sub-agent ids.

## Test Strategy

| Tests | Focus |
|-------|-------|
| `tests/gateway/test_agent_turn_mvp.py` | Core turn |
| `tests/gateway/test_agent_turn_tier_b.py` | Tier B wiring |
| `tests/gateway/test_agent_turn_escalation.py` | Escalation |
| `tests/gateway/test_session_manager.py` | Queue semantics |
| `tests/gateway/test_queue_steer.py`, `test_queue_multi.py` | Queue modes |
| `tests/gateway/test_cascade_budget.py` | Retry budget |
| `tests/gateway/test_no_answer_messages.py` | Fallback copy |
| `tests/gateway/test_lifecycle.py`, `test_lifecycle_w1_red.py` | Boot/shutdown; browser reap failure log; operator-notify wiring |
| `tests/proxy/test_codex_aggregation.py`, `test_codex_aggregation_w1_red.py` | Slow-turn Still working… route; MC stage-latency no-op log |
| `tests/channels/test_telegram_outbound.py` | D6/D7 enqueue `chat_id` + classifier-timeout dispatch routing |
| `tests/gateway/test_version_id_control_w1_red.py`, `test_stop_l1_buttons.py` | Version-id `answer_callback` toast + fallback; `/stop` picker re-edit |
| `make telegram-checks` | Host Telegram Bot-API smoke (`telegram_checks`; alias `make telegram-e2e`) |
