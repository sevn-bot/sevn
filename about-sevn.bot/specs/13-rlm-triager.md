---
id: spec-13-rlm-triager
kind: spec
title: RLM Triager — Spec
status: done
owner: Alex
summary: 'The Triager is the routing brain (prd-04-getting-things-done §5.1–§5.2):
  a single, tool-less outbound generation step that emits validated TriageResult consumed
  by tier dispatch (A / B / C / D), MCP e'
last_updated: '2026-07-19'
fingerprint: sha256:9c955d2d530ded15bd0893520e391245945b9224f58e5a50cb7e80a8458dc5c0
related: []
sources:
- src/sevn/agent/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-05-llm-transports
build_phase: null
interfaces:
- name: default_codemode_limits
  file: src/sevn/agent/adapters/_monty_limits.py
  symbol: default_codemode_limits
- name: install_monty_resource_limits
  file: src/sevn/agent/adapters/_monty_limits.py
  symbol: install_monty_resource_limits
- name: lambda_rlm_filter
  file: src/sevn/agent/adapters/dspy_adapter.py
  symbol: lambda_rlm_filter
- name: to_dspy_tools
  file: src/sevn/agent/adapters/dspy_adapter.py
  symbol: to_dspy_tools
- name: EgressBridgeContext
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: EgressBridgeContext
- name: build_sevn_anthropic_client
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: build_sevn_anthropic_client
- name: build_sevn_httpx_event_hooks
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: build_sevn_httpx_event_hooks
- name: build_sevn_openai_client
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: build_sevn_openai_client
- name: redact_httpx_request_snapshot
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: redact_httpx_request_snapshot
- name: redact_llm_request_snapshot
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: redact_llm_request_snapshot
- name: redact_proxy_transport_request
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: redact_proxy_transport_request
- name: resolve_proxy_shared_secret
  file: src/sevn/agent/adapters/egress_bridge.py
  symbol: resolve_proxy_shared_secret
- name: MiniMaxHygieneContext
  file: src/sevn/agent/adapters/minimax_wrapper_model.py
  symbol: MiniMaxHygieneContext
- name: MiniMaxOpenAIWrapperModel
  file: src/sevn/agent/adapters/minimax_wrapper_model.py
  symbol: MiniMaxOpenAIWrapperModel
- name: MiniMaxWrapperModel
  file: src/sevn/agent/adapters/minimax_wrapper_model.py
  symbol: MiniMaxWrapperModel
- name: wrap_minimax_native_model
  file: src/sevn/agent/adapters/minimax_wrapper_model.py
  symbol: wrap_minimax_native_model
- name: wrap_minimax_openai_native_model
  file: src/sevn/agent/adapters/minimax_wrapper_model.py
  symbol: wrap_minimax_openai_native_model
- name: NativeModelContext
  file: src/sevn/agent/adapters/native_model.py
  symbol: NativeModelContext
- name: build_native_model_settings
  file: src/sevn/agent/adapters/native_model.py
  symbol: build_native_model_settings
- name: default_native_model_context
  file: src/sevn/agent/adapters/native_model.py
  symbol: default_native_model_context
- name: resolve_pydantic_model
  file: src/sevn/agent/adapters/native_model.py
  symbol: resolve_pydantic_model
- name: resolve_pydantic_model_for_slot
  file: src/sevn/agent/adapters/native_model.py
  symbol: resolve_pydantic_model_for_slot
- name: PydanticToolRegistration
  file: src/sevn/agent/adapters/pydantic_adapter.py
  symbol: PydanticToolRegistration
- name: register_pydantic_tools
  file: src/sevn/agent/adapters/pydantic_adapter.py
  symbol: register_pydantic_tools
- name: WebEgressDomainPolicy
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: WebEgressDomainPolicy
- name: build_get_page_content_local_tool
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: build_get_page_content_local_tool
- name: build_serp_local_tool
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: build_serp_local_tool
- name: build_web_thinking_extra_capabilities
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: build_web_thinking_extra_capabilities
- name: make_codemode_web_registry_tool
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: make_codemode_web_registry_tool
- name: provider_supports_native_web_fetch
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: provider_supports_native_web_fetch
- name: provider_supports_native_web_search
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: provider_supports_native_web_search
- name: registry_tool_names_owned_by_web_capabilities
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: registry_tool_names_owned_by_web_capabilities
- name: resolve_thinking_effort
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: resolve_thinking_effort
- name: resolve_web_egress_domain_policy
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: resolve_web_egress_domain_policy
- name: url_passes_domain_policy
  file: src/sevn/agent/adapters/tier_b_capabilities.py
  symbol: url_passes_domain_policy
- name: build_codemode_capability
  file: src/sevn/agent/adapters/tier_b_codemode.py
  symbol: build_codemode_capability
- name: compute_codemode_eligible_names
  file: src/sevn/agent/adapters/tier_b_codemode.py
  symbol: compute_codemode_eligible_names
- name: is_codemode_eligible_tool
  file: src/sevn/agent/adapters/tier_b_codemode.py
  symbol: is_codemode_eligible_tool
- name: TierBHookConfig
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: TierBHookConfig
- name: apply_load_tool_grant
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: apply_load_tool_grant
- name: await_human_tool_approval
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: await_human_tool_approval
- name: build_tier_b_hooks
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: build_tier_b_hooks
- name: check_permission_before_dispatch
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: check_permission_before_dispatch
- name: enforce_round_budget
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: enforce_round_budget
- name: fetch_round_cap_after_model
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: fetch_round_cap_after_model
- name: grounding_guard_after_model
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: grounding_guard_after_model
- name: inject_owner_steer
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: inject_owner_steer
- name: permission_before_tool_execute
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: permission_before_tool_execute
- name: provision_denial_envelope
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: provision_denial_envelope
- name: resolve_deferred_approvals
  file: src/sevn/agent/adapters/tier_b_hooks.py
  symbol: resolve_deferred_approvals
