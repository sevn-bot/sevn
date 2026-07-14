---
id: spec-10-schema-ontology
kind: spec
title: Schema & ontology — Spec
status: done
owner: Alex
summary: 'Define the runtime ontology for Triager output and related labels across
  the agent core: canonical field names, closed enums, typing conventions, and how
  they compose with executor dispatch described '
last_updated: '2026-07-14'
fingerprint: sha256:5974dac305546f994730735acb3807d00aff5d24e1ad06c19cbab944953f0f67
related: []
sources:
- src/sevn/config/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
- spec-04-tracing
- spec-05-llm-transports
- spec-06-secrets
- spec-07-egress-proxy
- spec-08-sandbox
- spec-09-security-scanner
build_phase: null
interfaces:
- name: SevnConfigError
  file: src/sevn/config/errors.py
  symbol: SevnConfigError
- name: SevnJsonNotFoundError
  file: src/sevn/config/errors.py
  symbol: SevnJsonNotFoundError
- name: TriagerUnavailable
  file: src/sevn/config/errors.py
  symbol: TriagerUnavailable
- name: UnsupportedSchemaVersionError
  file: src/sevn/config/errors.py
  symbol: UnsupportedSchemaVersionError
- name: field_help_for
  file: src/sevn/config/field_help.py
  symbol: field_help_for
- name: load_config_field_help
  file: src/sevn/config/field_help.py
  symbol: load_config_field_help
- name: urls_in_help_text
  file: src/sevn/config/field_help.py
  symbol: urls_in_help_text
- name: ReasoningParams
  file: src/sevn/config/llm_params.py
  symbol: ReasoningParams
- name: SamplingParams
  file: src/sevn/config/llm_params.py
  symbol: SamplingParams
- name: builtin_llm_params_doc
  file: src/sevn/config/llm_params.py
  symbol: builtin_llm_params_doc
- name: load_or_create_llm_params_doc
  file: src/sevn/config/llm_params.py
  symbol: load_or_create_llm_params_doc
- name: resolve_effective_max_output_tokens
  file: src/sevn/config/llm_params.py
  symbol: resolve_effective_max_output_tokens
- name: resolve_llm_params
  file: src/sevn/config/llm_params.py
  symbol: resolve_llm_params
- name: resolve_llm_params_max_output_tokens
  file: src/sevn/config/llm_params.py
  symbol: resolve_llm_params_max_output_tokens
- name: resolve_llm_request_params
  file: src/sevn/config/llm_params.py
  symbol: resolve_llm_request_params
- name: resolve_minimax_thinking_request
  file: src/sevn/config/llm_params.py
  symbol: resolve_minimax_thinking_request
- name: resolve_reasoning_params
  file: src/sevn/config/llm_params.py
  symbol: resolve_reasoning_params
- name: resolve_reasoning_request
  file: src/sevn/config/llm_params.py
  symbol: resolve_reasoning_request
- name: set_agent_model_max_output_tokens
  file: src/sevn/config/llm_params.py
  symbol: set_agent_model_max_output_tokens
- name: transport_for
  file: src/sevn/config/llm_params.py
  symbol: transport_for
- name: validate_llm_params_doc
  file: src/sevn/config/llm_params.py
  symbol: validate_llm_params_doc
- name: write_llm_params_doc
  file: src/sevn/config/llm_params.py
  symbol: write_llm_params_doc
- name: bound_sevn_json_path
  file: src/sevn/config/loader.py
  symbol: bound_sevn_json_path
- name: ensure_schema_supported
  file: src/sevn/config/loader.py
  symbol: ensure_schema_supported
- name: find_sevn_json
  file: src/sevn/config/loader.py
  symbol: find_sevn_json
- name: load_workspace
  file: src/sevn/config/loader.py
  symbol: load_workspace
- name: operator_home_dir
  file: src/sevn/config/loader.py
  symbol: operator_home_dir
- name: resolve_sevn_json_path
  file: src/sevn/config/loader.py
  symbol: resolve_sevn_json_path
