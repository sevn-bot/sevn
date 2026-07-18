---
id: spec-23-cli
kind: spec
title: CLI — Spec
status: scaffold
owner: Alex
summary: Deliver the primary operator and automation surface for install, upgrades,
  health checks, workspace + daemon lifecycle, and scriptable inspection. The CLI
  is not the agent’s in-harness tool API and no
last_updated: '2026-07-18'
fingerprint: sha256:1df1627c54d4b7734d1f18146359ecbe137f9541ac7edb548e0a32263804a588
related: []
sources:
- src/sevn/cli/**
parent_prd: prd-06-setup-and-operations
depends_on:
- spec-02-config-and-workspace
- spec-06-secrets
- spec-07-egress-proxy
- spec-17-gateway
- spec-22-onboarding
build_phase: null
interfaces:
- name: main
  file: src/sevn/cli/app.py
  symbol: main
- name: version_detail
  file: src/sevn/cli/app.py
  symbol: version_detail
- name: run_sync_coro
  file: src/sevn/cli/asyncio_util.py
  symbol: run_sync_coro
- name: install_cli_activity_log
  file: src/sevn/cli/cli_activity_log.py
  symbol: install_cli_activity_log
- name: log_cli_activity
  file: src/sevn/cli/cli_activity_log.py
  symbol: log_cli_activity
- name: log_cli_invocation
  file: src/sevn/cli/cli_activity_log.py
  symbol: log_cli_invocation
- name: resolve_cli_log_path
  file: src/sevn/cli/cli_activity_log.py
  symbol: resolve_cli_log_path
- name: shutdown_cli_activity_log
  file: src/sevn/cli/cli_activity_log.py
  symbol: shutdown_cli_activity_log
- name: register
  file: src/sevn/cli/commands/about_docs_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/agent_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/channels_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/completion.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/config_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/dashboard_cmd.py
  symbol: register
- name: register_set_login_password
  file: src/sevn/cli/commands/dashboard_set_login_password.py
  symbol: register_set_login_password
- name: register
  file: src/sevn/cli/commands/deploy_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/doctor.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/export_secrets_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/gateway.py
  symbol: register
- name: register_set_gateway_token
  file: src/sevn/cli/commands/gateway_set_token.py
  symbol: register_set_gateway_token
- name: echo_gh_intro
  file: src/sevn/cli/commands/gh_cmd.py
  symbol: echo_gh_intro
- name: echo_github_token_setup_guide
  file: src/sevn/cli/commands/gh_cmd.py
  symbol: echo_github_token_setup_guide
- name: register
  file: src/sevn/cli/commands/gh_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/gui_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/guide_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/improve_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/logs_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/memory_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/message_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/migrate_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/models_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/onboard.py
  symbol: register
- name: echo_openwiki_intro
  file: src/sevn/cli/commands/openwiki_cmd.py
  symbol: echo_openwiki_intro
- name: register
  file: src/sevn/cli/commands/openwiki_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/pairing_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/placeholders.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/providers_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/proxy_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/readme_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/second_brain_cmd.py
  symbol: register
- name: show_second_brain_config
  file: src/sevn/cli/commands/second_brain_cmd.py
  symbol: show_second_brain_config
- name: execute_secrets_put
  file: src/sevn/cli/commands/secrets_cmd.py
  symbol: execute_secrets_put
- name: register
  file: src/sevn/cli/commands/secrets_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/sessions.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/shell_history_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/skills_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/subagents_cmd.py
  symbol: register
- name: show_subagents_config
  file: src/sevn/cli/commands/subagents_cmd.py
  symbol: show_subagents_config
- name: register
  file: src/sevn/cli/commands/sync_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/tools_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/traces_cmd.py
  symbol: register
- name: run_traces
  file: src/sevn/cli/commands/traces_cmd.py
  symbol: run_traces
- name: register
  file: src/sevn/cli/commands/tracing_cmd.py
  symbol: register
- name: show_tracing_config
  file: src/sevn/cli/commands/tracing_cmd.py
  symbol: show_tracing_config
- name: register
  file: src/sevn/cli/commands/tunnel_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/turn_bundle_cmd.py
  symbol: register
- name: discover_operator_home_paths
  file: src/sevn/cli/commands/unboard.py
  symbol: discover_operator_home_paths
- name: register
  file: src/sevn/cli/commands/unboard.py
  symbol: register
- name: resolve_operator_home
  file: src/sevn/cli/commands/unboard.py
  symbol: resolve_operator_home
- name: resolve_source_root
  file: src/sevn/cli/commands/unboard.py
  symbol: resolve_source_root
- name: run_unboard
  file: src/sevn/cli/commands/unboard.py
  symbol: run_unboard
- name: register
  file: src/sevn/cli/commands/update_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/usage_cmd.py
  symbol: register
- name: register
  file: src/sevn/cli/commands/voice_cmd.py
  symbol: register
- name: completion_install
  file: src/sevn/cli/completion_util.py
  symbol: completion_install
- name: completion_show_script
  file: src/sevn/cli/completion_util.py
  symbol: completion_show_script
- name: completion_uninstall
  file: src/sevn/cli/completion_util.py
  symbol: completion_uninstall
- name: normalize_shell
  file: src/sevn/cli/completion_util.py
  symbol: normalize_shell
- name: ConfigSection
  file: src/sevn/cli/config_paths.py
  symbol: ConfigSection
- name: iter_config_sections
  file: src/sevn/cli/config_paths.py
  symbol: iter_config_sections
- name: menu_registry_root_slugs
  file: src/sevn/cli/config_paths.py
  symbol: menu_registry_root_slugs
- name: section_by_slug
  file: src/sevn/cli/config_paths.py
  symbol: section_by_slug
- name: section_callback
  file: src/sevn/cli/config_paths.py
  symbol: section_callback
- name: format_section_plain
  file: src/sevn/cli/config_sections/__init__.py
  symbol: format_section_plain
- name: nested_get
  file: src/sevn/cli/config_sections/__init__.py
  symbol: nested_get
- name: section_payload
  file: src/sevn/cli/config_sections/__init__.py
  symbol: section_payload
- name: register_daemon_subcommands
  file: src/sevn/cli/daemon_control.py
  symbol: register_daemon_subcommands
- name: dashboard_api_get
  file: src/sevn/cli/dashboard_api_client.py
  symbol: dashboard_api_get
- name: dashboard_api_post
  file: src/sevn/cli/dashboard_api_client.py
  symbol: dashboard_api_post
- name: dashboard_http_failure
  file: src/sevn/cli/dashboard_api_client.py
  symbol: dashboard_http_failure
- name: DashboardLoginPasswordStoreResult
  file: src/sevn/cli/dashboard_login_password_store.py
  symbol: DashboardLoginPasswordStoreResult
- name: store_dashboard_login_password_local
  file: src/sevn/cli/dashboard_login_password_store.py
  symbol: store_dashboard_login_password_local
- name: AgentRunReport
  file: src/sevn/cli/doctor/agent.py
  symbol: AgentRunReport
- name: AgentStepResult
  file: src/sevn/cli/doctor/agent.py
  symbol: AgentStepResult
- name: run_doctor_with_agent
  file: src/sevn/cli/doctor/agent.py
  symbol: run_doctor_with_agent
- name: CheckResult
  file: src/sevn/cli/doctor/checks.py
  symbol: CheckResult
- name: DoctorCheck
  file: src/sevn/cli/doctor/checks.py
  symbol: DoctorCheck
- name: FixContext
  file: src/sevn/cli/doctor/fix.py
  symbol: FixContext
- name: FixOutcome
  file: src/sevn/cli/doctor/fix.py
  symbol: FixOutcome
- name: FixReport
  file: src/sevn/cli/doctor/fix.py
  symbol: FixReport
- name: apply_safe_fixes
  file: src/sevn/cli/doctor/fix.py
  symbol: apply_safe_fixes
- name: DoctorRunOptions
  file: src/sevn/cli/doctor/probes.py
  symbol: DoctorRunOptions
- name: run_doctor_probes
  file: src/sevn/cli/doctor/probes.py
  symbol: run_doctor_probes
- name: render_doctor_report
  file: src/sevn/cli/doctor/report.py
  symbol: render_doctor_report
- name: render_fix_lines
  file: src/sevn/cli/doctor/report.py
  symbol: render_fix_lines
- name: registered_check_ids
  file: src/sevn/cli/doctor/sections.py
  symbol: registered_check_ids
- name: section_for
  file: src/sevn/cli/doctor/sections.py
  symbol: section_for
- name: title_for
  file: src/sevn/cli/doctor/sections.py
  symbol: title_for
- name: DoctorSolution
  file: src/sevn/cli/doctor/solutions.py
  symbol: DoctorSolution
- name: SolutionsCatalog
  file: src/sevn/cli/doctor/solutions.py
  symbol: SolutionsCatalog
- name: catalog_resource_path
  file: src/sevn/cli/doctor/solutions.py
  symbol: catalog_resource_path
- name: load_solutions_catalog
  file: src/sevn/cli/doctor/solutions.py
  symbol: load_solutions_catalog
- name: lookup_solution
  file: src/sevn/cli/doctor/solutions.py
  symbol: lookup_solution
- name: solution_for_json
  file: src/sevn/cli/doctor/solutions.py
  symbol: solution_for_json
- name: CliAuthError
  file: src/sevn/cli/errors.py
  symbol: CliAuthError
- name: CliError
  file: src/sevn/cli/errors.py
  symbol: CliError
- name: CliPreconditionError
  file: src/sevn/cli/errors.py
  symbol: CliPreconditionError
- name: CliUsageError
  file: src/sevn/cli/errors.py
  symbol: CliUsageError
- name: gateway_get
  file: src/sevn/cli/gateway_client.py
  symbol: gateway_get
- name: gateway_json_request
  file: src/sevn/cli/gateway_client.py
  symbol: gateway_json_request
- name: gateway_listen_conflict_detail
  file: src/sevn/cli/gateway_client.py
  symbol: gateway_listen_conflict_detail
- name: probe_gateway_listen_state
  file: src/sevn/cli/gateway_client.py
  symbol: probe_gateway_listen_state
- name: probe_proxy_listen_state
  file: src/sevn/cli/gateway_client.py
  symbol: probe_proxy_listen_state
- name: proxy_healthz_get
  file: src/sevn/cli/gateway_client.py
  symbol: proxy_healthz_get
- name: proxy_listen_conflict_detail
  file: src/sevn/cli/gateway_client.py
  symbol: proxy_listen_conflict_detail
- name: resolve_gateway_base_url
  file: src/sevn/cli/gateway_client.py
  symbol: resolve_gateway_base_url
- name: resolve_gateway_token
  file: src/sevn/cli/gateway_client.py
  symbol: resolve_gateway_token
- name: resolve_proxy_base_url
  file: src/sevn/cli/gateway_client.py
  symbol: resolve_proxy_base_url
- name: stop_all_gateway_instances
  file: src/sevn/cli/gateway_teardown.py
  symbol: stop_all_gateway_instances
- name: stop_handoff_listeners
  file: src/sevn/cli/gateway_teardown.py
  symbol: stop_handoff_listeners
- name: GatewayTokenBootstrap
  file: src/sevn/cli/gateway_token_store.py
  symbol: GatewayTokenBootstrap
- name: GatewayTokenStoreResult
  file: src/sevn/cli/gateway_token_store.py
  symbol: GatewayTokenStoreResult
- name: load_bootstrap_workspace
  file: src/sevn/cli/gateway_token_store.py
  symbol: load_bootstrap_workspace
- name: store_gateway_token_local
  file: src/sevn/cli/gateway_token_store.py
  symbol: store_gateway_token_local
- name: guide_title
  file: src/sevn/cli/help/guide.py
  symbol: guide_title
- name: list_guide_topics
  file: src/sevn/cli/help/guide.py
  symbol: list_guide_topics
- name: load_guide
  file: src/sevn/cli/help/guide.py
  symbol: load_guide
- name: apply_root_panels
  file: src/sevn/cli/help/panels.py
  symbol: apply_root_panels
- name: iter_root_click_commands
  file: src/sevn/cli/help/panels.py
  symbol: iter_root_click_commands
- name: panel_for
  file: src/sevn/cli/help/panels.py
  symbol: panel_for
- name: InstallCandidate
  file: src/sevn/cli/install_discovery.py
  symbol: InstallCandidate
- name: candidate_to_dict
  file: src/sevn/cli/install_discovery.py
  symbol: candidate_to_dict
- name: discover_operator_homes
  file: src/sevn/cli/install_discovery.py
  symbol: discover_operator_homes
- name: resolve_keystore_path
  file: src/sevn/cli/install_discovery.py
  symbol: resolve_keystore_path
- name: resolve_workspace_keystore_path
  file: src/sevn/cli/install_discovery.py
  symbol: resolve_workspace_keystore_path
- name: workspace_has_artifacts
  file: src/sevn/cli/install_discovery.py
  symbol: workspace_has_artifacts
- name: install_daemon_plan
  file: src/sevn/cli/install_gate.py
  symbol: install_daemon_plan
- name: maybe_install_daemon_after_promote
  file: src/sevn/cli/install_gate.py
  symbol: maybe_install_daemon_after_promote
- name: parse_install_daemon_flag_from_env
  file: src/sevn/cli/install_gate.py
  symbol: parse_install_daemon_flag_from_env
- name: parse_reuse_from_env
  file: src/sevn/cli/install_gate.py
  symbol: parse_reuse_from_env
- name: run_install_daemon
  file: src/sevn/cli/install_gate.py
  symbol: run_install_daemon
- name: should_install_daemon
  file: src/sevn/cli/install_gate.py
  symbol: should_install_daemon
- name: emit_json_failure
  file: src/sevn/cli/json_util.py
  symbol: emit_json_failure
- name: emit_json_success
  file: src/sevn/cli/json_util.py
  symbol: emit_json_success
- name: LogEntry
  file: src/sevn/cli/log_follow.py
  symbol: LogEntry
- name: build_logs_insight_summary
  file: src/sevn/cli/log_follow.py
  symbol: build_logs_insight_summary
- name: collect_merged_log_entries
  file: src/sevn/cli/log_follow.py
  symbol: collect_merged_log_entries
- name: parse_log_level
  file: src/sevn/cli/log_follow.py
  symbol: parse_log_level
- name: parse_log_timestamp
  file: src/sevn/cli/log_follow.py
  symbol: parse_log_timestamp
- name: render_logs_insight_summary
  file: src/sevn/cli/log_follow.py
  symbol: render_logs_insight_summary
- name: resolve_agent_log_path
  file: src/sevn/cli/log_follow.py
  symbol: resolve_agent_log_path
- name: resolve_gateway_log_path
  file: src/sevn/cli/log_follow.py
  symbol: resolve_gateway_log_path
- name: resolve_log_paths_for_sources
  file: src/sevn/cli/log_follow.py
  symbol: resolve_log_paths_for_sources
- name: resolve_service_log_path
  file: src/sevn/cli/log_follow.py
  symbol: resolve_service_log_path
- name: run_gateway_logs
  file: src/sevn/cli/log_follow.py
  symbol: run_gateway_logs
- name: run_service_logs
  file: src/sevn/cli/log_follow.py
  symbol: run_service_logs
- name: run_unified_logs
  file: src/sevn/cli/log_follow.py
  symbol: run_unified_logs
- name: OperatorLockHeld
  file: src/sevn/cli/operator_lock.py
  symbol: OperatorLockHeld
- name: lock_file_age_seconds
  file: src/sevn/cli/operator_lock.py
  symbol: lock_file_age_seconds
- name: lock_file_appears_stale
  file: src/sevn/cli/operator_lock.py
  symbol: lock_file_appears_stale
- name: operator_lock
  file: src/sevn/cli/operator_lock.py
  symbol: operator_lock
- name: operator_lock_path
  file: src/sevn/cli/operator_lock.py
  symbol: operator_lock_path
- name: echo_field_collect_guide
  file: src/sevn/cli/prompt_util.py
  symbol: echo_field_collect_guide
- name: prompt_with_field_help
  file: src/sevn/cli/prompt_util.py
  symbol: prompt_with_field_help
- name: RenderOptions
  file: src/sevn/cli/render/console.py
  symbol: RenderOptions
- name: configure_render
  file: src/sevn/cli/render/console.py
  symbol: configure_render
- name: get_console
  file: src/sevn/cli/render/console.py
  symbol: get_console
- name: is_rich
  file: src/sevn/cli/render/console.py
  symbol: is_rich
- name: plain_echo
  file: src/sevn/cli/render/console.py
  symbol: plain_echo
- name: check_fail
  file: src/sevn/cli/render/sections.py
  symbol: check_fail
- name: check_info
  file: src/sevn/cli/render/sections.py
  symbol: check_info
- name: check_ok
  file: src/sevn/cli/render/sections.py
  symbol: check_ok
- name: check_warn
  file: src/sevn/cli/render/sections.py
  symbol: check_warn
- name: section
  file: src/sevn/cli/render/sections.py
  symbol: section
- name: render_table
  file: src/sevn/cli/render/tables.py
  symbol: render_table
- name: SpanTreeNode
  file: src/sevn/cli/render/tree.py
  symbol: SpanTreeNode
- name: render_span_tree
  file: src/sevn/cli/render/tree.py
  symbol: render_span_tree
- name: RepoSyncError
  file: src/sevn/cli/repo_sync.py
  symbol: RepoSyncError
- name: SyncResult
  file: src/sevn/cli/repo_sync.py
  symbol: SyncResult
- name: resolve_sevn_repo_root
  file: src/sevn/cli/repo_sync.py
  symbol: resolve_sevn_repo_root
- name: sync_source_tree
  file: src/sevn/cli/repo_sync.py
  symbol: sync_source_tree
- name: http_error_detail
  file: src/sevn/cli/secrets_gateway_client.py
  symbol: http_error_detail
- name: secrets_delete
  file: src/sevn/cli/secrets_gateway_client.py
  symbol: secrets_delete
- name: secrets_list
  file: src/sevn/cli/secrets_gateway_client.py
  symbol: secrets_list
- name: secrets_put
  file: src/sevn/cli/secrets_gateway_client.py
  symbol: secrets_put
- name: InstallPlan
  file: src/sevn/cli/service_manager.py
  symbol: InstallPlan
- name: ServiceManagerError
  file: src/sevn/cli/service_manager.py
  symbol: ServiceManagerError
- name: both_units_installed_and_active
  file: src/sevn/cli/service_manager.py
  symbol: both_units_installed_and_active
- name: control_unit
  file: src/sevn/cli/service_manager.py
  symbol: control_unit
- name: install_paired_units
  file: src/sevn/cli/service_manager.py
  symbol: install_paired_units
- name: plan_install
  file: src/sevn/cli/service_manager.py
  symbol: plan_install
- name: propagate_daemon_proxy_env
  file: src/sevn/cli/service_manager.py
  symbol: propagate_daemon_proxy_env
- name: propagate_daemon_secret_env
  file: src/sevn/cli/service_manager.py
  symbol: propagate_daemon_secret_env
- name: remove_paired_unit_files
  file: src/sevn/cli/service_manager.py
  symbol: remove_paired_unit_files
- name: stop_paired_units
  file: src/sevn/cli/service_manager.py
  symbol: stop_paired_units
- name: unit_file_exists
  file: src/sevn/cli/service_manager.py
  symbol: unit_file_exists
- name: unit_is_active
  file: src/sevn/cli/service_manager.py
  symbol: unit_is_active
- name: resolve_shell_history_path
  file: src/sevn/cli/shell_history.py
  symbol: resolve_shell_history_path
- name: schedule_post_exit_history_scrub
  file: src/sevn/cli/shell_history.py
  symbol: schedule_post_exit_history_scrub
- name: scrub_shell_history
  file: src/sevn/cli/shell_history.py
  symbol: scrub_shell_history
- name: emit_shell_history_session_hint
  file: src/sevn/cli/shell_history_hooks.py
  symbol: emit_shell_history_session_hint
- name: ensure_shell_history_hook
  file: src/sevn/cli/shell_history_hooks.py
  symbol: ensure_shell_history_hook
- name: install_shell_history_hook
  file: src/sevn/cli/shell_history_hooks.py
  symbol: install_shell_history_hook
- name: shell_history_hook_installed
  file: src/sevn/cli/shell_history_hooks.py
  symbol: shell_history_hook_installed
- name: uninstall_shell_history_hook
  file: src/sevn/cli/shell_history_hooks.py
  symbol: uninstall_shell_history_hook
- name: terminal_hyperlink
  file: src/sevn/cli/terminal_util.py
  symbol: terminal_hyperlink
- name: SpanNode
  file: src/sevn/cli/traces_read.py
  symbol: SpanNode
- name: load_trace_turns
  file: src/sevn/cli/traces_read.py
  symbol: load_trace_turns
- name: traces_drilldown_hint
  file: src/sevn/cli/traces_read.py
  symbol: traces_drilldown_hint
- name: turn_to_span_tree_node
  file: src/sevn/cli/traces_read.py
  symbol: turn_to_span_tree_node
- name: load_log_viewer_app
  file: src/sevn/cli/tui/__init__.py
  symbol: load_log_viewer_app
- name: load_section_picker_app
  file: src/sevn/cli/tui/__init__.py
  symbol: load_section_picker_app
- name: textual_ui_allowed
  file: src/sevn/cli/tui/__init__.py
  symbol: textual_ui_allowed
- name: run_config_menu
  file: src/sevn/cli/tui/config_menu.py
  symbol: run_config_menu
- name: LogViewerApp
  file: src/sevn/cli/tui/log_viewer.py
  symbol: LogViewerApp
- name: run_log_viewer
  file: src/sevn/cli/tui/log_viewer.py
  symbol: run_log_viewer
- name: SectionPickerApp
  file: src/sevn/cli/tui/menu.py
  symbol: SectionPickerApp
- name: run_section_picker
  file: src/sevn/cli/tui/menu.py
  symbol: run_section_picker
- name: TunnelSetupResult
  file: src/sevn/cli/tunnel_setup_store.py
  symbol: TunnelSetupResult
- name: apply_tunnel_setup_local
  file: src/sevn/cli/tunnel_setup_store.py
  symbol: apply_tunnel_setup_local
- name: uvicorn_program_argv
  file: src/sevn/cli/uvicorn_argv.py
  symbol: uvicorn_program_argv
- name: BoundWorkspace
  file: src/sevn/cli/workspace.py
  symbol: BoundWorkspace
- name: bound_sevn_json_path
  file: src/sevn/cli/workspace.py
  symbol: bound_sevn_json_path
- name: bound_workspace_dir
  file: src/sevn/cli/workspace.py
  symbol: bound_workspace_dir
- name: load_bound_workspace
  file: src/sevn/cli/workspace.py
  symbol: load_bound_workspace
- name: load_doctor_workspace
  file: src/sevn/cli/workspace.py
  symbol: load_doctor_workspace
- name: operator_home_from_sevn_json
  file: src/sevn/cli/workspace.py
  symbol: operator_home_from_sevn_json
- name: sevn_home_dir
  file: src/sevn/cli/workspace.py
  symbol: sevn_home_dir
- name: config_set_reload_hint
  file: src/sevn/cli/workspace_schema.py
  symbol: config_set_reload_hint
- name: dotted_path_in_schema
  file: src/sevn/cli/workspace_schema.py
  symbol: dotted_path_in_schema
- name: load_workspace_json_schema
  file: src/sevn/cli/workspace_schema.py
  symbol: load_workspace_json_schema
- name: parse_config_set_value
  file: src/sevn/cli/workspace_schema.py
  symbol: parse_config_set_value
---

## Purpose

Deliver the primary operator and automation surface for install, upgrades, health checks, workspace + daemon lifecycle, and scriptable inspection. The CLI is not the agent’s in-harness tool API and no

Primary code trees: [`src/sevn/cli`](src/sevn/cli/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`main`](src/sevn/cli/app.py) — `src/sevn/cli/app.py`
- [`version_detail`](src/sevn/cli/app.py) — `src/sevn/cli/app.py`
- [`run_sync_coro`](src/sevn/cli/asyncio_util.py) — `src/sevn/cli/asyncio_util.py`
- [`install_cli_activity_log`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`log_cli_activity`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`log_cli_invocation`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`resolve_cli_log_path`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`shutdown_cli_activity_log`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`register`](src/sevn/cli/commands/about_docs_cmd.py) — `src/sevn/cli/commands/about_docs_cmd.py`
- [`register`](src/sevn/cli/commands/agent_cmd.py) — `src/sevn/cli/commands/agent_cmd.py`
- [`register`](src/sevn/cli/commands/channels_cmd.py) — `src/sevn/cli/commands/channels_cmd.py`
- [`register`](src/sevn/cli/commands/completion.py) — `src/sevn/cli/commands/completion.py`
- _…and 221 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`main`](src/sevn/cli/app.py) — `src/sevn/cli/app.py`
- [`version_detail`](src/sevn/cli/app.py) — `src/sevn/cli/app.py`
- [`run_sync_coro`](src/sevn/cli/asyncio_util.py) — `src/sevn/cli/asyncio_util.py`
- [`install_cli_activity_log`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`log_cli_activity`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`log_cli_invocation`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`resolve_cli_log_path`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`shutdown_cli_activity_log`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`register`](src/sevn/cli/commands/about_docs_cmd.py) — `src/sevn/cli/commands/about_docs_cmd.py`
- [`register`](src/sevn/cli/commands/agent_cmd.py) — `src/sevn/cli/commands/agent_cmd.py`
- [`register`](src/sevn/cli/commands/channels_cmd.py) — `src/sevn/cli/commands/channels_cmd.py`
- [`register`](src/sevn/cli/commands/completion.py) — `src/sevn/cli/commands/completion.py`
- _…and 221 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/cli`](src/sevn/cli/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/cli`](src/sevn/cli/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Amendments (spec-36-sub-agents)

New command group `sevn subagents list|kill|limits` and `sevn config subagents`
summary (`src/sevn/cli/commands/subagents_cmd.py`). Doctor probe `subagents_registry`
reports orphan counts (D13).

## Implemented by

- [`main`](src/sevn/cli/app.py) — `src/sevn/cli/app.py`
- [`version_detail`](src/sevn/cli/app.py) — `src/sevn/cli/app.py`
- [`run_sync_coro`](src/sevn/cli/asyncio_util.py) — `src/sevn/cli/asyncio_util.py`
- [`install_cli_activity_log`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`log_cli_activity`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`log_cli_invocation`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`resolve_cli_log_path`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`shutdown_cli_activity_log`](src/sevn/cli/cli_activity_log.py) — `src/sevn/cli/cli_activity_log.py`
- [`register`](src/sevn/cli/commands/about_docs_cmd.py) — `src/sevn/cli/commands/about_docs_cmd.py`
- [`register`](src/sevn/cli/commands/agent_cmd.py) — `src/sevn/cli/commands/agent_cmd.py`
- [`register`](src/sevn/cli/commands/channels_cmd.py) — `src/sevn/cli/commands/channels_cmd.py`
- [`register`](src/sevn/cli/commands/completion.py) — `src/sevn/cli/commands/completion.py`
- [`register`](src/sevn/cli/commands/config_cmd.py) — `src/sevn/cli/commands/config_cmd.py`
- [`register`](src/sevn/cli/commands/dashboard_cmd.py) — `src/sevn/cli/commands/dashboard_cmd.py`
- [`register_set_login_password`](src/sevn/cli/commands/dashboard_set_login_password.py) — `src/sevn/cli/commands/dashboard_set_login_password.py`
- [`register`](src/sevn/cli/commands/deploy_cmd.py) — `src/sevn/cli/commands/deploy_cmd.py`
- [`register`](src/sevn/cli/commands/doctor.py) — `src/sevn/cli/commands/doctor.py`
- [`register`](src/sevn/cli/commands/export_secrets_cmd.py) — `src/sevn/cli/commands/export_secrets_cmd.py`
- [`register`](src/sevn/cli/commands/gateway.py) — `src/sevn/cli/commands/gateway.py`
- [`register_set_gateway_token`](src/sevn/cli/commands/gateway_set_token.py) — `src/sevn/cli/commands/gateway_set_token.py`
- _…and 213 more in frontmatter `interfaces:`._

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