- name: TriagerBoundToolChoiceContext
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: TriagerBoundToolChoiceContext
- name: anthropic_completion_to_model_response
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: anthropic_completion_to_model_response
- name: append_owner_steer_model_request
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: append_owner_steer_model_request
- name: apply_minimax_anthropic_request_hygiene
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: apply_minimax_anthropic_request_hygiene
- name: bedrock_converse_to_model_response
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: bedrock_converse_to_model_response
- name: build_llm_request_metadata
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: build_llm_request_metadata
- name: build_tier_b_function_model
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: build_tier_b_function_model
- name: coalesce_adjacent_anthropic_messages
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: coalesce_adjacent_anthropic_messages
- name: coalesce_adjacent_openai_messages
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: coalesce_adjacent_openai_messages
- name: finalize_openai_chat_messages
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: finalize_openai_chat_messages
- name: is_anthropic_empty_end_turn
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: is_anthropic_empty_end_turn
- name: merge_adjacent_anthropic_text_blocks
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: merge_adjacent_anthropic_text_blocks
- name: normalize_codemode_run_code_payloads
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: normalize_codemode_run_code_payloads
- name: openai_completion_to_model_response
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: openai_completion_to_model_response
- name: prepare_anthropic_messages_for_transport
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: prepare_anthropic_messages_for_transport
- name: pydantic_messages_to_anthropic_messages
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: pydantic_messages_to_anthropic_messages
- name: pydantic_messages_to_bedrock_converse
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: pydantic_messages_to_bedrock_converse
- name: pydantic_messages_to_openai_chat
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: pydantic_messages_to_openai_chat
- name: repair_anthropic_tool_pairing
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: repair_anthropic_tool_pairing
- name: repair_openai_tool_pairing
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: repair_openai_tool_pairing
- name: replay_stubs_are_same_turn_only
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: replay_stubs_are_same_turn_only
- name: rewrite_codemode_native_tool_calls
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: rewrite_codemode_native_tool_calls
- name: sanitize_anthropic_messages
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: sanitize_anthropic_messages
- name: strip_orphan_tool_result_blocks
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: strip_orphan_tool_result_blocks
- name: strip_orphan_tool_use_blocks
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: strip_orphan_tool_use_blocks
- name: tier_b_system_prompt_text
  file: src/sevn/agent/adapters/tier_b_model.py
  symbol: tier_b_system_prompt_text
- name: TierBModalitySupport
  file: src/sevn/agent/adapters/tier_b_multimodal.py
  symbol: TierBModalitySupport
- name: build_tier_b_user_prompt
  file: src/sevn/agent/adapters/tier_b_multimodal.py
  symbol: build_tier_b_user_prompt
- name: resolve_tier_b_modality_support
  file: src/sevn/agent/adapters/tier_b_multimodal.py
  symbol: resolve_tier_b_modality_support
- name: resolve_turn_media_items
  file: src/sevn/agent/adapters/tier_b_multimodal.py
  symbol: resolve_turn_media_items
- name: OverflowingToolOutput
  file: src/sevn/agent/adapters/tier_b_overflow.py
  symbol: OverflowingToolOutput
- name: build_overflow_capability
  file: src/sevn/agent/adapters/tier_b_overflow.py
  symbol: build_overflow_capability
- name: SkillCapabilitySource
  file: src/sevn/agent/adapters/tier_b_skill_capabilities.py
  symbol: SkillCapabilitySource
- name: build_tier_b_skill_capabilities
  file: src/sevn/agent/adapters/tier_b_skill_capabilities.py
  symbol: build_tier_b_skill_capabilities
- name: resolve_skill_capability_sources
  file: src/sevn/agent/adapters/tier_b_skill_capabilities.py
  symbol: resolve_skill_capability_sources
- name: sevn_run_skill_script
  file: src/sevn/agent/adapters/tier_b_skill_capabilities.py
  symbol: sevn_run_skill_script
- name: skill_capability
  file: src/sevn/agent/adapters/tier_b_skill_capabilities.py
  symbol: skill_capability
- name: bound_file_search_tools
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: bound_file_search_tools
- name: build_pydantic_tools_for_registry
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: build_pydantic_tools_for_registry
- name: build_pydantic_tools_for_triage
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: build_pydantic_tools_for_triage
- name: eager_hydrate_tool_names
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: eager_hydrate_tool_names
- name: meta_tool_name_frozenset
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: meta_tool_name_frozenset
- name: minimal_stub_json_schema
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: minimal_stub_json_schema
- name: prepare_lazy_tool_definitions
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: prepare_lazy_tool_definitions
- name: should_block_shell_improvisation
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: should_block_shell_improvisation
- name: tool_definition_to_args_model
  file: src/sevn/agent/adapters/tier_b_tools.py
  symbol: tool_definition_to_args_model
- name: SevnRegistryToolset
  file: src/sevn/agent/adapters/tier_b_toolset.py
  symbol: SevnRegistryToolset
- name: bound_tools_only_first_round
  file: src/sevn/agent/adapters/tier_b_toolset.py
  symbol: bound_tools_only_first_round
- name: PendingToolApproval
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: PendingToolApproval
- name: ToolApprovalBridge
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: ToolApprovalBridge
- name: ack_tool_on_deps
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: ack_tool_on_deps
- name: get_tool_approval_bridge
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: get_tool_approval_bridge
- name: install_tool_approval_bridge
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: install_tool_approval_bridge
- name: reset_tool_approval_bridge_for_tests
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: reset_tool_approval_bridge_for_tests
- name: summarize_tool_args
  file: src/sevn/agent/adapters/tool_approval_bridge.py
  symbol: summarize_tool_args
- name: MutableToolAllowlist
  file: src/sevn/agent/adapters/tool_part_filter.py
  symbol: MutableToolAllowlist
- name: filter_tool_call_parts
  file: src/sevn/agent/adapters/tool_part_filter.py
  symbol: filter_tool_call_parts
- name: compose_list_skills_reply
  file: src/sevn/agent/capability_reply.py
  symbol: compose_list_skills_reply
- name: compose_list_tools_reply
  file: src/sevn/agent/capability_reply.py
  symbol: compose_list_tools_reply
- name: is_list_skills_message
  file: src/sevn/agent/capability_reply.py
  symbol: is_list_skills_message
- name: is_list_tools_message
  file: src/sevn/agent/capability_reply.py
  symbol: is_list_tools_message
- name: build_agent_context_manifest
  file: src/sevn/agent/context_manifest.py
  symbol: build_agent_context_manifest
- name: collect_manifest_slot_ids
  file: src/sevn/agent/context_manifest.py
  symbol: collect_manifest_slot_ids
- name: tier_b_intro_system_prompt_builders
  file: src/sevn/agent/context_manifest.py
  symbol: tier_b_intro_system_prompt_builders