- name: ModelSlot
  file: src/sevn/config/model_resolution.py
  symbol: ModelSlot
- name: apply_model_to_picker_slot
  file: src/sevn/config/model_resolution.py
  symbol: apply_model_to_picker_slot
- name: codemode_enabled
  file: src/sevn/config/model_resolution.py
  symbol: codemode_enabled
- name: codemode_max_retries
  file: src/sevn/config/model_resolution.py
  symbol: codemode_max_retries
- name: codemode_resource_limits
  file: src/sevn/config/model_resolution.py
  symbol: codemode_resource_limits
- name: diagnostics_agent_enabled
  file: src/sevn/config/model_resolution.py
  symbol: diagnostics_agent_enabled
- name: fill_missing_model_slots_from_triager
  file: src/sevn/config/model_resolution.py
  symbol: fill_missing_model_slots_from_triager
- name: is_minimax_catalog_model
  file: src/sevn/config/model_resolution.py
  symbol: is_minimax_catalog_model
- name: is_minimax_model
  file: src/sevn/config/model_resolution.py
  symbol: is_minimax_model
- name: list_catalog_model_ids
  file: src/sevn/config/model_resolution.py
  symbol: list_catalog_model_ids
- name: maybe_split_unified_model_on_config_set
  file: src/sevn/config/model_resolution.py
  symbol: maybe_split_unified_model_on_config_set
- name: model_picker_slot_keys
  file: src/sevn/config/model_resolution.py
  symbol: model_picker_slot_keys
- name: model_picker_slots_for_key
  file: src/sevn/config/model_resolution.py
  symbol: model_picker_slots_for_key
- name: model_slot_for_config_dot_path
  file: src/sevn/config/model_resolution.py
  symbol: model_slot_for_config_dot_path
- name: native_model_enabled
  file: src/sevn/config/model_resolution.py
  symbol: native_model_enabled
- name: resolve_diagnostics_model
  file: src/sevn/config/model_resolution.py
  symbol: resolve_diagnostics_model
- name: resolve_main_model_id
  file: src/sevn/config/model_resolution.py
  symbol: resolve_main_model_id
- name: resolve_minimax_anthropic_base_url
  file: src/sevn/config/model_resolution.py
  symbol: resolve_minimax_anthropic_base_url
- name: resolve_minimax_openai_base_url
  file: src/sevn/config/model_resolution.py
  symbol: resolve_minimax_openai_base_url
- name: resolve_model_slot
  file: src/sevn/config/model_resolution.py
  symbol: resolve_model_slot
- name: resolve_slot_fallback_model_ids
  file: src/sevn/config/model_resolution.py
  symbol: resolve_slot_fallback_model_ids
- name: resolve_transport_for_model_id
  file: src/sevn/config/model_resolution.py
  symbol: resolve_transport_for_model_id
- name: resolve_wire_model_id
  file: src/sevn/config/model_resolution.py
  symbol: resolve_wire_model_id
- name: use_main_model_for_all
  file: src/sevn/config/model_resolution.py
  symbol: use_main_model_for_all
- name: user_model_extraction_enabled
  file: src/sevn/config/model_resolution.py
  symbol: user_model_extraction_enabled
- name: workspace_has_minimax_catalog_model
  file: src/sevn/config/model_resolution.py
  symbol: workspace_has_minimax_catalog_model
- name: effective_my_sevn
  file: src/sevn/config/my_sevn.py
  symbol: effective_my_sevn
- name: effective_my_sevn_executors
  file: src/sevn/config/my_sevn.py
  symbol: effective_my_sevn_executors
- name: effective_my_sevn_issues
  file: src/sevn/config/my_sevn.py
  symbol: effective_my_sevn_issues
- name: effective_my_sevn_pipelines
  file: src/sevn/config/my_sevn.py
  symbol: effective_my_sevn_pipelines
- name: effective_my_sevn_sync
  file: src/sevn/config/my_sevn.py
  symbol: effective_my_sevn_sync
