---
id: spec-24-dashboard
kind: spec
title: Mission Control (dashboard) — Spec
status: done
owner: Alex
summary: 'Deliver Mission Control: a same-process dashboard (prd-07-mission-control)
  so the owner can inspect traces, costs, provider health, in-flight runs, proxy status,
  and config without opening SQLite from'
last_updated: '2026-07-07'
fingerprint: sha256:d437a013bcf30936fa7a4877a32a4fab8ce0d79dc71a3a395ded9cd8c9380d19
related: []
sources:
- src/sevn/ui/**
parent_prd: prd-07-mission-control
depends_on:
- spec-02-config-and-workspace
- spec-05-llm-transports
- spec-06-secrets
- spec-07-egress-proxy
- spec-16-harness-discipline
- spec-17-gateway
- spec-22-onboarding
- spec-23-cli
build_phase: null
interfaces:
- name: register_dashboard_routes
  file: src/sevn/ui/dashboard/__init__.py
  symbol: register_dashboard_routes
- name: create_dashboard_api_router
  file: src/sevn/ui/dashboard/api/__init__.py
  symbol: create_dashboard_api_router
- name: config_error
  file: src/sevn/ui/dashboard/api/_config_persist.py
  symbol: config_error
- name: config_validation_error
  file: src/sevn/ui/dashboard/api/_config_persist.py
  symbol: config_validation_error
- name: deep_merge
  file: src/sevn/ui/dashboard/api/_config_persist.py
  symbol: deep_merge
- name: load_workspace_document
  file: src/sevn/ui/dashboard/api/_config_persist.py
  symbol: load_workspace_document
- name: persist_workspace_document
  file: src/sevn/ui/dashboard/api/_config_persist.py
  symbol: persist_workspace_document
- name: read_config_body
  file: src/sevn/ui/dashboard/api/_config_persist.py
  symbol: read_config_body
- name: SkillInstallBody
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: SkillInstallBody
- name: SkillToggleBody
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: SkillToggleBody
- name: agent_config_get
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: agent_config_get
- name: agent_config_put
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: agent_config_put
- name: agent_permissions_get
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: agent_permissions_get
- name: agent_permissions_put
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: agent_permissions_put
- name: llm_params_get
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: llm_params_get
- name: llm_params_put
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: llm_params_put
- name: mcp_servers_put
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: mcp_servers_put
- name: mcp_servers_registry
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: mcp_servers_registry
- name: skills_bundled_list
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: skills_bundled_list
- name: skills_install
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: skills_install
- name: skills_inventory
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: skills_inventory
- name: skills_promote
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: skills_promote
- name: skills_toggle
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: skills_toggle
- name: skills_uninstall
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: skills_uninstall
- name: tools_health_list
  file: src/sevn/ui/dashboard/api/agent.py
  symbol: tools_health_list
- name: analytics_approvals
  file: src/sevn/ui/dashboard/api/audit.py
  symbol: analytics_approvals
- name: analytics_daily_volume
  file: src/sevn/ui/dashboard/api/audit.py
  symbol: analytics_daily_volume
- name: analytics_tool_frequency
  file: src/sevn/ui/dashboard/api/audit.py
  symbol: analytics_tool_frequency
- name: audit_timeline
  file: src/sevn/ui/dashboard/api/audit.py
  symbol: audit_timeline
- name: LoginRequest
  file: src/sevn/ui/dashboard/api/auth.py
  symbol: LoginRequest
- name: auth_status
  file: src/sevn/ui/dashboard/api/auth.py
  symbol: auth_status
- name: login
  file: src/sevn/ui/dashboard/api/auth.py
  symbol: login
- name: logout
  file: src/sevn/ui/dashboard/api/auth.py
  symbol: logout
- name: dashboard_canvas
  file: src/sevn/ui/dashboard/api/canvas.py
  symbol: dashboard_canvas
- name: alerts_rollup
  file: src/sevn/ui/dashboard/api/channels.py
  symbol: alerts_rollup
- name: channels_config_get
  file: src/sevn/ui/dashboard/api/channels.py
  symbol: channels_config_get
- name: channels_config_put
  file: src/sevn/ui/dashboard/api/channels.py
  symbol: channels_config_put
- name: channels_status
  file: src/sevn/ui/dashboard/api/channels.py
  symbol: channels_status
- name: ChatForkResponse
  file: src/sevn/ui/dashboard/api/chat.py
  symbol: ChatForkResponse
- name: ChatTokenResponse
  file: src/sevn/ui/dashboard/api/chat.py
  symbol: ChatTokenResponse
- name: chat_fork
  file: src/sevn/ui/dashboard/api/chat.py
  symbol: chat_fork
- name: chat_token
  file: src/sevn/ui/dashboard/api/chat.py
  symbol: chat_token
- name: CliRunBody
  file: src/sevn/ui/dashboard/api/cli_console.py
  symbol: CliRunBody
- name: CliRunResponse
  file: src/sevn/ui/dashboard/api/cli_console.py
  symbol: CliRunResponse
- name: cli_run
  file: src/sevn/ui/dashboard/api/cli_console.py
  symbol: cli_run
- name: cli_shortcuts
  file: src/sevn/ui/dashboard/api/cli_console.py
  symbol: cli_shortcuts
- name: coding_agents_artifacts_list
  file: src/sevn/ui/dashboard/api/coding_agents.py
  symbol: coding_agents_artifacts_list
- name: coding_agents_list
  file: src/sevn/ui/dashboard/api/coding_agents.py
  symbol: coding_agents_list
- name: coding_agents_list_payload
  file: src/sevn/ui/dashboard/api/coding_agents.py
  symbol: coding_agents_list_payload
- name: coding_agents_put
  file: src/sevn/ui/dashboard/api/coding_agents.py
  symbol: coding_agents_put
- name: coding_agents_run_artifacts
  file: src/sevn/ui/dashboard/api/coding_agents.py
  symbol: coding_agents_run_artifacts
- name: require_dashboard_csrf
  file: src/sevn/ui/dashboard/api/deps.py
  symbol: require_dashboard_csrf
- name: require_dashboard_owner
  file: src/sevn/ui/dashboard/api/deps.py
  symbol: require_dashboard_owner
- name: CreateEvolutionIssueBody
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: CreateEvolutionIssueBody
- name: EditApprovalBody
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: EditApprovalBody
- name: ImportGithubIssueBody
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: ImportGithubIssueBody
- name: RunPipelineBody
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: RunPipelineBody
- name: SyncGithubIssuesBody
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: SyncGithubIssuesBody
- name: create_evolution_issue
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: create_evolution_issue
- name: evolution_approval_approve
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_approval_approve
- name: evolution_approval_edit
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_approval_edit
- name: evolution_approval_reject
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_approval_reject
- name: evolution_approvals
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_approvals
- name: evolution_issue_detail
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_issue_detail
- name: evolution_issue_import
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_issue_import
- name: evolution_issue_sync
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_issue_sync
- name: evolution_issues
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_issues
- name: evolution_pipeline_detail
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_pipeline_detail
- name: evolution_pipeline_kill
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_pipeline_kill
- name: evolution_pipeline_poll
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_pipeline_poll
- name: evolution_pipeline_run
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_pipeline_run
- name: evolution_pipelines
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_pipelines
- name: evolution_stats
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_stats
- name: evolution_traces
  file: src/sevn/ui/dashboard/api/evolution.py
  symbol: evolution_traces
- name: FileContentPutBody
  file: src/sevn/ui/dashboard/api/files.py
  symbol: FileContentPutBody
- name: FileCreateBody
  file: src/sevn/ui/dashboard/api/files.py
  symbol: FileCreateBody
- name: FileRenameBody
  file: src/sevn/ui/dashboard/api/files.py
  symbol: FileRenameBody
- name: files_content_get
  file: src/sevn/ui/dashboard/api/files.py
  symbol: files_content_get
- name: files_content_put
  file: src/sevn/ui/dashboard/api/files.py
  symbol: files_content_put
- name: files_create
  file: src/sevn/ui/dashboard/api/files.py
  symbol: files_create
- name: files_delete
  file: src/sevn/ui/dashboard/api/files.py
  symbol: files_delete
- name: files_rename
  file: src/sevn/ui/dashboard/api/files.py
  symbol: files_rename
- name: files_tree
  file: src/sevn/ui/dashboard/api/files.py
  symbol: files_tree
- name: code_understanding_index
  file: src/sevn/ui/dashboard/api/knowledge.py
  symbol: code_understanding_index
- name: knowledge_graph
  file: src/sevn/ui/dashboard/api/knowledge.py
  symbol: knowledge_graph
- name: memory_overview
  file: src/sevn/ui/dashboard/api/knowledge.py
  symbol: memory_overview
- name: second_brain_overview
  file: src/sevn/ui/dashboard/api/knowledge.py
  symbol: second_brain_overview
- name: workspace_files_list
  file: src/sevn/ui/dashboard/api/knowledge.py
  symbol: workspace_files_list
- name: dashboard_nav
  file: src/sevn/ui/dashboard/api/nav.py
  symbol: dashboard_nav
- name: backup_manifest
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: backup_manifest
- name: config_full_get
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: config_full_get
- name: config_full_put
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: config_full_put
- name: config_full_validate
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: config_full_validate
- name: config_get
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: config_get
- name: cron_config_put
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: cron_config_put
- name: cron_jobs_list
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: cron_jobs_list
- name: schema_ontology
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: schema_ontology
- name: secrets_alias_reveal
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: secrets_alias_reveal
- name: secrets_aliases
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: secrets_aliases
- name: security_get
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: security_get
- name: security_put
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: security_put
- name: tunnels_process
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: tunnels_process
- name: tunnels_start
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: tunnels_start
- name: tunnels_status
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: tunnels_status
- name: tunnels_stop
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: tunnels_stop
- name: ConfirmBody
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ConfirmBody
- name: CronJobBody
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: CronJobBody
- name: cron_job_create
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: cron_job_create
- name: cron_job_delete
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: cron_job_delete
- name: cron_job_run
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: cron_job_run
- name: cron_job_update
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: cron_job_update
- name: ops_actions_capabilities
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_actions_capabilities
- name: ops_backup_export
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_backup_export
- name: ops_backup_import
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_backup_import
- name: ops_daemon_action
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_daemon_action
- name: ops_daemons_status
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_daemons_status
- name: ops_dreaming_run
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_dreaming_run
- name: ops_reload_config
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_reload_config
- name: ops_snapshot_create
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_snapshot_create
- name: ops_snapshot_restore
  file: src/sevn/ui/dashboard/api/ops_control.py
  symbol: ops_snapshot_restore
- name: run_snapshots
  file: src/sevn/ui/dashboard/api/runs.py
  symbol: run_snapshots
- name: global_search
  file: src/sevn/ui/dashboard/api/search.py
  symbol: global_search
- name: SecretRevealResponse
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: SecretRevealResponse
- name: SecretsEntriesResponse
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: SecretsEntriesResponse
- name: SecretsStoreStatusResponse
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: SecretsStoreStatusResponse
- name: secrets_store_entries_list
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: secrets_store_entries_list
- name: secrets_store_entry_delete
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: secrets_store_entry_delete
- name: secrets_store_entry_put
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: secrets_store_entry_put
- name: secrets_store_entry_reveal
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: secrets_store_entry_reveal
- name: secrets_store_status
  file: src/sevn/ui/dashboard/api/secrets_store.py
  symbol: secrets_store_status
- name: CreateImproveJobBody
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: CreateImproveJobBody
- name: SelfImproveCycleBody
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: SelfImproveCycleBody
- name: approve_self_improve_plan
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: approve_self_improve_plan
- name: create_self_improve_job
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: create_self_improve_job
- name: self_improve_cycle
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_cycle
- name: self_improve_experiments
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_experiments
- name: self_improve_feedback
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_feedback
- name: self_improve_job_eval_report
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_job_eval_report
- name: self_improve_jobs
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_jobs
- name: self_improve_rlm_training
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_rlm_training
- name: self_improve_trajectories
  file: src/sevn/ui/dashboard/api/self_improve.py
  symbol: self_improve_trajectories
- name: replay_turn
  file: src/sevn/ui/dashboard/api/sessions.py
  symbol: replay_turn
- name: session_api_calls
  file: src/sevn/ui/dashboard/api/sessions.py
  symbol: session_api_calls
- name: session_api_calls_csv
  file: src/sevn/ui/dashboard/api/sessions.py
  symbol: session_api_calls_csv
- name: sessions
  file: src/sevn/ui/dashboard/api/sessions.py
  symbol: sessions
- name: PutConstitutionBody
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: PutConstitutionBody
- name: PutSpecKitOptionsBody
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: PutSpecKitOptionsBody
- name: TestInvokeBody
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: TestInvokeBody
- name: get_constitution
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: get_constitution
- name: get_constitution_template
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: get_constitution_template
- name: get_spec_kit_options
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: get_spec_kit_options
- name: get_spec_kit_runs
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: get_spec_kit_runs
- name: post_test_invoke
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: post_test_invoke
- name: put_constitution
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: put_constitution
- name: put_spec_kit_options
  file: src/sevn/ui/dashboard/api/spec_kit.py
  symbol: put_spec_kit_options
- name: onboarding_overview
  file: src/sevn/ui/dashboard/api/surfaces.py
  symbol: onboarding_overview
- name: telegram_menu_overview
  file: src/sevn/ui/dashboard/api/surfaces.py
  symbol: telegram_menu_overview
- name: telegram_menu_put
  file: src/sevn/ui/dashboard/api/surfaces.py
  symbol: telegram_menu_put
- name: users_rbac_overview
  file: src/sevn/ui/dashboard/api/surfaces.py
  symbol: users_rbac_overview
- name: web_apps_overview
  file: src/sevn/ui/dashboard/api/surfaces.py
  symbol: web_apps_overview
- name: web_apps_put
  file: src/sevn/ui/dashboard/api/surfaces.py
  symbol: web_apps_put
- name: budget_summary
  file: src/sevn/ui/dashboard/api/system.py
  symbol: budget_summary
- name: config_validate
  file: src/sevn/ui/dashboard/api/system.py
  symbol: config_validate
- name: config_write
  file: src/sevn/ui/dashboard/api/system.py
  symbol: config_write
- name: migrate_preview
  file: src/sevn/ui/dashboard/api/system.py
  symbol: migrate_preview
- name: page_agent_intent
  file: src/sevn/ui/dashboard/api/system.py
  symbol: page_agent_intent
- name: provider_oauth_reauth
  file: src/sevn/ui/dashboard/api/system.py
  symbol: provider_oauth_reauth
- name: providers_health
  file: src/sevn/ui/dashboard/api/system.py
  symbol: providers_health
- name: proxy_logs
  file: src/sevn/ui/dashboard/api/system.py
  symbol: proxy_logs
- name: proxy_restart
  file: src/sevn/ui/dashboard/api/system.py
  symbol: proxy_restart
- name: proxy_status
  file: src/sevn/ui/dashboard/api/system.py
  symbol: proxy_status
- name: system_logging_get
  file: src/sevn/ui/dashboard/api/system.py
  symbol: system_logging_get
- name: system_logging_put
  file: src/sevn/ui/dashboard/api/system.py
  symbol: system_logging_put
- name: upgrade_restart
  file: src/sevn/ui/dashboard/api/system.py
  symbol: upgrade_restart
- name: TerminalSessionResponse
  file: src/sevn/ui/dashboard/api/terminal.py
  symbol: TerminalSessionResponse
- name: terminal_session
  file: src/sevn/ui/dashboard/api/terminal.py
  symbol: terminal_session
- name: ToolApprovalVerdictBody
  file: src/sevn/ui/dashboard/api/tool_approvals.py
  symbol: ToolApprovalVerdictBody
- name: tool_approval_decide
  file: src/sevn/ui/dashboard/api/tool_approvals.py
  symbol: tool_approval_decide
- name: tool_approvals_pending
  file: src/sevn/ui/dashboard/api/tool_approvals.py
  symbol: tool_approvals_pending
- name: trace_detail
  file: src/sevn/ui/dashboard/api/traces.py
  symbol: trace_detail
- name: traces_list
  file: src/sevn/ui/dashboard/api/traces.py
  symbol: traces_list
- name: traces_query
  file: src/sevn/ui/dashboard/api/traces.py
  symbol: traces_query
- name: ActionDescriptor
  file: src/sevn/ui/dashboard/dashboard_schema.py
  symbol: ActionDescriptor
- name: TabDescriptor
  file: src/sevn/ui/dashboard/dashboard_schema.py
  symbol: TabDescriptor
- name: ViewDescriptor
  file: src/sevn/ui/dashboard/dashboard_schema.py
  symbol: ViewDescriptor
- name: descriptor_slugs
  file: src/sevn/ui/dashboard/dashboard_schema.py
  symbol: descriptor_slugs
- name: missing_descriptor_slugs
  file: src/sevn/ui/dashboard/dashboard_schema.py
  symbol: missing_descriptor_slugs
- name: approval_timeline_from_traces
  file: src/sevn/ui/dashboard/query/audit_analytics.py
  symbol: approval_timeline_from_traces
- name: audit_timeline_from_traces
  file: src/sevn/ui/dashboard/query/audit_analytics.py
  symbol: audit_timeline_from_traces
- name: daily_volume_from_traces
  file: src/sevn/ui/dashboard/query/audit_analytics.py
  symbol: daily_volume_from_traces
- name: tool_frequency_from_traces
  file: src/sevn/ui/dashboard/query/audit_analytics.py
  symbol: tool_frequency_from_traces
- name: budget_summary_from_traces
  file: src/sevn/ui/dashboard/query/budget.py
  symbol: budget_summary_from_traces
- name: PageParams
  file: src/sevn/ui/dashboard/query/pagination.py
  symbol: PageParams
- name: clamp_limit
  file: src/sevn/ui/dashboard/query/pagination.py
  symbol: clamp_limit
- name: fts_query_text
  file: src/sevn/ui/dashboard/query/search.py
  symbol: fts_query_text
- name: search_trace_events
  file: src/sevn/ui/dashboard/query/search.py
  symbol: search_trace_events
- name: list_active_run_snapshots
  file: src/sevn/ui/dashboard/query/storage.py
  symbol: list_active_run_snapshots
- name: list_gateway_sessions
  file: src/sevn/ui/dashboard/query/storage.py
  symbol: list_gateway_sessions
- name: ensure_trace_connection
  file: src/sevn/ui/dashboard/query/traces.py
  symbol: ensure_trace_connection
- name: get_span_with_children
  file: src/sevn/ui/dashboard/query/traces.py
  symbol: get_span_with_children
- name: list_provider_calls
  file: src/sevn/ui/dashboard/query/traces.py
  symbol: list_provider_calls
- name: list_trace_events
  file: src/sevn/ui/dashboard/query/traces.py
  symbol: list_trace_events
- name: DashboardAuthService
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: DashboardAuthService
- name: DashboardClaims
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: DashboardClaims
- name: apply_tunnel_local_open_policy
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: apply_tunnel_local_open_policy
- name: dashboard_local_open_configured
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: dashboard_local_open_configured
- name: infrastructure_tunnel_mode
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: infrastructure_tunnel_mode
- name: is_loopback_client_host
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: is_loopback_client_host
- name: local_open_effective
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: local_open_effective
- name: sevn_json_path_from_request
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: sevn_json_path_from_request
- name: synthetic_owner_claims
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: synthetic_owner_claims
- name: tunnel_active
  file: src/sevn/ui/dashboard/services/auth.py
  symbol: tunnel_active
- name: changed_top_level_keys
  file: src/sevn/ui/dashboard/services/config_full.py
  symbol: changed_top_level_keys
- name: is_redacted_placeholder
  file: src/sevn/ui/dashboard/services/config_full.py
  symbol: is_redacted_placeholder
- name: merge_redacted_config
  file: src/sevn/ui/dashboard/services/config_full.py
  symbol: merge_redacted_config
- name: validate_against_json_schema
  file: src/sevn/ui/dashboard/services/config_full.py
  symbol: validate_against_json_schema
- name: validate_config_document
  file: src/sevn/ui/dashboard/services/config_full.py
  symbol: validate_config_document
- name: validation_errors_from_exception
  file: src/sevn/ui/dashboard/services/config_full.py
  symbol: validation_errors_from_exception
- name: emit_mission_audit
  file: src/sevn/ui/dashboard/services/mission_audit.py
  symbol: emit_mission_audit
- name: mission_runtime_alerts
  file: src/sevn/ui/dashboard/services/mission_runtime.py
  symbol: mission_runtime_alerts
- name: mission_runtime_channels
  file: src/sevn/ui/dashboard/services/mission_runtime.py
  symbol: mission_runtime_channels
- name: build_backup_export_bytes
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: build_backup_export_bytes
- name: build_daemons_status
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: build_daemons_status
- name: confirm_token_valid
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: confirm_token_valid
- name: create_workspace_snapshot
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: create_workspace_snapshot
- name: cron_job_payload
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: cron_job_payload
- name: daemon_control
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: daemon_control
- name: dispatch_cron_job_now
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: dispatch_cron_job_now
- name: enqueue_self_improve_cycle
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: enqueue_self_improve_cycle
- name: import_backup_archive
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: import_backup_archive
- name: install_bundled_skill
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: install_bundled_skill
- name: list_bundled_skill_names
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: list_bundled_skill_names
- name: reload_workspace_in_process
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: reload_workspace_in_process
- name: restore_workspace_snapshot
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: restore_workspace_snapshot
- name: run_dreaming_cycle
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: run_dreaming_cycle
- name: set_user_skill_quarantine
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: set_user_skill_quarantine
- name: uninstall_user_skill
  file: src/sevn/ui/dashboard/services/ops_control.py
  symbol: uninstall_user_skill
- name: SandboxTerminalError
  file: src/sevn/ui/dashboard/services/sandbox_terminal.py
  symbol: SandboxTerminalError
- name: SandboxTerminalSession
  file: src/sevn/ui/dashboard/services/sandbox_terminal.py
  symbol: SandboxTerminalSession
- name: create_sandbox_terminal_session
  file: src/sevn/ui/dashboard/services/sandbox_terminal.py
  symbol: create_sandbox_terminal_session
- name: TerminalSessionRegistry
  file: src/sevn/ui/dashboard/services/terminal_registry.py
  symbol: TerminalSessionRegistry
- name: TerminalUpgradeTicket
  file: src/sevn/ui/dashboard/services/terminal_registry.py
  symbol: TerminalUpgradeTicket
- name: ToolSkillHealthRow
  file: src/sevn/ui/dashboard/services/tool_skill_health.py
  symbol: ToolSkillHealthRow
- name: ToolSkillHealthService
  file: src/sevn/ui/dashboard/services/tool_skill_health.py
  symbol: ToolSkillHealthService
- name: content_has_secret_refs
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: content_has_secret_refs
- name: graph_json_for_workspace
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: graph_json_for_workspace
- name: is_editable_extension
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: is_editable_extension
- name: is_excluded_path
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: is_excluded_path
- name: is_skills_core_write_blocked
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: is_skills_core_write_blocked
- name: resolve_confined
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: resolve_confined
- name: resolve_root_base
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: resolve_root_base
- name: soft_trash_destination
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: soft_trash_destination
- name: validate_utf8_text
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: validate_utf8_text
- name: workspace_relative_posix
  file: src/sevn/ui/dashboard/services/workspace_fs.py
  symbol: workspace_relative_posix
- name: build_nav_payload
  file: src/sevn/ui/dashboard/tab_registry.py
  symbol: build_nav_payload
- name: registry_tab_slug
  file: src/sevn/ui/dashboard/tab_registry.py
  symbol: registry_tab_slug
- name: tab_slug
  file: src/sevn/ui/dashboard/tab_registry.py
  symbol: tab_slug
- name: DashboardHub
  file: src/sevn/ui/dashboard/ws.py
  symbol: DashboardHub
- name: dashboard_ws_endpoint
  file: src/sevn/ui/dashboard/ws.py
  symbol: dashboard_ws_endpoint
- name: active_terminal_sessions
  file: src/sevn/ui/dashboard/ws_terminal.py
  symbol: active_terminal_sessions
- name: dashboard_terminal_ws_endpoint
  file: src/sevn/ui/dashboard/ws_terminal.py
  symbol: dashboard_terminal_ws_endpoint
- name: OpenUIBridge
  file: src/sevn/ui/openui/bridge.py
  symbol: OpenUIBridge
- name: build_content_security_policy
  file: src/sevn/ui/openui/bridge.py
  symbol: build_content_security_policy
- name: inject_submit_token_into_html
  file: src/sevn/ui/openui/bridge.py
  symbol: inject_submit_token_into_html
- name: build_openui_dispatch_payload
  file: src/sevn/ui/openui/callback.py
  symbol: build_openui_dispatch_payload
- name: normalize_webchat_openui_callback
  file: src/sevn/ui/openui/callback.py
  symbol: normalize_webchat_openui_callback
- name: parse_query_dict
  file: src/sevn/ui/openui/callback.py
  symbol: parse_query_dict
- name: build_openui_payload
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: build_openui_payload
- name: cards_fallback_text
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: cards_fallback_text
- name: compose_cards_html
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: compose_cards_html
- name: compose_table_html
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: compose_table_html
- name: escape_html
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: escape_html
- name: parse_json_list
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: parse_json_list
- name: table_fallback_text
  file: src/sevn/ui/openui/canvas_compose.py
  symbol: table_fallback_text
- name: build_openui_delivery_metadata
  file: src/sevn/ui/openui/delivery.py
  symbol: build_openui_delivery_metadata
- name: build_telegram_openui_inline_keyboard
  file: src/sevn/ui/openui/delivery.py
  symbol: build_telegram_openui_inline_keyboard
- name: Drop
  file: src/sevn/ui/openui/models.py
  symbol: Drop
- name: OpenUIConfig
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIConfig
- name: OpenUIRenderError
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIRenderError
- name: OpenUIRenderResult
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIRenderResult
- name: OpenUIRuntimeDeps
  file: src/sevn/ui/openui/models.py
  symbol: OpenUIRuntimeDeps
- name: RasteriseCaps
  file: src/sevn/ui/openui/models.py
  symbol: RasteriseCaps
- name: SanitiseResult
  file: src/sevn/ui/openui/models.py
  symbol: SanitiseResult
- name: effective_openui_config
  file: src/sevn/ui/openui/models.py
  symbol: effective_openui_config
- name: rasterise_pdf_bytes
  file: src/sevn/ui/openui/rasteriser.py
  symbol: rasterise_pdf_bytes
- name: rasterise_png_bytes
  file: src/sevn/ui/openui/rasteriser.py
  symbol: rasterise_png_bytes
- name: sanitise
  file: src/sevn/ui/openui/sanitiser.py
  symbol: sanitise
- name: OpenUIRecord
  file: src/sevn/ui/openui/store.py
  symbol: OpenUIRecord
- name: OpenUIStore
  file: src/sevn/ui/openui/store.py
  symbol: OpenUIStore
- name: sign_token
  file: src/sevn/ui/openui/tokens.py
  symbol: sign_token
- name: verify_token
  file: src/sevn/ui/openui/tokens.py
  symbol: verify_token
- name: verify_token_status
  file: src/sevn/ui/openui/tokens.py
  symbol: verify_token_status
- name: openui_render
  file: src/sevn/ui/openui/tools_register.py
  symbol: openui_render
- name: register_openui_tools
  file: src/sevn/ui/openui/tools_register.py
  symbol: register_openui_tools
- name: register_shared_ui_routes
  file: src/sevn/ui/shared/__init__.py
  symbol: register_shared_ui_routes
- name: serve_shared_ui_asset
  file: src/sevn/ui/shared/__init__.py
  symbol: serve_shared_ui_asset
- name: serve_style_asset
  file: src/sevn/ui/style/__init__.py
  symbol: serve_style_asset
- name: brand_header
  file: src/sevn/ui/terminal_theme.py
  symbol: brand_header
- name: style_error
  file: src/sevn/ui/terminal_theme.py
  symbol: style_error
- name: style_muted
  file: src/sevn/ui/terminal_theme.py
  symbol: style_muted
- name: style_success
  file: src/sevn/ui/terminal_theme.py
  symbol: style_success
- name: style_warning
  file: src/sevn/ui/terminal_theme.py
  symbol: style_warning
specs: []
personas: []
---

## Purpose

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Purpose.

## Public Interface

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Public Interface.

## Data Model

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Data Model.

## Internal Architecture

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Internal Architecture.

## Behavior

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Behavior.

## Failure Modes

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Failure Modes.

## Amendments (spec-36-sub-agents)

Observability group gains **Sub-agents** tab: L1/L2 count chips, running table with
kill actions, recent history, read-only limits. APIs:
`GET /api/v1/mission/subagents`, `POST .../kill`, `POST .../kill_all` (D13).

## Test Strategy

Offline scaffold for Mission Control (dashboard) — Spec (spec-24-dashboard) — Test Strategy.