- name: tier_b_system_prompt_builders
  file: src/sevn/agent/context_manifest.py
  symbol: tier_b_system_prompt_builders
- name: expand_context_refs
  file: src/sevn/agent/context_refs.py
  symbol: expand_context_refs
- name: DiagnosticPlan
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: DiagnosticPlan
- name: DiagnosticStep
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: DiagnosticStep
- name: DiagnosticsDeps
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: DiagnosticsDeps
- name: is_apply_sevn_command
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: is_apply_sevn_command
- name: is_readonly_sevn_command
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: is_readonly_sevn_command
- name: load_sevn_diagnostics_skill_body
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: load_sevn_diagnostics_skill_body
- name: run_diagnostics_agent
  file: src/sevn/agent/diagnostics/runtime.py
  symbol: run_diagnostics_agent
- name: build_tier_b_capabilities
  file: src/sevn/agent/executors/b_harness.py
  symbol: build_tier_b_capabilities
- name: run_b_turn
  file: src/sevn/agent/executors/b_harness.py
  symbol: run_b_turn
- name: BTierDeps
  file: src/sevn/agent/executors/b_types.py
  symbol: BTierDeps
- name: BTurnOutcome
  file: src/sevn/agent/executors/b_types.py
  symbol: BTurnOutcome
- name: ChannelPayload
  file: src/sevn/agent/executors/b_types.py
  symbol: ChannelPayload
- name: EscalationRequest
  file: src/sevn/agent/executors/b_types.py
  symbol: EscalationRequest
- name: ResolvedTierBModel
  file: src/sevn/agent/executors/b_types.py
  symbol: ResolvedTierBModel
- name: SessionHandle
  file: src/sevn/agent/executors/b_types.py
  symbol: SessionHandle
- name: SteerInject
  file: src/sevn/agent/executors/b_types.py
  symbol: SteerInject
- name: ImmediateApprovedPlanGate
  file: src/sevn/agent/executors/cd_harness.py
  symbol: ImmediateApprovedPlanGate
- name: NoOpPlanGate
  file: src/sevn/agent/executors/cd_harness.py
  symbol: NoOpPlanGate
- name: SupersedingPlanGate
  file: src/sevn/agent/executors/cd_harness.py
  symbol: SupersedingPlanGate
- name: run_cd_turn
  file: src/sevn/agent/executors/cd_harness.py
  symbol: run_cd_turn
- name: CdDspyPipelinePort
  file: src/sevn/agent/executors/cd_types.py
  symbol: CdDspyPipelinePort
- name: CdTurnOutcome
  file: src/sevn/agent/executors/cd_types.py
  symbol: CdTurnOutcome
- name: Plan
  file: src/sevn/agent/executors/cd_types.py
  symbol: Plan
- name: PlanGatePort
  file: src/sevn/agent/executors/cd_types.py
  symbol: PlanGatePort
- name: PlanStep
  file: src/sevn/agent/executors/cd_types.py
  symbol: PlanStep
- name: ResolvedCdOuterModels
  file: src/sevn/agent/executors/cd_types.py
  symbol: ResolvedCdOuterModels
- name: run_lambda_rlm_turn
  file: src/sevn/agent/executors/lambda_rlm_runtime.py
  symbol: run_lambda_rlm_turn
- name: LoadedPendingPlan
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: LoadedPendingPlan
- name: PendingPlanRecord
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: PendingPlanRecord
- name: expire_pending_plans
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: expire_pending_plans
- name: load_awaiting_pending_plan
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: load_awaiting_pending_plan
- name: load_pending_plan_by_id
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: load_pending_plan_by_id
- name: store_pending_plan
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: store_pending_plan
- name: supersede_awaiting_for_session
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: supersede_awaiting_for_session
- name: supersede_pending_plan
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: supersede_pending_plan
- name: update_pending_plan_status
  file: src/sevn/agent/executors/plan_gate_store.py
  symbol: update_pending_plan_status
- name: append_output_truncation_notice
  file: src/sevn/agent/grounding.py
  symbol: append_output_truncation_notice
- name: apply_audit_evidence_guard
  file: src/sevn/agent/grounding.py
  symbol: apply_audit_evidence_guard
- name: apply_file_delivery_grounding_guard
  file: src/sevn/agent/grounding.py
  symbol: apply_file_delivery_grounding_guard
- name: apply_live_factual_grounding_guard
  file: src/sevn/agent/grounding.py
  symbol: apply_live_factual_grounding_guard
- name: apply_zero_tool_grounding_guard
  file: src/sevn/agent/grounding.py
  symbol: apply_zero_tool_grounding_guard
- name: asserts_false_fabrication
  file: src/sevn/agent/grounding.py
  symbol: asserts_false_fabrication
- name: asserts_ungrounded_claims
  file: src/sevn/agent/grounding.py
  symbol: asserts_ungrounded_claims
- name: claims_bound_tool_unavailable
  file: src/sevn/agent/grounding.py
  symbol: claims_bound_tool_unavailable
- name: claims_file_delivery_success
  file: src/sevn/agent/grounding.py
  symbol: claims_file_delivery_success
- name: claims_list_dir_embellishment
  file: src/sevn/agent/grounding.py
  symbol: claims_list_dir_embellishment
- name: claims_live_factual_content
  file: src/sevn/agent/grounding.py
  symbol: claims_live_factual_content
- name: claims_success_after_tool_failure
  file: src/sevn/agent/grounding.py
  symbol: claims_success_after_tool_failure
- name: claims_unattempted_tool_failure
  file: src/sevn/agent/grounding.py
  symbol: claims_unattempted_tool_failure
- name: is_routing_footer_query
  file: src/sevn/agent/grounding.py
  symbol: is_routing_footer_query
- name: is_self_architecture_query
  file: src/sevn/agent/grounding.py
  symbol: is_self_architecture_query
- name: last_model_stop_reason
  file: src/sevn/agent/grounding.py
  symbol: last_model_stop_reason
- name: steer_for_audit_evidence
  file: src/sevn/agent/grounding.py
  symbol: steer_for_audit_evidence
- name: steer_for_browser_cdp_probe_failure
  file: src/sevn/agent/grounding.py
  symbol: steer_for_browser_cdp_probe_failure
- name: steer_for_codemode_loaded_tool
  file: src/sevn/agent/grounding.py
  symbol: steer_for_codemode_loaded_tool