- name: persist_my_sevn_repo_path
  file: src/sevn/config/my_sevn.py
  symbol: persist_my_sevn_repo_path
- name: resolve_my_sevn_repo_path
  file: src/sevn/config/my_sevn.py
  symbol: resolve_my_sevn_repo_path
- name: MissingProviderCredential
  file: src/sevn/config/provider_credential_validate.py
  symbol: MissingProviderCredential
- name: collect_missing_provider_credentials
  file: src/sevn/config/provider_credential_validate.py
  symbol: collect_missing_provider_credentials
- name: collect_unused_declared_providers
  file: src/sevn/config/provider_credential_validate.py
  symbol: collect_unused_declared_providers
- name: declared_provider_names
  file: src/sevn/config/provider_credential_validate.py
  symbol: declared_provider_names
- name: format_unused_provider_warning
  file: src/sevn/config/provider_credential_validate.py
  symbol: format_unused_provider_warning
- name: provider_credential_resolvable
  file: src/sevn/config/provider_credential_validate.py
  symbol: provider_credential_resolvable
- name: validate_provider_credentials
  file: src/sevn/config/provider_credential_validate.py
  symbol: validate_provider_credentials
- name: ProviderBinding
  file: src/sevn/config/provider_registry.py
  symbol: ProviderBinding
- name: provider_credential_ref
  file: src/sevn/config/provider_registry.py
  symbol: provider_credential_ref
- name: resolve_provider_binding
  file: src/sevn/config/provider_registry.py
  symbol: resolve_provider_binding
- name: resolve_provider_for_model_id
  file: src/sevn/config/provider_registry.py
  symbol: resolve_provider_for_model_id
- name: apply_provider_credential_bindings
  file: src/sevn/config/provider_secrets.py
  symbol: apply_provider_credential_bindings
- name: assigned_provider_names_from_doc
  file: src/sevn/config/provider_secrets.py
  symbol: assigned_provider_names_from_doc
- name: handoff_provider_secret_keys
  file: src/sevn/config/provider_secrets.py
  symbol: handoff_provider_secret_keys
- name: migrate_legacy_provider_api_key
  file: src/sevn/config/provider_secrets.py
  symbol: migrate_legacy_provider_api_key
- name: provider_credential_ref_for_name
  file: src/sevn/config/provider_secrets.py
  symbol: provider_credential_ref_for_name
- name: provider_secret_alias
  file: src/sevn/config/provider_secrets.py
  symbol: provider_secret_alias
- name: resolve_handoff_secret_alias
  file: src/sevn/config/provider_secrets.py
  symbol: resolve_handoff_secret_alias
- name: agent_max_output_tokens_ceiling
  file: src/sevn/config/sections/accessors.py
  symbol: agent_max_output_tokens_ceiling
- name: browser_settings
  file: src/sevn/config/sections/accessors.py
  symbol: browser_settings
- name: cascade_budget_s
  file: src/sevn/config/sections/accessors.py
  symbol: cascade_budget_s
- name: complexity_clamp_confidence_threshold
  file: src/sevn/config/sections/accessors.py
  symbol: complexity_clamp_confidence_threshold
- name: complexity_clamp_short_word_limit
  file: src/sevn/config/sections/accessors.py
  symbol: complexity_clamp_short_word_limit
- name: rlm_json_dict
  file: src/sevn/config/sections/accessors.py
  symbol: rlm_json_dict
- name: show_intent_footer
  file: src/sevn/config/sections/accessors.py
  symbol: show_intent_footer
- name: tier_b_answer_mode
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_answer_mode
- name: tier_b_count_planning
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_count_planning
- name: tier_b_executor_timeout_s
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_executor_timeout_s
- name: tier_b_max_output_tokens
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_max_output_tokens
- name: tier_b_rounds
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_rounds
- name: tier_b_rounds_expanded
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_rounds_expanded
- name: tier_b_skill_cap
  file: src/sevn/config/sections/accessors.py
  symbol: tier_b_skill_cap
- name: tier_cd_executor_timeout_s
  file: src/sevn/config/sections/accessors.py
  symbol: tier_cd_executor_timeout_s