- name: steer_for_direct_tool_call
  file: src/sevn/agent/grounding.py
  symbol: steer_for_direct_tool_call
- name: steer_for_dropped_tool_call
  file: src/sevn/agent/grounding.py
  symbol: steer_for_dropped_tool_call
- name: steer_for_fallback_tool
  file: src/sevn/agent/grounding.py
  symbol: steer_for_fallback_tool
- name: steer_for_false_tool_failure_claim
  file: src/sevn/agent/grounding.py
  symbol: steer_for_false_tool_failure_claim
- name: steer_for_meta_tool_call
  file: src/sevn/agent/grounding.py
  symbol: steer_for_meta_tool_call
- name: steer_for_opener_only
  file: src/sevn/agent/grounding.py
  symbol: steer_for_opener_only
- name: steer_for_promised_action
  file: src/sevn/agent/grounding.py
  symbol: steer_for_promised_action
- name: steer_for_summarize_after_fetch
  file: src/sevn/agent/grounding.py
  symbol: steer_for_summarize_after_fetch
- name: steer_for_triager_bound_tools_unused
  file: src/sevn/agent/grounding.py
  symbol: steer_for_triager_bound_tools_unused
- name: tier_b_routing_footer_inject
  file: src/sevn/agent/grounding.py
  symbol: tier_b_routing_footer_inject
- name: tier_b_self_architecture_inject
  file: src/sevn/agent/grounding.py
  symbol: tier_b_self_architecture_inject
- name: tools_attempted_from_call_counts
  file: src/sevn/agent/grounding.py
  symbol: tools_attempted_from_call_counts
- name: triager_bound_tools_satisfied
  file: src/sevn/agent/grounding.py
  symbol: triager_bound_tools_satisfied
- name: ActiveRunSnapshotWrite
  file: src/sevn/agent/harness/snapshots.py
  symbol: ActiveRunSnapshotWrite
- name: BootResumeRunRef
  file: src/sevn/agent/harness/snapshots.py
  symbol: BootResumeRunRef
- name: HarnessBootSweepResult
  file: src/sevn/agent/harness/snapshots.py
  symbol: HarnessBootSweepResult
- name: HarnessSnapshotSanitisationError
  file: src/sevn/agent/harness/snapshots.py
  symbol: HarnessSnapshotSanitisationError
- name: ReplayTurnNotFoundError
  file: src/sevn/agent/harness/snapshots.py
  symbol: ReplayTurnNotFoundError
- name: ReplayTurnNotReplayableError
  file: src/sevn/agent/harness/snapshots.py
  symbol: ReplayTurnNotReplayableError
- name: delete_active_run_snapshot
  file: src/sevn/agent/harness/snapshots.py
  symbol: delete_active_run_snapshot
- name: format_upgrade_paused_notification
  file: src/sevn/agent/harness/snapshots.py
  symbol: format_upgrade_paused_notification
- name: get_or_create_turn_replay_job_id
  file: src/sevn/agent/harness/snapshots.py
  symbol: get_or_create_turn_replay_job_id
- name: pause_active_snapshots_for_upgrade
  file: src/sevn/agent/harness/snapshots.py
  symbol: pause_active_snapshots_for_upgrade
- name: pending_resume_group_count
  file: src/sevn/agent/harness/snapshots.py
  symbol: pending_resume_group_count
- name: persist_run_snapshot
  file: src/sevn/agent/harness/snapshots.py
  symbol: persist_run_snapshot
- name: queue_dashboard_turn_replay
  file: src/sevn/agent/harness/snapshots.py
  symbol: queue_dashboard_turn_replay
- name: redacted_inspect_summary
  file: src/sevn/agent/harness/snapshots.py
  symbol: redacted_inspect_summary
- name: replay_requests_in_window
  file: src/sevn/agent/harness/snapshots.py
  symbol: replay_requests_in_window
- name: sanitize_in_flight_tools
  file: src/sevn/agent/harness/snapshots.py
  symbol: sanitize_in_flight_tools
- name: sanitize_plan_state
  file: src/sevn/agent/harness/snapshots.py
  symbol: sanitize_plan_state
- name: session_has_active_run_for_replay
  file: src/sevn/agent/harness/snapshots.py
  symbol: session_has_active_run_for_replay
- name: sweep_active_run_snapshots
  file: src/sevn/agent/harness/snapshots.py
  symbol: sweep_active_run_snapshots
- name: turn_has_replay_trace
  file: src/sevn/agent/harness/snapshots.py
  symbol: turn_has_replay_trace
- name: ZombieTask
  file: src/sevn/agent/harness/zombie.py
  symbol: ZombieTask
- name: ZombieWatchQueue
  file: src/sevn/agent/harness/zombie.py
  symbol: ZombieWatchQueue
- name: compose_identity_reply
  file: src/sevn/agent/identity_reply.py
  symbol: compose_identity_reply
- name: identity_bootstrap_incomplete_fields
  file: src/sevn/agent/identity_reply.py
  symbol: identity_bootstrap_incomplete_fields
- name: is_pure_identity_message
  file: src/sevn/agent/identity_reply.py
  symbol: is_pure_identity_message
- name: resolve_workspace_identity
  file: src/sevn/agent/identity_reply.py
  symbol: resolve_workspace_identity
- name: is_bare_opener
  file: src/sevn/agent/openers.py
  symbol: is_bare_opener
- name: normalize_opener
  file: src/sevn/agent/openers.py
  symbol: normalize_opener
- name: strip_opener_echo
  file: src/sevn/agent/openers.py
  symbol: strip_opener_echo
- name: build_tier_b_intro_prompt_parts
  file: src/sevn/agent/persona.py
  symbol: build_tier_b_intro_prompt_parts
- name: load_persona_block
  file: src/sevn/agent/persona.py
  symbol: load_persona_block
- name: load_persona_block_intro
  file: src/sevn/agent/persona.py
  symbol: load_persona_block_intro
- name: tier_b_repo_access_prompt
  file: src/sevn/agent/persona.py
  symbol: tier_b_repo_access_prompt
- name: tier_b_workspace_roots_prompt
  file: src/sevn/agent/persona.py
  symbol: tier_b_workspace_roots_prompt
- name: BudgetRegime
  file: src/sevn/agent/providers/budget.py
  symbol: BudgetRegime
- name: ModelBudget
  file: src/sevn/agent/providers/budget.py
  symbol: ModelBudget
- name: resolve_model
  file: src/sevn/agent/providers/resolve.py
  symbol: resolve_model
- name: AnthropicMessagesTransport
  file: src/sevn/agent/providers/transport.py
  symbol: AnthropicMessagesTransport
- name: AnthropicTransport
  file: src/sevn/agent/providers/transport.py
  symbol: AnthropicTransport
- name: BedrockTransport
  file: src/sevn/agent/providers/transport.py
  symbol: BedrockTransport
- name: ChatCompletionsTransport
  file: src/sevn/agent/providers/transport.py
  symbol: ChatCompletionsTransport
- name: ResponsesApiTransport
  file: src/sevn/agent/providers/transport.py
  symbol: ResponsesApiTransport
- name: StreamFinal
  file: src/sevn/agent/providers/transport.py
  symbol: StreamFinal
- name: StreamTextDelta
  file: src/sevn/agent/providers/transport.py
  symbol: StreamTextDelta
- name: Transport
  file: src/sevn/agent/providers/transport.py
  symbol: Transport
- name: TransportBadRequest
  file: src/sevn/agent/providers/transport_http.py
  symbol: TransportBadRequest
- name: iter_llm_sse
  file: src/sevn/agent/providers/transport_http.py
  symbol: iter_llm_sse
- name: post_llm_json
  file: src/sevn/agent/providers/transport_http.py
  symbol: post_llm_json
- name: adapt_request_for_transport
  file: src/sevn/agent/providers/wire.py
  symbol: adapt_request_for_transport
- name: PyodideDenoRunner
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: PyodideDenoRunner
- name: PyodideDenoUnavailable
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: PyodideDenoUnavailable
- name: PyodideExecResult
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: PyodideExecResult
- name: deno_binary_on_path
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: deno_binary_on_path
- name: effective_sandbox_exec_driver
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: effective_sandbox_exec_driver
- name: pyodide_runner_script_path
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: pyodide_runner_script_path
- name: reconcile_sandbox_mode_document
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: reconcile_sandbox_mode_document
- name: resolve_sandbox_exec_driver
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: resolve_sandbox_exec_driver
- name: sandbox_driver_runtime_available
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: sandbox_driver_runtime_available
- name: sandbox_exec_unavailable_note
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: sandbox_exec_unavailable_note
- name: should_wire_pyodide_sandbox
  file: src/sevn/agent/runtimes/pyodide_deno.py
  symbol: should_wire_pyodide_sandbox
- name: PyodideDenoInterpreter
  file: src/sevn/agent/runtimes/sandbox.py
  symbol: PyodideDenoInterpreter
- name: SevnDockerInterpreter
  file: src/sevn/agent/runtimes/sandbox.py
  symbol: SevnDockerInterpreter
- name: build_rlm_interpreter
  file: src/sevn/agent/runtimes/sandbox.py
  symbol: build_rlm_interpreter
- name: SevnSandboxExecutorClient
  file: src/sevn/agent/runtimes/sandbox_client.py
  symbol: SevnSandboxExecutorClient
- name: build_sandbox_executor_client
  file: src/sevn/agent/runtimes/sandbox_client.py
  symbol: build_sandbox_executor_client
- name: MiniMaxMediaError
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: MiniMaxMediaError
- name: clone_voice_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: clone_voice_bytes
- name: generate_image_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_image_bytes
- name: generate_image_from_reference_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_image_from_reference_bytes
- name: generate_music_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_music_bytes
- name: generate_video_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_bytes
- name: generate_video_first_last_frame_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_first_last_frame_bytes
- name: generate_video_from_image_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_from_image_bytes
- name: generate_video_subject_reference_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_subject_reference_bytes
- name: generate_video_template_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_template_bytes
- name: synthesize_speech_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: synthesize_speech_bytes
- name: upload_file_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: upload_file_bytes
- name: MediaPromptVars
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: MediaPromptVars
- name: PromptTemplateMeta
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: PromptTemplateMeta
- name: VideoAgentTemplate
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: VideoAgentTemplate
- name: augment_prompt
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: augment_prompt
- name: build_media_trace
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: build_media_trace
- name: list_prompt_templates
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: list_prompt_templates
- name: list_video_agent_templates
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: list_video_agent_templates
- name: resolve_video_agent_template
  file: src/sevn/agent/subagents/media_prompts.py
  symbol: resolve_video_agent_template
- name: MediaTask
  file: src/sevn/agent/subagents/media_worker.py
  symbol: MediaTask
- name: execute_media_generator_for_context
  file: src/sevn/agent/subagents/media_worker.py
  symbol: execute_media_generator_for_context
- name: execute_media_generator_task
  file: src/sevn/agent/subagents/media_worker.py
  symbol: execute_media_generator_task
- name: parse_media_task
  file: src/sevn/agent/subagents/media_worker.py
  symbol: parse_media_task
- name: require_media_generator
  file: src/sevn/agent/subagents/media_worker.py
  symbol: require_media_generator
- name: resolve_minimax_api_key
  file: src/sevn/agent/subagents/media_worker.py
  symbol: resolve_minimax_api_key
- name: SubAgentLimitExceeded
  file: src/sevn/agent/subagents/models.py
  symbol: SubAgentLimitExceeded
- name: SubAgentRun
  file: src/sevn/agent/subagents/models.py
  symbol: SubAgentRun
- name: SubAgentStatus
  file: src/sevn/agent/subagents/models.py
  symbol: SubAgentStatus
- name: generate_short_id
  file: src/sevn/agent/subagents/models.py
  symbol: generate_short_id
- name: RegistrySnapshot
  file: src/sevn/agent/subagents/registry.py
  symbol: RegistrySnapshot
- name: SubAgentRegistry
  file: src/sevn/agent/subagents/registry.py
  symbol: SubAgentRegistry
- name: SocialMediaManagerError
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: SocialMediaManagerError
- name: SocialMediaTask
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: SocialMediaTask
- name: assigned_skills_for
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: assigned_skills_for
- name: assigned_tools_for
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: assigned_tools_for
- name: execute_social_media_manager_for_context
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: execute_social_media_manager_for_context
- name: execute_social_media_manager_task
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: execute_social_media_manager_task
- name: parse_social_media_task
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: parse_social_media_task
- name: require_social_media_manager
  file: src/sevn/agent/subagents/social_media_worker.py
  symbol: require_social_media_manager