- name: tool_as_skill_auto_route_enabled
  file: src/sevn/config/sections/accessors.py
  symbol: tool_as_skill_auto_route_enabled
- name: tool_debug_result_max_chars
  file: src/sevn/config/sections/accessors.py
  symbol: tool_debug_result_max_chars
- name: AgentCodemodeConfig
  file: src/sevn/config/sections/agent.py
  symbol: AgentCodemodeConfig
- name: AgentDiagnosticsConfig
  file: src/sevn/config/sections/agent.py
  symbol: AgentDiagnosticsConfig
- name: AgentWorkspaceConfig
  file: src/sevn/config/sections/agent.py
  symbol: AgentWorkspaceConfig
- name: ChannelsWorkspaceSectionConfig
  file: src/sevn/config/sections/channels.py
  symbol: ChannelsWorkspaceSectionConfig
- name: OwnerScannerOverrides
  file: src/sevn/config/sections/channels.py
  symbol: OwnerScannerOverrides
- name: TelegramChannelConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramChannelConfig
- name: TelegramInlineConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramInlineConfig
- name: TelegramInlineSourcesConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramInlineSourcesConfig
- name: TelegramQuickActionsConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramQuickActionsConfig
- name: TelegramReplyKeyboardConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramReplyKeyboardConfig
- name: TelegramRichConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramRichConfig
- name: TelegramWebappConfig
  file: src/sevn/config/sections/channels.py
  symbol: TelegramWebappConfig
- name: VoiceConfig
  file: src/sevn/config/sections/channels.py
  symbol: VoiceConfig
- name: WebChatChannelConfig
  file: src/sevn/config/sections/channels.py
  symbol: WebChatChannelConfig
- name: channel_extra_dict
  file: src/sevn/config/sections/channels.py
  symbol: channel_extra_dict
- name: channel_is_enabled
  file: src/sevn/config/sections/channels.py
  symbol: channel_is_enabled
- name: resolve_busy_input_mode
  file: src/sevn/config/sections/channels.py
  symbol: resolve_busy_input_mode
- name: AlrcaAgentConfig
  file: src/sevn/config/sections/coding_agents.py
  symbol: AlrcaAgentConfig
- name: CodingAgentsWorkspaceConfig
  file: src/sevn/config/sections/coding_agents.py
  symbol: CodingAgentsWorkspaceConfig
- name: LitellmLapAgentConfig
  file: src/sevn/config/sections/coding_agents.py
  symbol: LitellmLapAgentConfig
- name: TelegramBindingConfig
  file: src/sevn/config/sections/coding_agents.py
  symbol: TelegramBindingConfig
- name: parse_coding_agents_section
  file: src/sevn/config/sections/coding_agents.py
  symbol: parse_coding_agents_section
- name: DashboardPageAgentConfig
  file: src/sevn/config/sections/dashboard.py
  symbol: DashboardPageAgentConfig
- name: DashboardWorkspaceConfig
  file: src/sevn/config/sections/dashboard.py
  symbol: DashboardWorkspaceConfig
- name: DocsWorkspaceSectionConfig
  file: src/sevn/config/sections/docs.py
  symbol: DocsWorkspaceSectionConfig
- name: ReadmeWorkspaceConfig
  file: src/sevn/config/sections/docs.py
  symbol: ReadmeWorkspaceConfig
- name: MySevnBugsWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnBugsWorkspaceConfig
- name: MySevnExecutorsWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnExecutorsWorkspaceConfig
- name: MySevnFeaturesWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnFeaturesWorkspaceConfig
- name: MySevnIssuesWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnIssuesWorkspaceConfig
- name: MySevnPipelinesWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnPipelinesWorkspaceConfig
- name: MySevnPromotionWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnPromotionWorkspaceConfig
- name: MySevnSyncWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnSyncWorkspaceConfig
- name: MySevnWorkspaceBackupConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnWorkspaceBackupConfig
- name: MySevnWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: MySevnWorkspaceConfig
- name: SpecKitOptionsWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: SpecKitOptionsWorkspaceConfig
- name: SpecKitWorkspaceConfig
  file: src/sevn/config/sections/evolution.py
  symbol: SpecKitWorkspaceConfig