- name: ResolvedSpecialist
  file: src/sevn/agent/subagents/specialists.py
  symbol: ResolvedSpecialist
- name: merge_specialist_grants
  file: src/sevn/agent/subagents/specialists.py
  symbol: merge_specialist_grants
- name: resolve_specialist
  file: src/sevn/agent/subagents/specialists.py
  symbol: resolve_specialist
- name: resolve_specialist_executor
  file: src/sevn/agent/subagents/specialists.py
  symbol: resolve_specialist_executor
- name: resolve_specialist_transport
  file: src/sevn/agent/subagents/specialists.py
  symbol: resolve_specialist_transport
- name: specialist_spawn_allowed
  file: src/sevn/agent/subagents/specialists.py
  symbol: specialist_spawn_allowed
- name: list_recent_subagent_runs
  file: src/sevn/agent/subagents/storage.py
  symbol: list_recent_subagent_runs
- name: persist_subagent_run
  file: src/sevn/agent/subagents/storage.py
  symbol: persist_subagent_run
- name: prune_subagent_runs
  file: src/sevn/agent/subagents/storage.py
  symbol: prune_subagent_runs
- name: sqlite_persist_hook
  file: src/sevn/agent/subagents/storage.py
  symbol: sqlite_persist_hook
- name: sweep_orphaned_subagent_runs
  file: src/sevn/agent/subagents/storage.py
  symbol: sweep_orphaned_subagent_runs
- name: SubAgentHandle
  file: src/sevn/agent/subagents/supervisor.py
  symbol: SubAgentHandle
- name: SubAgentSpec
  file: src/sevn/agent/subagents/supervisor.py
  symbol: SubAgentSpec
- name: SubAgentSupervisor
  file: src/sevn/agent/subagents/supervisor.py
  symbol: SubAgentSupervisor
- name: TemplateEntry
  file: src/sevn/agent/templates/registry.py
  symbol: TemplateEntry
- name: load_template_registry
  file: src/sevn/agent/templates/registry.py
  symbol: load_template_registry
- name: registry_version
  file: src/sevn/agent/templates/registry.py
  symbol: registry_version
- name: build_tier_b_context_attrs
  file: src/sevn/agent/tracing/agent_context.py
  symbol: build_tier_b_context_attrs
- name: build_triager_context_attrs
  file: src/sevn/agent/tracing/agent_context.py
  symbol: build_triager_context_attrs
- name: emit_context_span
  file: src/sevn/agent/tracing/agent_context.py
  symbol: emit_context_span
- name: serialize_message_history_for_trace
  file: src/sevn/agent/tracing/agent_context.py
  symbol: serialize_message_history_for_trace
- name: serialize_user_prompt_for_trace
  file: src/sevn/agent/tracing/agent_context.py
  symbol: serialize_user_prompt_for_trace
- name: trace_text_field
  file: src/sevn/agent/tracing/agent_context.py
  symbol: trace_text_field
- name: json_safe_trace_attrs
  file: src/sevn/agent/tracing/attrs.py
  symbol: json_safe_trace_attrs
- name: json_safe_trace_value
  file: src/sevn/agent/tracing/attrs.py
  symbol: json_safe_trace_value
- name: trace_tool_result_value
  file: src/sevn/agent/tracing/attrs.py
  symbol: trace_tool_result_value
- name: register_trace_subscriber
  file: src/sevn/agent/tracing/emit.py
  symbol: register_trace_subscriber
- name: reset_trace_subscribers_for_tests
  file: src/sevn/agent/tracing/emit.py
  symbol: reset_trace_subscribers_for_tests
- name: unregister_trace_subscriber
  file: src/sevn/agent/tracing/emit.py
  symbol: unregister_trace_subscriber
- name: wrap_trace_sink
  file: src/sevn/agent/tracing/emit.py
  symbol: wrap_trace_sink
- name: LogfireExportStatus
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: LogfireExportStatus
- name: apply_logfire_export_to_sevn_doc
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: apply_logfire_export_to_sevn_doc
- name: logfire_export_status
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: logfire_export_status
- name: logfire_export_status_from_doc
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: logfire_export_status_from_doc
- name: logfire_sink_entry_for_tests
  file: src/sevn/agent/tracing/logfire_config.py
  symbol: logfire_sink_entry_for_tests
- name: MultiSink
  file: src/sevn/agent/tracing/multi_sink.py
  symbol: MultiSink
- name: OTelExporterSink
  file: src/sevn/agent/tracing/otel_sink.py
  symbol: OTelExporterSink
- name: emit_provider_call
  file: src/sevn/agent/tracing/provider_call.py
  symbol: emit_provider_call
- name: RedactingSink
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: RedactingSink
- name: TraceRedactionPolicy
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: TraceRedactionPolicy
- name: redact
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: redact
- name: redact_attrs
  file: src/sevn/agent/tracing/redacting_sink.py
  symbol: redact_attrs
- name: apply_trace_redaction_to_sevn_doc
  file: src/sevn/agent/tracing/redaction_config.py
  symbol: apply_trace_redaction_to_sevn_doc
- name: effective_trace_redaction_enabled_from_doc
  file: src/sevn/agent/tracing/redaction_config.py
  symbol: effective_trace_redaction_enabled_from_doc
- name: RotatingJSONLFileSink
  file: src/sevn/agent/tracing/rotating_jsonl_sink.py
  symbol: RotatingJSONLFileSink
- name: JSONLFileSink
  file: src/sevn/agent/tracing/sink.py
  symbol: JSONLFileSink
- name: NullTraceSink
  file: src/sevn/agent/tracing/sink.py
  symbol: NullTraceSink
- name: TraceEvent
  file: src/sevn/agent/tracing/sink.py
  symbol: TraceEvent
- name: TraceSink
  file: src/sevn/agent/tracing/sink.py
  symbol: TraceSink
- name: checkpoint_snapshot
  file: src/sevn/agent/tracing/sink.py
  symbol: checkpoint_snapshot
- name: current_sink
  file: src/sevn/agent/tracing/sink.py
  symbol: current_sink
- name: trace_sink_scope
  file: src/sevn/agent/tracing/sink.py
  symbol: trace_sink_scope
- name: build_gateway_trace_sink
  file: src/sevn/agent/tracing/sink_factory.py
  symbol: build_gateway_trace_sink
- name: build_gateway_trace_sink_async
  file: src/sevn/agent/tracing/sink_factory.py
  symbol: build_gateway_trace_sink_async
- name: trace_redaction_policy_for
  file: src/sevn/agent/tracing/sink_factory.py
  symbol: trace_redaction_policy_for
- name: SQLiteSink
  file: src/sevn/agent/tracing/sqlite_sink.py
  symbol: SQLiteSink
- name: cap_attrs_json
  file: src/sevn/agent/tracing/sqlite_sink.py
  symbol: cap_attrs_json
- name: redact_trace_attrs
  file: src/sevn/agent/tracing/sqlite_sink.py
  symbol: redact_trace_attrs
- name: SubAgentPrometheusCounts
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: SubAgentPrometheusCounts
- name: SubAgentTraceEmitter
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: SubAgentTraceEmitter
- name: bind_subagent_turn_context
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: bind_subagent_turn_context
- name: build_subagent_trace_hook
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: build_subagent_trace_hook
- name: reset_subagent_trace_for_tests
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: reset_subagent_trace_for_tests
- name: reset_subagent_turn_context
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: reset_subagent_turn_context
- name: subagent_trace_scope
  file: src/sevn/agent/tracing/subagent_trace.py
  symbol: subagent_trace_scope
- name: TraceEventOtelBridge
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: TraceEventOtelBridge
- name: attach_turn_trace_context
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: attach_turn_trace_context
- name: get_trace_event_bridge
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: get_trace_event_bridge
- name: set_trace_event_bridge
  file: src/sevn/agent/tracing/trace_event_bridge.py
  symbol: set_trace_event_bridge
- name: purge_trace_events_ttl
  file: src/sevn/agent/tracing/traces_maintenance.py
  symbol: purge_trace_events_ttl
- name: write_hourly_rollups
  file: src/sevn/agent/tracing/traces_maintenance.py
  symbol: write_hourly_rollups
- name: apply_traces_migrations
  file: src/sevn/agent/tracing/traces_migrate.py
  symbol: apply_traces_migrations
- name: ensure_trace_connection
  file: src/sevn/agent/tracing/traces_migrate.py
  symbol: ensure_trace_connection
- name: ensure_traces_db
  file: src/sevn/agent/tracing/traces_migrate.py
  symbol: ensure_traces_db
- name: TranscriptRow
  file: src/sevn/agent/transcript_replay.py
  symbol: TranscriptRow
- name: anthropic_messages_to_pydantic_history
  file: src/sevn/agent/transcript_replay.py
  symbol: anthropic_messages_to_pydantic_history
- name: build_cross_turn_message_history
  file: src/sevn/agent/transcript_replay.py
  symbol: build_cross_turn_message_history
- name: sanitize_provider_turn_messages_for_storage
  file: src/sevn/agent/transcript_replay.py
  symbol: sanitize_provider_turn_messages_for_storage
- name: serialize_provider_turn_messages
  file: src/sevn/agent/transcript_replay.py
  symbol: serialize_provider_turn_messages
- name: slim_transcript_for_log_provenance
  file: src/sevn/agent/transcript_replay.py
  symbol: slim_transcript_for_log_provenance
- name: ApprovedUserTurn
  file: src/sevn/agent/triager/context.py
  symbol: ApprovedUserTurn
- name: RegistryIndexEntry
  file: src/sevn/agent/triager/context.py
  symbol: RegistryIndexEntry
- name: RegistrySnapshot
  file: src/sevn/agent/triager/context.py
  symbol: RegistrySnapshot
- name: SessionView
  file: src/sevn/agent/triager/context.py
  symbol: SessionView
- name: SkillSurfaceEntry
  file: src/sevn/agent/triager/context.py
  symbol: SkillSurfaceEntry
- name: TriagePromptContext
  file: src/sevn/agent/triager/context.py
  symbol: TriagePromptContext
- name: TriagerUnknownToolAbort
  file: src/sevn/agent/triager/errors.py
  symbol: TriagerUnknownToolAbort
- name: ComplexityTier
  file: src/sevn/agent/triager/models.py
  symbol: ComplexityTier
- name: Intent
  file: src/sevn/agent/triager/models.py
  symbol: Intent
- name: MessageKind
  file: src/sevn/agent/triager/models.py
  symbol: MessageKind
- name: TelegramFollowupAnchor
  file: src/sevn/agent/triager/models.py
  symbol: TelegramFollowupAnchor
- name: TriageResult
  file: src/sevn/agent/triager/models.py
  symbol: TriageResult
- name: WebUIFollowupAnchor
  file: src/sevn/agent/triager/models.py
  symbol: WebUIFollowupAnchor
- name: build_triager_prompt_segments
  file: src/sevn/agent/triager/prompt.py
  symbol: build_triager_prompt_segments
- name: concat_prompt_for_stub_llm
  file: src/sevn/agent/triager/prompt.py
  symbol: concat_prompt_for_stub_llm
- name: RelatednessDecision
  file: src/sevn/agent/triager/relatedness.py
  symbol: RelatednessDecision
- name: RelatednessInput
  file: src/sevn/agent/triager/relatedness.py
  symbol: RelatednessInput
- name: RelatednessResult
  file: src/sevn/agent/triager/relatedness.py
  symbol: RelatednessResult
- name: classify_relatedness
  file: src/sevn/agent/triager/relatedness.py
  symbol: classify_relatedness
- name: routing_context_from_relatedness
  file: src/sevn/agent/triager/relatedness.py
  symbol: routing_context_from_relatedness
- name: apply_routing_policy
  file: src/sevn/agent/triager/routing_policy.py
  symbol: apply_routing_policy
- name: classify_greeting
  file: src/sevn/agent/triager/routing_policy.py
  symbol: classify_greeting
- name: default_early_ack
  file: src/sevn/agent/triager/routing_policy.py
  symbol: default_early_ack
- name: default_strict_tier_a_reply
  file: src/sevn/agent/triager/routing_policy.py
  symbol: default_strict_tier_a_reply
- name: default_tier_a_reply
  file: src/sevn/agent/triager/routing_policy.py
  symbol: default_tier_a_reply
- name: first_message_passes_opener_rule
  file: src/sevn/agent/triager/routing_policy.py
  symbol: first_message_passes_opener_rule