- name: ExecutorsWorkspaceConfig
  file: src/sevn/config/sections/executors.py
  symbol: ExecutorsWorkspaceConfig
- name: PlanApprovalWorkspaceConfig
  file: src/sevn/config/sections/executors.py
  symbol: PlanApprovalWorkspaceConfig
- name: RlmWorkspaceConfig
  file: src/sevn/config/sections/executors.py
  symbol: RlmWorkspaceConfig
- name: TierCdExecutorConfig
  file: src/sevn/config/sections/executors.py
  symbol: TierCdExecutorConfig
- name: TierCdLambdaRlmConfig
  file: src/sevn/config/sections/executors.py
  symbol: TierCdLambdaRlmConfig
- name: OpenUIWorkspaceConfig
  file: src/sevn/config/sections/features.py
  symbol: OpenUIWorkspaceConfig
- name: PluginHookEntryConfig
  file: src/sevn/config/sections/features.py
  symbol: PluginHookEntryConfig
- name: SecondBrainFetchConfig
  file: src/sevn/config/sections/features.py
  symbol: SecondBrainFetchConfig
- name: SecondBrainPathsConfig
  file: src/sevn/config/sections/features.py
  symbol: SecondBrainPathsConfig
- name: SecondBrainWorkspaceConfig
  file: src/sevn/config/sections/features.py
  symbol: SecondBrainWorkspaceConfig
- name: DispatcherStateWorkspaceConfig
  file: src/sevn/config/sections/gateway.py
  symbol: DispatcherStateWorkspaceConfig
- name: GatewayBudgetConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewayBudgetConfig
- name: GatewayConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewayConfig
- name: GatewayFirstSessionIntroConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewayFirstSessionIntroConfig
- name: GatewayOutputConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewayOutputConfig
- name: GatewayRestartConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewayRestartConfig
- name: GatewaySessionMirrorConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewaySessionMirrorConfig
- name: GatewaySteerConfig
  file: src/sevn/config/sections/gateway.py
  symbol: GatewaySteerConfig
- name: HarnessSnapshotSubConfig
  file: src/sevn/config/sections/gateway.py
  symbol: HarnessSnapshotSubConfig
- name: HarnessWorkspaceConfig
  file: src/sevn/config/sections/gateway.py
  symbol: HarnessWorkspaceConfig
- name: ReplayWorkspaceConfig
  file: src/sevn/config/sections/gateway.py
  symbol: ReplayWorkspaceConfig
- name: LoggingCloudConfig
  file: src/sevn/config/sections/logging.py
  symbol: LoggingCloudConfig
- name: LoggingCloudProviderConfig
  file: src/sevn/config/sections/logging.py
  symbol: LoggingCloudProviderConfig
- name: LoggingWorkspaceConfig
  file: src/sevn/config/sections/logging.py
  symbol: LoggingWorkspaceConfig
- name: DreamingLlmRankerWorkspaceConfig
  file: src/sevn/config/sections/memory.py
  symbol: DreamingLlmRankerWorkspaceConfig
- name: DreamingScoringWorkspaceConfig
  file: src/sevn/config/sections/memory.py
  symbol: DreamingScoringWorkspaceConfig
- name: DreamingWorkspaceConfig
  file: src/sevn/config/sections/memory.py
  symbol: DreamingWorkspaceConfig
- name: LcmWorkspaceConfig
  file: src/sevn/config/sections/memory.py
  symbol: LcmWorkspaceConfig
- name: MemoryPreCompactionFlushWorkspaceConfig
  file: src/sevn/config/sections/memory.py
  symbol: MemoryPreCompactionFlushWorkspaceConfig