- name: is_browser_tool_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_browser_tool_message
- name: is_evolution_fix_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_evolution_fix_intent_message
- name: is_file_search_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_file_search_intent_message
- name: is_github_repo_eval_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_github_repo_eval_intent_message
- name: is_identity_or_capability_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_identity_or_capability_message
- name: is_lcm_status_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_lcm_status_message
- name: is_live_factual_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_live_factual_message
- name: is_log_provenance_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_log_provenance_intent_message
- name: is_memorize_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_memorize_message
- name: is_obvious_continuation_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_obvious_continuation_message
- name: is_package_install_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_package_install_message
- name: is_pdf_file_pipeline_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_pdf_file_pipeline_message
- name: is_registry_capability_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_registry_capability_intent_message
- name: is_registry_meta_howto_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_registry_meta_howto_message
- name: is_repo_code_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_repo_code_intent_message
- name: is_session_recall_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_session_recall_message
- name: is_skill_status_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_skill_status_intent_message
- name: is_strict_greeting_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_strict_greeting_message
- name: is_workspace_file_intent_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_workspace_file_intent_message
- name: prior_triage_indicates_in_progress
  file: src/sevn/agent/triager/routing_policy.py
  symbol: prior_triage_indicates_in_progress
- name: resolve_skill_status_target
  file: src/sevn/agent/triager/routing_policy.py
  symbol: resolve_skill_status_target
- name: try_fast_continuation_triage
  file: src/sevn/agent/triager/routing_policy.py
  symbol: try_fast_continuation_triage
- name: try_fast_greeting_triage
  file: src/sevn/agent/triager/routing_policy.py
  symbol: try_fast_greeting_triage
- name: StructuredOutputCallResult
  file: src/sevn/agent/triager/run.py
  symbol: StructuredOutputCallResult
- name: effective_triager_config
  file: src/sevn/agent/triager/run.py
  symbol: effective_triager_config
- name: extract_json_payload
  file: src/sevn/agent/triager/run.py
  symbol: extract_json_payload
- name: finalize_triage_result
  file: src/sevn/agent/triager/run.py
  symbol: finalize_triage_result
- name: permissions_scope_narrowing_enabled
  file: src/sevn/agent/triager/run.py
  symbol: permissions_scope_narrowing_enabled
- name: resolve_triager_model_id
  file: src/sevn/agent/triager/run.py
  symbol: resolve_triager_model_id
- name: resolve_triager_model_id_for_turn
  file: src/sevn/agent/triager/run.py
  symbol: resolve_triager_model_id_for_turn
- name: resolve_triager_transport_name
  file: src/sevn/agent/triager/run.py
  symbol: resolve_triager_transport_name
- name: should_inject_group_triage_block
  file: src/sevn/agent/triager/run.py
  symbol: should_inject_group_triage_block
- name: structured_output_call
  file: src/sevn/agent/triager/run.py
  symbol: structured_output_call
- name: triage_turn
  file: src/sevn/agent/triager/run.py
  symbol: triage_turn
- name: build_tool_index_lines
  file: src/sevn/agent/triager/tool_index.py
  symbol: build_tool_index_lines
---

## Purpose

The **Triager** is the routing brain: a single structured-generation step that emits
`TriageResult` consumed by tier dispatch (A/B/C/D), MCP overlays, and sub-agent specialist
grants. It is tool-less at generation time — tool/skill **names** are selected, not executed.

## Public Interface

| Symbol | Module | Role |
|--------|--------|------|
| `triage_turn` | `src/sevn/agent/triager/run.py` | Main entry |
| `finalize_triage_result` | same | Post-process LLM output |
| `structured_output_call` | same | Provider structured JSON call |
| `TriagePromptContext` | `src/sevn/agent/triager/context.py` | Prompt assembly inputs |
| `apply_routing_policy` | `src/sevn/agent/triager/routing_policy.py` | Deterministic policy layer |
| `try_fast_greeting_triage` | same | LLM bypass for greetings |
| `try_fast_continuation_triage` | same | LLM bypass for continuations |
| `TriagerUnavailable` | `src/sevn/agent/triager/errors.py` | Fatal routing-unavailable |
| `TriagerUnknownToolAbort` | same | Abort on unknown named tool |

Gateway wiring: `triage_context_from_session`, `is_triager_enabled`, `passthrough_triage_result`
in `src/sevn/gateway/triage/triage_context.py`.

## Data Model

Inputs: `ApprovedUserTurn`, `SessionView`, `RegistrySnapshot` (tool/skill names + caps).

Output: `TriageResult` (spec-10 ontology).

Config: `triager` section in `WorkspaceConfig` — model, provider, caps, personality blocks.

## Internal Architecture

```text
triage_context_from_session → triage_turn
    → fast paths (greeting / continuation)?
    → build prompt (prompt.py + context.py)
    → structured_output_call → finalize_triage_result
    → apply_routing_policy → TriageResult
```

Relatedness classifier for `multi` queue mode: `classify_busy_relatedness` in
`src/sevn/agent/triager/relatedness.py` (spec-36 amendment).

## Behavior

1. If triager disabled → `passthrough_triage_result` (tier B default).
2. Fast paths avoid LLM for obvious greetings/continuations when policy allows.
3. Prompt includes registry snapshot, session summary, channel constraints, persona blocks.
4. Policy clamps complexity, handles `disregard`, validates tool/skill ids against registry.
5. Gateway persists decision span `gateway.triage.completed`; tier A emits `first_message` as final.

## Failure Modes

| Condition | User-visible / log |
|-----------|-------------------|
| `TriagerUnavailable` | "Sorry — message routing is unavailable right now." |
| `TriagerUnknownToolAbort` | Turn abort (strict unknown-tool policy) |
| Provider timeout / empty fixture | Unavailable path |
| `disregard=True` | Silent return (no outbound) |
| Classifier timeout (`multi`) | Fall back to steer (spec-17) |

## Test Strategy

| Tests | Focus |
|-------|-------|
| `tests/agent/test_triager_run.py` | Core triage |
| `tests/agent/test_triager_routing_policy.py` | Policy |
| `tests/agent/test_triager_integration.py` | Provider integration |
| `tests/agent/test_triager_tracing.py` | OTel spans |
| `tests/gateway/test_triage_context.py` | Gateway integration |
| `tests/code_understanding/test_triager_orientation.py` | Orientation hints |