- name: MemoryWorkspaceSectionConfig
  file: src/sevn/config/sections/memory.py
  symbol: MemoryWorkspaceSectionConfig
- name: UserModelWorkspaceConfig
  file: src/sevn/config/sections/memory.py
  symbol: UserModelWorkspaceConfig
- name: BrowserWorkspaceConfig
  file: src/sevn/config/sections/ops.py
  symbol: BrowserWorkspaceConfig
- name: OnboardingPersonalityDraftConfig
  file: src/sevn/config/sections/ops.py
  symbol: OnboardingPersonalityDraftConfig
- name: OnboardingWorkspaceSectionConfig
  file: src/sevn/config/sections/ops.py
  symbol: OnboardingWorkspaceSectionConfig
- name: TelemetryWorkspaceSectionConfig
  file: src/sevn/config/sections/ops.py
  symbol: TelemetryWorkspaceSectionConfig
- name: TriggersWorkspaceConfig
  file: src/sevn/config/sections/ops.py
  symbol: TriggersWorkspaceConfig
- name: WorkspaceOutputSectionConfig
  file: src/sevn/config/sections/ops.py
  symbol: WorkspaceOutputSectionConfig
- name: ProviderEntryConfig
  file: src/sevn/config/sections/providers.py
  symbol: ProviderEntryConfig
- name: ProviderModelOverrideConfig
  file: src/sevn/config/sections/providers.py
  symbol: ProviderModelOverrideConfig
- name: ProvidersWorkspaceSectionConfig
  file: src/sevn/config/sections/providers.py
  symbol: ProvidersWorkspaceSectionConfig
- name: provider_entry_dict
  file: src/sevn/config/sections/providers.py
  symbol: provider_entry_dict
- name: providers_section_dict
  file: src/sevn/config/sections/providers.py
  symbol: providers_section_dict
- name: resolve_auth_mode
  file: src/sevn/config/sections/providers.py
  symbol: resolve_auth_mode
- name: resolve_consumption_type
  file: src/sevn/config/sections/providers.py
  symbol: resolve_consumption_type
- name: ProvisioningWorkspaceConfig
  file: src/sevn/config/sections/provisioning.py
  symbol: ProvisioningWorkspaceConfig
- name: WorkspaceConfig
  file: src/sevn/config/sections/root.py
  symbol: WorkspaceConfig
- name: EncryptedFileBackendEntry
  file: src/sevn/config/sections/secrets.py
  symbol: EncryptedFileBackendEntry
- name: EncryptedFileSubtreeDefaults
  file: src/sevn/config/sections/secrets.py
  symbol: EncryptedFileSubtreeDefaults
- name: LinuxSecretServiceBackendEntry
  file: src/sevn/config/sections/secrets.py
  symbol: LinuxSecretServiceBackendEntry
- name: MacOSKeychainBackendEntry
  file: src/sevn/config/sections/secrets.py
  symbol: MacOSKeychainBackendEntry
- name: OpenBaoBackendEntry
  file: src/sevn/config/sections/secrets.py
  symbol: OpenBaoBackendEntry
- name: ProtonPassBackendEntry
  file: src/sevn/config/sections/secrets.py
  symbol: ProtonPassBackendEntry
- name: SecretsBackendSectionConfig
  file: src/sevn/config/sections/secrets.py
  symbol: SecretsBackendSectionConfig
- name: effective_encrypted_file_key_source
  file: src/sevn/config/sections/secrets.py
  symbol: effective_encrypted_file_key_source
- name: DeploymentConfig
  file: src/sevn/config/sections/security.py
  symbol: DeploymentConfig
- name: SandboxConfig
  file: src/sevn/config/sections/security.py
  symbol: SandboxConfig
- name: SecurityAuditSubConfig
  file: src/sevn/config/sections/security.py
  symbol: SecurityAuditSubConfig
- name: SecurityLlmignoreRetentionSubConfig
  file: src/sevn/config/sections/security.py
  symbol: SecurityLlmignoreRetentionSubConfig
- name: SecurityLlmignoreSubConfig
  file: src/sevn/config/sections/security.py
  symbol: SecurityLlmignoreSubConfig
- name: SecurityReplSubConfig
  file: src/sevn/config/sections/security.py
  symbol: SecurityReplSubConfig
- name: SecuritySandboxSubConfig
  file: src/sevn/config/sections/security.py
  symbol: SecuritySandboxSubConfig
- name: SecurityScannerSubConfig
  file: src/sevn/config/sections/security.py
  symbol: SecurityScannerSubConfig
- name: SecurityWorkspaceConfig
  file: src/sevn/config/sections/security.py
  symbol: SecurityWorkspaceConfig
- name: SelfImproveEvalWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveEvalWorkspaceConfig
- name: SelfImproveExportWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveExportWorkspaceConfig
- name: SelfImproveHubWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveHubWorkspaceConfig
- name: SelfImproveJobsWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveJobsWorkspaceConfig
- name: SelfImproveSamplerCoverageWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveSamplerCoverageWorkspaceConfig
- name: SelfImproveSamplerWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveSamplerWorkspaceConfig
- name: SelfImproveSpecKitConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveSpecKitConfig
- name: SelfImproveTrajectoriesWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveTrajectoriesWorkspaceConfig
- name: SelfImproveWorkspaceConfig
  file: src/sevn/config/sections/self_improve.py
  symbol: SelfImproveWorkspaceConfig
- name: SpecialistConfig
  file: src/sevn/config/sections/subagents.py
  symbol: SpecialistConfig
- name: SubAgentRoleLimits
  file: src/sevn/config/sections/subagents.py
  symbol: SubAgentRoleLimits
- name: SubAgentsWorkspaceConfig
  file: src/sevn/config/sections/subagents.py
  symbol: SubAgentsWorkspaceConfig
- name: resolve_limits
  file: src/sevn/config/sections/subagents.py
  symbol: resolve_limits
- name: TraceRedactionConfig
  file: src/sevn/config/sections/tracing.py
  symbol: TraceRedactionConfig
- name: TraceSinkEntry
  file: src/sevn/config/sections/tracing.py
  symbol: TraceSinkEntry
- name: TracingConfig
  file: src/sevn/config/sections/tracing.py
  symbol: TracingConfig
- name: TriagerTimeoutConfig
  file: src/sevn/config/sections/triager.py
  symbol: TriagerTimeoutConfig
- name: TriagerWorkspaceConfig
  file: src/sevn/config/sections/triager.py
  symbol: TriagerWorkspaceConfig
- name: ProcessSettings
  file: src/sevn/config/settings.py
  symbol: ProcessSettings
- name: is_sevn_repo
  file: src/sevn/config/sevn_repo.py
  symbol: is_sevn_repo
- name: resolve_mycode_default_root
  file: src/sevn/config/sevn_repo.py
  symbol: resolve_mycode_default_root
- name: resolve_sevn_checkout_for_workspace
  file: src/sevn/config/sevn_repo.py
  symbol: resolve_sevn_checkout_for_workspace
- name: resolve_sevn_checkout_with_origin
  file: src/sevn/config/sevn_repo.py
  symbol: resolve_sevn_checkout_with_origin
- name: sevn_gateway_read_paths
  file: src/sevn/config/sevn_repo.py
  symbol: sevn_gateway_read_paths
- name: sevn_package_glob_prefix
  file: src/sevn/config/sevn_repo.py
  symbol: sevn_package_glob_prefix
- name: try_resolve_sevn_repo_root
  file: src/sevn/config/sevn_repo.py
  symbol: try_resolve_sevn_repo_root
- name: parse_workspace_config
  file: src/sevn/config/workspace_config.py
  symbol: parse_workspace_config
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Purpose.

## Public Interface

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Public Interface.

## Data Model

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Data Model.

## Internal Architecture

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Internal Architecture.

## Behavior

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Behavior.

## Failure Modes

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Failure Modes.

## Test Strategy

Offline scaffold for Schema & ontology — Spec (spec-10-schema-ontology) — Test Strategy.
