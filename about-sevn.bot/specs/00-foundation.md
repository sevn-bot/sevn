---
id: spec-00-foundation
kind: spec
title: Foundation — Spec
status: draft
owner: Alex
summary: 'Deliver the lowest layer every later spec assumes: a src/sevn/ package layout,
  uv-managed Python 3.12+ project (hatchling build backend), a root Makefile as the
  single recurring-command surface, pre-c'
last_updated: '2026-07-14'
fingerprint: sha256:9e13b6fefba8c3db378874a014919674631edc707d55cfcc05f3e41a25e45926
related: []
sources:
- src/sevn/**
parent_prd: prd-00-main
depends_on: []
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
- name: steer_for_playwright_cdp_probe_failure
  file: src/sevn/agent/grounding.py
  symbol: steer_for_playwright_cdp_probe_failure
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
- name: generate_image_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_image_bytes
- name: generate_music_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_music_bytes
- name: generate_video_bytes
  file: src/sevn/agent/subagents/media_minimax.py
  symbol: generate_video_bytes
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
- name: apply_routing_policy
  file: src/sevn/agent/triager/routing_policy.py
  symbol: apply_routing_policy
- name: classify_greeting
  file: src/sevn/agent/triager/routing_policy.py
  symbol: classify_greeting
- name: default_early_ack
  file: src/sevn/agent/triager/routing_policy.py
  symbol: default_early_ack
- name: default_tier_a_reply
  file: src/sevn/agent/triager/routing_policy.py
  symbol: default_tier_a_reply
- name: first_message_passes_opener_rule
  file: src/sevn/agent/triager/routing_policy.py
  symbol: first_message_passes_opener_rule
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
- name: is_playwright_browser_message
  file: src/sevn/agent/triager/routing_policy.py
  symbol: is_playwright_browser_message
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
- name: LogoCell
  file: src/sevn/branding/logo_mark.py
  symbol: LogoCell
- name: build_marquee_frames
  file: src/sevn/branding/logo_mark.py
  symbol: build_marquee_frames
- name: build_palette
  file: src/sevn/branding/logo_mark.py
  symbol: build_palette
- name: build_reveal_frames
  file: src/sevn/branding/logo_mark.py
  symbol: build_reveal_frames
- name: convert_colored
  file: src/sevn/branding/logo_mark.py
  symbol: convert_colored
- name: grid_from_image_path
  file: src/sevn/branding/logo_mark.py
  symbol: grid_from_image_path
- name: hex_to_rgb
  file: src/sevn/branding/logo_mark.py
  symbol: hex_to_rgb
- name: load_bundled_logo_png
  file: src/sevn/branding/logo_mark.py
  symbol: load_bundled_logo_png
- name: parse_palette_from_css
  file: src/sevn/branding/logo_mark.py
  symbol: parse_palette_from_css
- name: parse_palette_from_svg
  file: src/sevn/branding/logo_mark.py
  symbol: parse_palette_from_svg
- name: play_bundled_logo_animation
  file: src/sevn/branding/logo_mark.py
  symbol: play_bundled_logo_animation
- name: play_frames
  file: src/sevn/branding/logo_mark.py
  symbol: play_frames
- name: render_ansi
  file: src/sevn/branding/logo_mark.py
  symbol: render_ansi
- name: render_html
  file: src/sevn/branding/logo_mark.py
  symbol: render_html
- name: render_plain
  file: src/sevn/branding/logo_mark.py
  symbol: render_plain
- name: rgb_to_hex
  file: src/sevn/branding/logo_mark.py
  symbol: rgb_to_hex
- name: trim_grid
  file: src/sevn/branding/logo_mark.py
  symbol: trim_grid
- name: logo_splash_enabled
  file: src/sevn/branding/splash.py
  symbol: logo_splash_enabled
- name: maybe_play_logo_splash
  file: src/sevn/branding/splash.py
  symbol: maybe_play_logo_splash
- name: build_trot_frames
  file: src/sevn/branding/unicorn_trot.py
  symbol: build_trot_frames
- name: compose_trot_track
  file: src/sevn/branding/unicorn_trot.py
  symbol: compose_trot_track
- name: play_unicorn_trot
  file: src/sevn/branding/unicorn_trot.py
  symbol: play_unicorn_trot
- name: render_halfblock
  file: src/sevn/branding/unicorn_trot.py
  symbol: render_halfblock
- name: sprite_rows
  file: src/sevn/branding/unicorn_trot.py
  symbol: sprite_rows
- name: AuthError
  file: src/sevn/browser/auth.py
  symbol: AuthError
- name: SiteProfile
  file: src/sevn/browser/auth.py
  symbol: SiteProfile
- name: export_cookies
  file: src/sevn/browser/auth.py
  symbol: export_cookies
- name: human_handoff
  file: src/sevn/browser/auth.py
  symbol: human_handoff
- name: import_cookies
  file: src/sevn/browser/auth.py
  symbol: import_cookies
- name: login
  file: src/sevn/browser/auth.py
  symbol: login
- name: login_state
  file: src/sevn/browser/auth.py
  symbol: login_state
- name: resolve_login_credentials
  file: src/sevn/browser/auth.py
  symbol: resolve_login_credentials
- name: resume_login
  file: src/sevn/browser/auth.py
  symbol: resume_login
- name: site_profile
  file: src/sevn/browser/auth.py
  symbol: site_profile
- name: CDPConnection
  file: src/sevn/browser/cdp/connection.py
  symbol: CDPConnection
- name: CDPError
  file: src/sevn/browser/cdp/protocol.py
  symbol: CDPError
- name: CDPSession
  file: src/sevn/browser/cdp/session.py
  symbol: CDPSession
- name: Dom
  file: src/sevn/browser/element.py
  symbol: Dom
- name: ElementError
  file: src/sevn/browser/element.py
  symbol: ElementError
- name: ElementHandle
  file: src/sevn/browser/element.py
  symbol: ElementHandle
- name: CDPBrowserSession
  file: src/sevn/browser/lifecycle.py
  symbol: CDPBrowserSession
- name: fetch_browser_ws_url
  file: src/sevn/browser/lifecycle.py
  symbol: fetch_browser_ws_url
- name: get_or_create_session
  file: src/sevn/browser/lifecycle.py
  symbol: get_or_create_session
- name: release_session
  file: src/sevn/browser/lifecycle.py
  symbol: release_session
- name: reset_pool_for_tests
  file: src/sevn/browser/lifecycle.py
  symbol: reset_pool_for_tests
- name: spawn_or_attach
  file: src/sevn/browser/lifecycle.py
  symbol: spawn_or_attach
- name: Page
  file: src/sevn/browser/page.py
  symbol: Page
- name: PageError
  file: src/sevn/browser/page.py
  symbol: PageError
- name: RecipeError
  file: src/sevn/browser/recipes/base.py
  symbol: RecipeError
- name: host_allowed
  file: src/sevn/browser/recipes/base.py
  symbol: host_allowed
- name: human_required
  file: src/sevn/browser/recipes/base.py
  symbol: human_required
- name: recipe_write_allowed
  file: src/sevn/browser/recipes/base.py
  symbol: recipe_write_allowed
- name: require_write_allowed
  file: src/sevn/browser/recipes/base.py
  symbol: require_write_allowed
- name: validate_egress
  file: src/sevn/browser/recipes/base.py
  symbol: validate_egress
- name: Gmail
  file: src/sevn/browser/recipes/gmail.py
  symbol: Gmail
- name: parse_inbox
  file: src/sevn/browser/recipes/gmail.py
  symbol: parse_inbox
- name: parse_message
  file: src/sevn/browser/recipes/gmail.py
  symbol: parse_message
- name: GoogleMaps
  file: src/sevn/browser/recipes/google_maps.py
  symbol: GoogleMaps
- name: parse_directions
  file: src/sevn/browser/recipes/google_maps.py
  symbol: parse_directions
- name: parse_place
  file: src/sevn/browser/recipes/google_maps.py
  symbol: parse_place
- name: parse_places
  file: src/sevn/browser/recipes/google_maps.py
  symbol: parse_places
- name: parse_reviews
  file: src/sevn/browser/recipes/google_maps.py
  symbol: parse_reviews
- name: GoogleSearch
  file: src/sevn/browser/recipes/google_search.py
  symbol: GoogleSearch
- name: parse_ai_overview
  file: src/sevn/browser/recipes/google_search.py
  symbol: parse_ai_overview
- name: parse_gemini_answer
  file: src/sevn/browser/recipes/google_search.py
  symbol: parse_gemini_answer
- name: parse_search_results
  file: src/sevn/browser/recipes/google_search.py
  symbol: parse_search_results
- name: LinkedInRecipe
  file: src/sevn/browser/recipes/linkedin.py
  symbol: LinkedInRecipe
- name: dry_run_requested
  file: src/sevn/browser/recipes/linkedin.py
  symbol: dry_run_requested
- name: linkedin_write_allowed
  file: src/sevn/browser/recipes/linkedin.py
  symbol: linkedin_write_allowed
- name: run_linkedin_op
  file: src/sevn/browser/recipes/linkedin.py
  symbol: run_linkedin_op
- name: run_linkedin_op_sync
  file: src/sevn/browser/recipes/linkedin.py
  symbol: run_linkedin_op_sync
- name: Certification
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: Certification
- name: Comment
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: Comment
- name: ContactInfo
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: ContactInfo
- name: Experience
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: Experience
- name: School
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: School
- name: Skill
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: Skill
- name: Staff
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: Staff
- name: create_emails
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: create_emails
- name: extract_base_domain
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: extract_base_domain
- name: extract_emails_from_text
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: extract_emails_from_text
- name: parse_company_data
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: parse_company_data
- name: parse_date
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: parse_date
- name: parse_dates
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: parse_dates
- name: parse_duration
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: parse_duration
- name: staff_rows_to_dicts
  file: src/sevn/browser/recipes/linkedin_models.py
  symbol: staff_rows_to_dicts
- name: GeoUrnNotFound
  file: src/sevn/browser/recipes/linkedin_scraper.py
  symbol: GeoUrnNotFound
- name: LinkedInVoyagerScraper
  file: src/sevn/browser/recipes/linkedin_scraper.py
  symbol: LinkedInVoyagerScraper
- name: RateLimitedError
  file: src/sevn/browser/recipes/linkedin_scraper.py
  symbol: RateLimitedError
- name: VoyagerClient
  file: src/sevn/browser/recipes/linkedin_scraper.py
  symbol: VoyagerClient
- name: VoyagerResponse
  file: src/sevn/browser/recipes/linkedin_scraper.py
  symbol: VoyagerResponse
- name: VoyagerStaleError
  file: src/sevn/browser/recipes/linkedin_scraper.py
  symbol: VoyagerStaleError
- name: SocialRecipe
  file: src/sevn/browser/recipes/social.py
  symbol: SocialRecipe
- name: parse_comments_html
  file: src/sevn/browser/recipes/social.py
  symbol: parse_comments_html
- name: parse_post_html
  file: src/sevn/browser/recipes/social.py
  symbol: parse_post_html
- name: social_write_allowed
  file: src/sevn/browser/recipes/social.py
  symbol: social_write_allowed
- name: TelegramWeb
  file: src/sevn/browser/recipes/telegram_web.py
  symbol: TelegramWeb
- name: extract_bot_token
  file: src/sevn/browser/recipes/telegram_web.py
  symbol: extract_bot_token
- name: YouTube
  file: src/sevn/browser/recipes/youtube.py
  symbol: YouTube
- name: parse_comments
  file: src/sevn/browser/recipes/youtube.py
  symbol: parse_comments
- name: parse_replies
  file: src/sevn/browser/recipes/youtube.py
  symbol: parse_replies
- name: parse_search_results
  file: src/sevn/browser/recipes/youtube.py
  symbol: parse_search_results
- name: parse_video_info
  file: src/sevn/browser/recipes/youtube.py
  symbol: parse_video_info
- name: PlatformChannelConfig
  file: src/sevn/channels/_common.py
  symbol: PlatformChannelConfig
- name: busy_input_mode_for_channel
  file: src/sevn/channels/_common.py
  symbol: busy_input_mode_for_channel
- name: channel_blob
  file: src/sevn/channels/_common.py
  symbol: channel_blob
- name: dm_policy_for_channel
  file: src/sevn/channels/_common.py
  symbol: dm_policy_for_channel
- name: platform_config_from_workspace
  file: src/sevn/channels/_common.py
  symbol: platform_config_from_workspace
- name: session_reset_policy_for_channel
  file: src/sevn/channels/_common.py
  symbol: session_reset_policy_for_channel
- name: resolve_dispatcher_overflow_callback_data
  file: src/sevn/channels/callback_overflow.py
  symbol: resolve_dispatcher_overflow_callback_data
- name: telegram_callback_data_utf8_len
  file: src/sevn/channels/callback_overflow.py
  symbol: telegram_callback_data_utf8_len
- name: tokenize_inline_keyboard_callback_data
  file: src/sevn/channels/callback_overflow.py
  symbol: tokenize_inline_keyboard_callback_data
- name: DiscordChannelAdapter
  file: src/sevn/channels/discord.py
  symbol: DiscordChannelAdapter
- name: escape_intent_footer
  file: src/sevn/channels/markdown_safe.py
  symbol: escape_intent_footer
- name: escape_markdown_v2
  file: src/sevn/channels/markdown_safe.py
  symbol: escape_markdown_v2
- name: SelfImproveTelegramNotification
  file: src/sevn/channels/self_improve_copy.py
  symbol: SelfImproveTelegramNotification
- name: format_self_improve_job_telegram
  file: src/sevn/channels/self_improve_copy.py
  symbol: format_self_improve_job_telegram
- name: SlackChannelAdapter
  file: src/sevn/channels/slack.py
  symbol: SlackChannelAdapter
- name: StubChannelAdapter
  file: src/sevn/channels/stub.py
  symbol: StubChannelAdapter
- name: make_stub_adapter_class
  file: src/sevn/channels/stub.py
  symbol: make_stub_adapter_class
- name: TelegramAdapter
  file: src/sevn/channels/telegram.py
  symbol: TelegramAdapter
- name: TelegramApiMixin
  file: src/sevn/channels/telegram_api.py
  symbol: TelegramApiMixin
- name: RichCapability
  file: src/sevn/channels/telegram_capabilities.py
  symbol: RichCapability
- name: bot_api_error_description
  file: src/sevn/channels/telegram_capabilities.py
  symbol: bot_api_error_description
- name: detect_rich_support
  file: src/sevn/channels/telegram_capabilities.py
  symbol: detect_rich_support
- name: is_method_not_found_response
  file: src/sevn/channels/telegram_capabilities.py
  symbol: is_method_not_found_response
- name: is_rich_payload_rejected
  file: src/sevn/channels/telegram_capabilities.py
  symbol: is_rich_payload_rejected
- name: DMPolicy
  file: src/sevn/channels/telegram_config.py
  symbol: DMPolicy
- name: TelegramConfig
  file: src/sevn/channels/telegram_config.py
  symbol: TelegramConfig
- name: TelegramSendError
  file: src/sevn/channels/telegram_config.py
  symbol: TelegramSendError
- name: TopicConfig
  file: src/sevn/channels/telegram_config.py
  symbol: TopicConfig
- name: build_reply_keyboard_markup
  file: src/sevn/channels/telegram_config.py
  symbol: build_reply_keyboard_markup
- name: chunk_text
  file: src/sevn/channels/telegram_config.py
  symbol: chunk_text
- name: format_reply_quote
  file: src/sevn/channels/telegram_config.py
  symbol: format_reply_quote
- name: telegram_config_from_workspace
  file: src/sevn/channels/telegram_config.py
  symbol: telegram_config_from_workspace
- name: telegram_utf16_len
  file: src/sevn/channels/telegram_config.py
  symbol: telegram_utf16_len
- name: build_file_link_keyboard
  file: src/sevn/channels/telegram_file_links.py
  symbol: build_file_link_keyboard
- name: extract_file_link_paths
  file: src/sevn/channels/telegram_file_links.py
  symbol: extract_file_link_paths
- name: parse_file_link_callback
  file: src/sevn/channels/telegram_file_links.py
  symbol: parse_file_link_callback
- name: strip_file_link_markers
  file: src/sevn/channels/telegram_file_links.py
  symbol: strip_file_link_markers
- name: markdown_tables_to_pre
  file: src/sevn/channels/telegram_format.py
  symbol: markdown_tables_to_pre
- name: to_telegram
  file: src/sevn/channels/telegram_format.py
  symbol: to_telegram
- name: TelegramInboundMixin
  file: src/sevn/channels/telegram_inbound.py
  symbol: TelegramInboundMixin
- name: TelegramInlineSendMixin
  file: src/sevn/channels/telegram_inline_send.py
  symbol: TelegramInlineSendMixin
- name: MarkdownRegionDict
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: MarkdownRegionDict
- name: find_markdown_regions
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: find_markdown_regions
- name: parse_markdown_table
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: parse_markdown_table
- name: parse_table_alignments
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: parse_table_alignments
- name: TelegramOutboundMixin
  file: src/sevn/channels/telegram_outbound.py
  symbol: TelegramOutboundMixin
- name: TelegramPollMixin
  file: src/sevn/channels/telegram_poll.py
  symbol: TelegramPollMixin
- name: build_input_rich_message_markdown
  file: src/sevn/channels/telegram_rich.py
  symbol: build_input_rich_message_markdown
- name: render_markdown_to_rich_message
  file: src/sevn/channels/telegram_rich.py
  symbol: render_markdown_to_rich_message
- name: rich_module_ready
  file: src/sevn/channels/telegram_rich.py
  symbol: rich_module_ready
- name: build_anchor
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_anchor
- name: build_animation
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_animation
- name: build_audio
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_audio
- name: build_block_quotation
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_block_quotation
- name: build_caption
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_caption
- name: build_collage
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_collage
- name: build_details
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_details
- name: build_divider
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_divider
- name: build_footer
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_footer
- name: build_input_rich_message
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_input_rich_message
- name: build_list
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_list
- name: build_list_item
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_list_item
- name: build_math
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_math
- name: build_paragraph
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_paragraph
- name: build_photo
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_photo
- name: build_preformatted
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_preformatted
- name: build_pull_quotation
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_pull_quotation
- name: build_section_heading
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_section_heading
- name: build_slideshow
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_slideshow
- name: build_table
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_table
- name: build_table_cell
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_table_cell
- name: build_thinking
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_thinking
- name: build_video
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_video
- name: build_voice_note
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_voice_note
- name: parse_media_directive_attrs
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: parse_media_directive_attrs
- name: resolve_media_source
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: resolve_media_source
- name: rich_blocks_module_ready
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: rich_blocks_module_ready
- name: rich_text
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: rich_text
- name: rich_text_plain
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: rich_text_plain
- name: RichFallbackReason
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: RichFallbackReason
- name: is_reply_rich_worthy
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: is_reply_rich_worthy
- name: resolve_rich_config
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: resolve_rich_config
- name: send_with_rich_fallback
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: send_with_rich_fallback
- name: should_use_rich
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: should_use_rich
- name: ast_to_input_rich_message
  file: src/sevn/channels/telegram_rich_map.py
  symbol: ast_to_input_rich_message
- name: inline_to_rich_json
  file: src/sevn/channels/telegram_rich_map.py
  symbol: inline_to_rich_json
- name: inline_to_rich_text
  file: src/sevn/channels/telegram_rich_map.py
  symbol: inline_to_rich_text
- name: AstAnchor
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstAnchor
- name: AstBlockquote
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstBlockquote
- name: AstCollage
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstCollage
- name: AstDetails
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstDetails
- name: AstDivider
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstDivider
- name: AstFooter
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstFooter
- name: AstHeading
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstHeading
- name: AstInlineCode
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineCode
- name: AstInlineLink
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineLink
- name: AstInlineMath
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineMath
- name: AstInlineMention
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineMention
- name: AstInlineStyled
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineStyled
- name: AstInlineText
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineText
- name: AstList
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstList
- name: AstListItem
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstListItem
- name: AstMathBlock
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstMathBlock
- name: AstMedia
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstMedia
- name: AstParagraph
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstParagraph
- name: AstPreformatted
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstPreformatted
- name: AstPullQuote
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstPullQuote
- name: AstSlideshow
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstSlideshow
- name: AstTable
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstTable
- name: AstThinking
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstThinking
- name: markdown_to_ast
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: markdown_to_ast
- name: TelegramRichSendMixin
  file: src/sevn/channels/telegram_rich_send.py
  symbol: TelegramRichSendMixin
- name: serialize_input_rich_message
  file: src/sevn/channels/telegram_rich_validate.py
  symbol: serialize_input_rich_message
- name: validate_rich_message_shape
  file: src/sevn/channels/telegram_rich_validate.py
  symbol: validate_rich_message_shape
- name: TelegramTextSendMixin
  file: src/sevn/channels/telegram_send_edit.py
  symbol: TelegramTextSendMixin
- name: build_text_api_body
  file: src/sevn/channels/telegram_send_edit.py
  symbol: build_text_api_body
- name: is_entity_parse_error
  file: src/sevn/channels/telegram_send_edit.py
  symbol: is_entity_parse_error
- name: is_message_not_modified
  file: src/sevn/channels/telegram_send_edit.py
  symbol: is_message_not_modified
- name: is_message_too_long_desc
  file: src/sevn/channels/telegram_send_edit.py
  symbol: is_message_too_long_desc
- name: TelegramSendHost
  file: src/sevn/channels/telegram_send_host.py
  symbol: TelegramSendHost
- name: add_custom_button
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: add_custom_button
- name: build_custom_inline_keyboard
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: build_custom_inline_keyboard
- name: buttons_store_path
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: buttons_store_path
- name: clear_custom_buttons
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: clear_custom_buttons
- name: list_custom_buttons
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: list_custom_buttons
- name: remove_custom_button
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: remove_custom_button
- name: create_forum_topic
  file: src/sevn/channels/telegram_skill/forum.py
  symbol: create_forum_topic
- name: find_group_by_name
  file: src/sevn/channels/telegram_skill/forum.py
  symbol: find_group_by_name
- name: TelegramSkillHooks
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: TelegramSkillHooks
- name: bot_api_call_from_adapter
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: bot_api_call_from_adapter
- name: bot_api_call_from_token
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: bot_api_call_from_token
- name: resolve_telegram_skill_hooks
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: resolve_telegram_skill_hooks
- name: WebChatAdapter
  file: src/sevn/channels/webchat.py
  symbol: WebChatAdapter
- name: WebChatConfig
  file: src/sevn/channels/webchat.py
  symbol: WebChatConfig
- name: webchat_config_from_workspace
  file: src/sevn/channels/webchat.py
  symbol: webchat_config_from_workspace
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
  file: src/sevn/cli/commands/telegram_test.py
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
- name: code_orientation_doctor_checks
  file: src/sevn/code_understanding/bootstrap.py
  symbol: code_orientation_doctor_checks
- name: mycode_needs_refresh
  file: src/sevn/code_understanding/bootstrap.py
  symbol: mycode_needs_refresh
- name: refresh_mycode_scan_cache
  file: src/sevn/code_understanding/bootstrap.py
  symbol: refresh_mycode_scan_cache
- name: build_cgr_argv
  file: src/sevn/code_understanding/cgr_adapter.py
  symbol: build_cgr_argv
- name: read_export_capped
  file: src/sevn/code_understanding/cgr_adapter.py
  symbol: read_export_capped
- name: read_export_file
  file: src/sevn/code_understanding/cgr_runner.py
  symbol: read_export_file
- name: run_cgr_subprocess
  file: src/sevn/code_understanding/cgr_runner.py
  symbol: run_cgr_subprocess
- name: DocstringGap
  file: src/sevn/code_understanding/code_index.py
  symbol: DocstringGap
- name: SymbolEntry
  file: src/sevn/code_understanding/code_index.py
  symbol: SymbolEntry
- name: audit_docstring_coverage
  file: src/sevn/code_understanding/code_index.py
  symbol: audit_docstring_coverage
- name: collect_module_symbols
  file: src/sevn/code_understanding/code_index.py
  symbol: collect_module_symbols
- name: extract_listed_symbols
  file: src/sevn/code_understanding/code_index.py
  symbol: extract_listed_symbols
- name: generate_code_index
  file: src/sevn/code_understanding/code_index.py
  symbol: generate_code_index
- name: iter_python_files
  file: src/sevn/code_understanding/code_index.py
  symbol: iter_python_files
- name: render_code_index_markdown
  file: src/sevn/code_understanding/code_index.py
  symbol: render_code_index_markdown
- name: build_serve_argv
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: build_serve_argv
- name: code_review_graph_mcp_enabled
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: code_review_graph_mcp_enabled
- name: code_review_graph_mcp_server_id
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: code_review_graph_mcp_server_id
- name: mcp_stdio_entry
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: mcp_stdio_entry
- name: merge_code_review_graph_mcp_server
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: merge_code_review_graph_mcp_server
- name: read_only_tool_names
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: read_only_tool_names
- name: resolve_command
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: resolve_command
- name: resolve_repo_root
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: resolve_repo_root
- name: validate_repo_root
  file: src/sevn/code_understanding/code_review_graph_mcp.py
  symbol: validate_repo_root
- name: effective_code_understanding
  file: src/sevn/code_understanding/effective_settings.py
  symbol: effective_code_understanding
- name: effective_graphify_settings
  file: src/sevn/code_understanding/effective_settings.py
  symbol: effective_graphify_settings
- name: graphify_enabled_for_checkout
  file: src/sevn/code_understanding/effective_settings.py
  symbol: graphify_enabled_for_checkout
- name: active_profiles_with_report
  file: src/sevn/code_understanding/graphify.py
  symbol: active_profiles_with_report
- name: clear_resolve_active_profiles_cache
  file: src/sevn/code_understanding/graphify.py
  symbol: clear_resolve_active_profiles_cache
- name: graph_json_path
  file: src/sevn/code_understanding/graphify.py
  symbol: graph_json_path
- name: graph_report_path
  file: src/sevn/code_understanding/graphify.py
  symbol: graph_report_path
- name: profile_covers
  file: src/sevn/code_understanding/graphify.py
  symbol: profile_covers
- name: resolve_active_profiles_cached
  file: src/sevn/code_understanding/graphify.py
  symbol: resolve_active_profiles_cached
- name: resolve_profiles
  file: src/sevn/code_understanding/graphify.py
  symbol: resolve_profiles
- name: search_tool_prefix
  file: src/sevn/code_understanding/graphify.py
  symbol: search_tool_prefix
- name: build_effective_mcp_servers
  file: src/sevn/code_understanding/graphify_mcp.py
  symbol: build_effective_mcp_servers
- name: graphify_mcp_enabled
  file: src/sevn/code_understanding/graphify_mcp.py
  symbol: graphify_mcp_enabled
- name: graphify_mcp_server_ids
  file: src/sevn/code_understanding/graphify_mcp.py
  symbol: graphify_mcp_server_ids
- name: merge_gateway_mcp_servers
  file: src/sevn/code_understanding/graphify_mcp.py
  symbol: merge_gateway_mcp_servers
- name: build_graphify_index
  file: src/sevn/code_understanding/graphify_seed.py
  symbol: build_graphify_index
- name: graphify_needs_refresh
  file: src/sevn/code_understanding/graphify_seed.py
  symbol: graphify_needs_refresh
- name: graphify_report_mirror_path
  file: src/sevn/code_understanding/graphify_seed.py
  symbol: graphify_report_mirror_path
- name: seed_graphify_mirror
  file: src/sevn/code_understanding/graphify_seed.py
  symbol: seed_graphify_mirror
- name: CodeGraphRagSettings
  file: src/sevn/code_understanding/models.py
  symbol: CodeGraphRagSettings
- name: CodeReviewGraphSettings
  file: src/sevn/code_understanding/models.py
  symbol: CodeReviewGraphSettings
- name: CodeUnderstandingSettings
  file: src/sevn/code_understanding/models.py
  symbol: CodeUnderstandingSettings
- name: GraphifyProfile
  file: src/sevn/code_understanding/models.py
  symbol: GraphifyProfile
- name: GraphifySettings
  file: src/sevn/code_understanding/models.py
  symbol: GraphifySettings
- name: MycodeFileEntry
  file: src/sevn/code_understanding/models.py
  symbol: MycodeFileEntry
- name: MycodeScanDigest
  file: src/sevn/code_understanding/models.py
  symbol: MycodeScanDigest
- name: MycodeSettings
  file: src/sevn/code_understanding/models.py
  symbol: MycodeSettings
- name: RoamCodeSettings
  file: src/sevn/code_understanding/models.py
  symbol: RoamCodeSettings
- name: cache_path_for_root
  file: src/sevn/code_understanding/mycode_cache.py
  symbol: cache_path_for_root
- name: save_scan_cache
  file: src/sevn/code_understanding/mycode_cache.py
  symbol: save_scan_cache
- name: scan_repo_cached
  file: src/sevn/code_understanding/mycode_cache.py
  symbol: scan_repo_cached
- name: Transport
  file: src/sevn/code_understanding/mycode_generate.py
  symbol: Transport
- name: generate_mycode_markdown
  file: src/sevn/code_understanding/mycode_generate.py
  symbol: generate_mycode_markdown
- name: write_mycode
  file: src/sevn/code_understanding/mycode_generate.py
  symbol: write_mycode
- name: scan_repo
  file: src/sevn/code_understanding/mycode_scan.py
  symbol: scan_repo
- name: build_openwiki_argv
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: build_openwiki_argv
- name: content_root_from_env
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: content_root_from_env
- name: looks_like_credentials_error
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: looks_like_credentials_error
- name: openwiki_missing_message
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: openwiki_missing_message
- name: openwiki_status
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: openwiki_status
- name: resolve_openwiki_root
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: resolve_openwiki_root
- name: run_openwiki_subprocess
  file: src/sevn/code_understanding/openwiki_runner.py
  symbol: run_openwiki_subprocess
- name: RoamCodeAdapter
  file: src/sevn/code_understanding/roam_code_adapter.py
  symbol: RoamCodeAdapter
- name: build_roam_argv
  file: src/sevn/code_understanding/roam_runner.py
  symbol: build_roam_argv
- name: run_roam_query
  file: src/sevn/code_understanding/roam_runner.py
  symbol: run_roam_query
- name: run_roam_query_async
  file: src/sevn/code_understanding/roam_runner.py
  symbol: run_roam_query_async
- name: run_roam_subprocess
  file: src/sevn/code_understanding/roam_runner.py
  symbol: run_roam_subprocess
- name: code_graph_rag_cli_tool
  file: src/sevn/code_understanding/tools_register.py
  symbol: code_graph_rag_cli_tool
- name: code_graph_rag_read_export_tool
  file: src/sevn/code_understanding/tools_register.py
  symbol: code_graph_rag_read_export_tool
- name: legacy_native_code_graph_rag_enabled
  file: src/sevn/code_understanding/tools_register.py
  symbol: legacy_native_code_graph_rag_enabled
- name: legacy_native_roam_code_enabled
  file: src/sevn/code_understanding/tools_register.py
  symbol: legacy_native_roam_code_enabled
- name: register_code_understanding_tools
  file: src/sevn/code_understanding/tools_register.py
  symbol: register_code_understanding_tools
- name: roam_code_tool
  file: src/sevn/code_understanding/tools_register.py
  symbol: roam_code_tool
- name: infer_orientation_intent
  file: src/sevn/code_understanding/triager_orientation.py
  symbol: infer_orientation_intent
- name: orientation_block_for_workspace
  file: src/sevn/code_understanding/triager_orientation.py
  symbol: orientation_block_for_workspace
- name: EvaluatorResult
  file: src/sevn/coding_agents/alrca/evaluator.py
  symbol: EvaluatorResult
- name: NullEvaluator
  file: src/sevn/coding_agents/alrca/evaluator.py
  symbol: NullEvaluator
- name: evaluate_turn
  file: src/sevn/coding_agents/alrca/evaluator.py
  symbol: evaluate_turn
- name: GoalContract
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: GoalContract
- name: GoalStatus
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: GoalStatus
- name: list_goals
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: list_goals
- name: load_goal
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: load_goal
- name: new_goal
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: new_goal
- name: save_goal
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: save_goal
- name: ALRCALoopWorker
  file: src/sevn/coding_agents/alrca/loop_worker.py
  symbol: ALRCALoopWorker
- name: LoopResult
  file: src/sevn/coding_agents/alrca/loop_worker.py
  symbol: LoopResult
- name: run_alrca_loop
  file: src/sevn/coding_agents/alrca/loop_worker.py
  symbol: run_alrca_loop
- name: BuiltinVerifierKind
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: BuiltinVerifierKind
- name: VerifierResult
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: VerifierResult
- name: build_verifier
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: build_verifier
- name: run_verifier_spec
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: run_verifier_spec
- name: list_all_runs
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: list_all_runs
- name: list_run_artifacts
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: list_run_artifacts
- name: read_artifact
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: read_artifact
- name: write_artifact
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: write_artifact
- name: StubExecutor
  file: src/sevn/coding_agents/executors/__init__.py
  symbol: StubExecutor
- name: build_executor
  file: src/sevn/coding_agents/executors/__init__.py
  symbol: build_executor
- name: ExecutorProtocol
  file: src/sevn/coding_agents/executors/protocol.py
  symbol: ExecutorProtocol
- name: ExecutorResult
  file: src/sevn/coding_agents/executors/protocol.py
  symbol: ExecutorResult
- name: migrate_legacy_claude_agent_topic
  file: src/sevn/coding_agents/migrate.py
  symbol: migrate_legacy_claude_agent_topic
- name: binding_matches
  file: src/sevn/coding_agents/registry.py
  symbol: binding_matches
- name: list_agent_summaries
  file: src/sevn/coding_agents/registry.py
  symbol: list_agent_summaries
- name: match_telegram_binding
  file: src/sevn/coding_agents/registry.py
  symbol: match_telegram_binding
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
- name: browser_cdp
  file: src/sevn/data/bundled_skills/core/browser-harness/helpers.py
  symbol: browser_cdp
- name: cdp_http_json
  file: src/sevn/data/bundled_skills/core/browser-harness/helpers.py
  symbol: cdp_http_json
- name: cdp_http_object
  file: src/sevn/data/bundled_skills/core/browser-harness/helpers.py
  symbol: cdp_http_object
- name: default_cdp_url
  file: src/sevn/data/bundled_skills/core/browser-harness/helpers.py
  symbol: default_cdp_url
- name: main
  file: src/sevn/data/bundled_skills/core/browser-harness/scripts/cdp.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/browser-harness/scripts/probe.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/browser-harness/scripts/run.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/canvas/scripts/compose_cards.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/canvas/scripts/compose_openui_payload.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/canvas/scripts/compose_table.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/code_graph_rag/scripts/cgr_cli.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/code_graph_rag/scripts/read_export.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/cua-agent/scripts/run_agent.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/cursor_cloud/scripts/launch.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/cursor_cloud/scripts/list_artifacts.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/cursor_cloud/scripts/list_jobs.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/cursor_cloud/scripts/status.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/email-management/scripts/fetch_recent.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/email-management/scripts/list_accounts.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/email-management/scripts/list_folders.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/email-management/scripts/search.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/email-management/scripts/send.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/facebook-use/scripts/feed.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/facebook-use/scripts/search.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/facebook-use/scripts/session_status.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-issues/scripts/issue_comment.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-issues/scripts/issue_create.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-issues/scripts/issue_list.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-issues/scripts/issue_view.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-pr/scripts/pr_close.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-pr/scripts/pr_create.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-pr/scripts/pr_list.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-pr/scripts/pr_merge.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-pr/scripts/pr_reviewers.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/gh-pr/scripts/pr_view.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/actions_list_workflows.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/actions_logs.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/actions_run.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/branch_create.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/branch_delete.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/branch_list.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/cicd_environments.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/cicd_secrets.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/cicd_vars.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/github-manager/scripts/deploy.py
  symbol: main
- name: build_graphify_argv
  file: src/sevn/data/bundled_skills/core/graphify/scripts/build.py
  symbol: build_graphify_argv
- name: main
  file: src/sevn/data/bundled_skills/core/graphify/scripts/build.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/cover_letter.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/interview_prep.py
  symbol: main
- name: fetch_html
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/browser_fetch.py
  symbol: fetch_html
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/adzuna.py
  symbol: run
- name: Extractor
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/base.py
  symbol: Extractor
- name: ExtractorResult
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/base.py
  symbol: ExtractorResult
- name: BrowserBoard
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/browser_board.py
  symbol: BrowserBoard
- name: parse_listing
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/browser_board.py
  symbol: parse_listing
- name: run_board
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/browser_board.py
  symbol: run_board
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/golangjobs.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/gradcracker.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/himalayas.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/hiringcafe.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/jobindex.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/jobnet.py
  symbol: run
- name: normalize_jobspy_records
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/jobspy_source.py
  symbol: normalize_jobspy_records
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/jobspy_source.py
  symbol: run
- name: available_sources
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/registry.py
  symbol: available_sources
- name: get_extractor
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/registry.py
  symbol: get_extractor
- name: source_matches
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/registry.py
  symbol: source_matches
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/remoteco.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/remoteok.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/remotive.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/startupjobs.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/ukvisajobs.py
  symbol: run
- name: run
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/extractors/workingnomads.py
  symbol: run
- name: ChallengeError
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/httpclient.py
  symbol: ChallengeError
- name: get_json
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/httpclient.py
  symbol: get_json
- name: get_text
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/httpclient.py
  symbol: get_text
- name: post_json
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/httpclient.py
  symbol: post_json
- name: LlmUnavailable
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py
  symbol: LlmUnavailable
- name: complete_json
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/llm.py
  symbol: complete_json
- name: JobPosting
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/models.py
  symbol: JobPosting
- name: Resume
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/models.py
  symbol: Resume
- name: ResumeReview
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/models.py
  symbol: ResumeReview
- name: ScoreResult
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/models.py
  symbol: ScoreResult
- name: SearchQuery
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/models.py
  symbol: SearchQuery
- name: content_root_from_env
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/settings.py
  symbol: content_root_from_env
- name: data_dir
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/settings.py
  symbol: data_dir
- name: get_logger
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/settings.py
  symbol: get_logger
- name: session_id_from_env
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/settings.py
  symbol: session_id_from_env
- name: JobStore
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/store.py
  symbol: JobStore
- name: infer_job_type
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: infer_job_type
- name: looks_like_challenge
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: looks_like_challenge
- name: matches_search_term
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: matches_search_term
- name: normalize_token
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: normalize_token
- name: normalize_whitespace
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: normalize_whitespace
- name: prepare_text
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: prepare_text
- name: strip_html
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/lib/text.py
  symbol: strip_html
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/list_jobs.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/review.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/score.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/search.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/set_resume.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/tailor.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/job-ops/scripts/track.py
  symbol: main
- name: generate
  file: src/sevn/data/bundled_skills/core/kokoro-tts/scripts/generate.py
  symbol: generate
- name: list_voices
  file: src/sevn/data/bundled_skills/core/kokoro-tts/scripts/generate.py
  symbol: list_voices
- name: generate_daily
  file: src/sevn/data/bundled_skills/core/last30days/scripts/briefing.py
  symbol: generate_daily
- name: generate_weekly
  file: src/sevn/data/bundled_skills/core/last30days/scripts/briefing.py
  symbol: generate_weekly
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/briefing.py
  symbol: main
- name: show_briefing
  file: src/sevn/data/bundled_skills/core/last30days/scripts/briefing.py
  symbol: show_briefing
- name: build_digest_for_run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/daily_digest.py
  symbol: build_digest_for_run
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/daily_digest.py
  symbol: main
- name: run_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/daily_digest.py
  symbol: run_topic
- name: build_judge_prompt
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: build_judge_prompt
- name: build_parser
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: build_parser
- name: build_ranked_items
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: build_ranked_items
- name: call_gemini_judge
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: call_gemini_judge
- name: create_eval_env
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: create_eval_env
- name: create_worktree
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: create_worktree
- name: extract_gemini_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: extract_gemini_text
- name: get_judgments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: get_judgments
- name: jaccard
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: jaccard
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: main
- name: ndcg_at_k
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: ndcg_at_k
- name: parse_topics_file
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: parse_topics_file
- name: precision_at_k
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: precision_at_k
- name: remove_worktree
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: remove_worktree
- name: resolve_google_judge_api_key
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: resolve_google_judge_api_key
- name: resolve_repo_dir
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: resolve_repo_dir
- name: retention
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: retention
- name: row_best_date
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: row_best_date
- name: row_sources
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: row_sources
- name: run_last30days
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: run_last30days
- name: source_coverage_recall
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: source_coverage_recall
- name: source_sets
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: source_sets
- name: stable_item_key
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: stable_item_key
- name: summarize_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: summarize_topic
- name: write_failure_summary
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: write_failure_summary
- name: write_summary
  file: src/sevn/data/bundled_skills/core/last30days/scripts/evaluate_search_quality.py
  symbol: write_summary
- name: filter_items
  file: src/sevn/data/bundled_skills/core/last30days/scripts/filter_raw.py
  symbol: filter_items
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/filter_raw.py
  symbol: main
- name: parse_raw_items
  file: src/sevn/data/bundled_skills/core/last30days/scripts/filter_raw.py
  symbol: parse_raw_items
- name: build_parser
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: build_parser
- name: comparison_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: comparison_topic
- name: compute_output_path_display
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: compute_output_path_display
- name: compute_save_path_display
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: compute_save_path_display
- name: emit_comparison_output
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: emit_comparison_output
- name: emit_output
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: emit_output
- name: ensure_supported_python
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: ensure_supported_python
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: main
- name: parse_as_of_date_arg
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: parse_as_of_date_arg
- name: parse_competitors_plan
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: parse_competitors_plan
- name: parse_search_flag
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: parse_search_flag
- name: persist_report
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: persist_report
- name: read_synthesis_file
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: read_synthesis_file
- name: register_child_pid
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: register_child_pid
- name: resolve_competitors_args
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: resolve_competitors_args
- name: resolve_requested_sources
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: resolve_requested_sources
- name: save_output
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: save_output
- name: save_rendered_output
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: save_rendered_output
- name: slugify
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: slugify
- name: subrun_kwargs_for
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: subrun_kwargs_for
- name: unregister_child_pid
  file: src/sevn/data/bundled_skills/core/last30days/scripts/last30days.py
  symbol: unregister_child_pid
- name: check_npm_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: check_npm_available
- name: get_bird_status
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: get_bird_status
- name: install_bird
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: install_bird
- name: is_bird_authenticated
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: is_bird_authenticated
- name: is_bird_installed
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: is_bird_installed
- name: parse_bird_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: parse_bird_response
- name: probe_works
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: probe_works
- name: search_handles
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: search_handles
- name: search_mentions
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: search_mentions
- name: search_x
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: search_x
- name: set_credentials
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bird_x.py
  symbol: set_credentials
- name: parse_bluesky_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bluesky.py
  symbol: parse_bluesky_response
- name: search_bluesky
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/bluesky.py
  symbol: search_bluesky
- name: detect_category
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/categories.py
  symbol: detect_category
- name: peer_subs_for
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/categories.py
  symbol: peer_subs_for
- name: extract_brave_cookies_macos
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/chrome_cookies.py
  symbol: extract_brave_cookies_macos
- name: extract_chrome_cookies_macos
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/chrome_cookies.py
  symbol: extract_chrome_cookies_macos
- name: extract_chromium_browser_cookies_macos
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/chrome_cookies.py
  symbol: extract_chromium_browser_cookies_macos
- name: has_cjk
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cjk.py
  symbol: has_cjk
- name: segment
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cjk.py
  symbol: segment
- name: cluster_candidates
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cluster.py
  symbol: cluster_candidates
- name: discover_competitors
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/competitors.py
  symbol: discover_competitors
- name: extract_arc_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_arc_cookies
- name: extract_brave_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_brave_cookies
- name: extract_chrome_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_chrome_cookies
- name: extract_chromium_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_chromium_cookies
- name: extract_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_cookies
- name: extract_cookies_with_source
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_cookies_with_source
- name: extract_edge_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_edge_cookies
- name: extract_firefox_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_firefox_cookies
- name: extract_opera_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_opera_cookies
- name: extract_safari_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_safari_cookies
- name: extract_vivaldi_cookies
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/cookie_extract.py
  symbol: extract_vivaldi_cookies
- name: days_ago
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: days_ago
- name: get_date_confidence
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: get_date_confidence
- name: get_date_range
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: get_date_range
- name: parse_as_of_date
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: parse_as_of_date
- name: parse_date
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: parse_date
- name: recency_score
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: recency_score
- name: timestamp_to_date
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dates.py
  symbol: timestamp_to_date
- name: dedupe_items
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: dedupe_items
- name: get_ngrams
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: get_ngrams
- name: hybrid_similarity
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: hybrid_similarity
- name: item_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: item_text
- name: jaccard_similarity
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: jaccard_similarity
- name: normalize_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: normalize_text
- name: prepared_similarity
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: prepared_similarity
- name: token_jaccard
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/dedupe.py
  symbol: token_jaccard
- name: enrich_source_items
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/digg.py
  symbol: enrich_source_items
- name: enrich_with_top_posts
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/digg.py
  symbol: enrich_with_top_posts
- name: fetch_top_posts
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/digg.py
  symbol: fetch_top_posts
- name: parse_digg_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/digg.py
  symbol: parse_digg_response
- name: search_digg
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/digg.py
  symbol: search_digg
- name: extract_entities
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/entity_extract.py
  symbol: extract_entities
- name: OpenAIAuth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: OpenAIAuth
- name: config_exists
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: config_exists
- name: cookie_extraction_browsers
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: cookie_extraction_browsers
- name: extract_browser_credentials
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: extract_browser_credentials
- name: extract_chatgpt_account_id
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: extract_chatgpt_account_id
- name: get_codex_access_token
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_codex_access_token
- name: get_config
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_config
- name: get_instagram_token
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_instagram_token
- name: get_openai_auth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_openai_auth
- name: get_pinterest_token
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_pinterest_token
- name: get_reddit_source
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_reddit_source
- name: get_tiktok_token
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_tiktok_token
- name: get_x_source
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_x_source
- name: get_x_source_status
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_x_source_status
- name: get_x_source_with_method
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_x_source_with_method
- name: get_xiaohongshu_api_base
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_xiaohongshu_api_base
- name: get_xquik_token
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: get_xquik_token
- name: is_bluesky_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_bluesky_available
- name: is_hackernews_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_hackernews_available
- name: is_instagram_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_instagram_available
- name: is_native_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_native_search
- name: is_pinterest_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_pinterest_available
- name: is_polymarket_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_polymarket_available
- name: is_threads_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_threads_available
- name: is_tiktok_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_tiktok_available
- name: is_tiktok_comments_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_tiktok_comments_available
- name: is_truthsocial_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_truthsocial_available
- name: is_xiaohongshu_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_xiaohongshu_available
- name: is_xquik_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_xquik_available
- name: is_youtube_comments_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_youtube_comments_available
- name: is_youtube_sc_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_youtube_sc_available
- name: is_ytdlp_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: is_ytdlp_available
- name: keyless_web_allowed
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: keyless_web_allowed
- name: load_codex_auth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: load_codex_auth
- name: load_env_file
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: load_env_file
- name: transcription_providers
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/env.py
  symbol: transcription_providers
- name: run_competitor_fanout
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/fanout.py
  symbol: run_competitor_fanout
- name: candidate_key
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/fusion.py
  symbol: candidate_key
- name: weighted_rrf
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/fusion.py
  symbol: weighted_rrf
- name: enrich_candidates_with_stars
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: enrich_candidates_with_stars
- name: enrich_with_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: enrich_with_comments
- name: extract_repo_refs
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: extract_repo_refs
- name: parse_github_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: parse_github_response
- name: resolve_token
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: resolve_token
- name: search_github
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: search_github
- name: search_github_person
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: search_github_person
- name: search_github_project
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/github.py
  symbol: search_github_project
- name: brave_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/grounding.py
  symbol: brave_search
- name: exa_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/grounding.py
  symbol: exa_search
- name: parallel_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/grounding.py
  symbol: parallel_search
- name: serper_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/grounding.py
  symbol: serper_search
- name: web_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/grounding.py
  symbol: web_search
- name: enrich_top_stories
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/hackernews.py
  symbol: enrich_top_stories
- name: parse_hackernews_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/hackernews.py
  symbol: parse_hackernews_response
- name: search_hackernews
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/hackernews.py
  symbol: search_hackernews
- name: SourceHealth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/health.py
  symbol: SourceHealth
- name: probe_command
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/health.py
  symbol: probe_command
- name: analyze
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/hiring_signals.py
  symbol: analyze
- name: infer_company_size
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/hiring_signals.py
  symbol: infer_company_size
- name: render_html
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/html_render.py
  symbol: render_html
- name: render_html_comparison
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/html_render.py
  symbol: render_html_comparison
- name: HTTPError
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: HTTPError
- name: RateLimiter
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: RateLimiter
- name: get
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: get
- name: get_reddit_json
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: get_reddit_json
- name: get_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: get_text
- name: log
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: log
- name: post
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: post
- name: post_raw
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: post_raw
- name: reddit_keyless_get_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: reddit_keyless_get_text
- name: request
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: request
- name: scrapecreators_headers
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/http.py
  symbol: scrapecreators_headers
- name: expand_instagram_queries
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/instagram.py
  symbol: expand_instagram_queries
- name: fetch_captions
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/instagram.py
  symbol: fetch_captions
- name: parse_instagram_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/instagram.py
  symbol: parse_instagram_response
- name: search_and_enrich
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/instagram.py
  symbol: search_and_enrich
- name: search_instagram
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/instagram.py
  symbol: search_instagram
- name: detect_ats
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: detect_ats
- name: extract_jsonld_jobs
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: extract_jsonld_jobs
- name: parse_ashby_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: parse_ashby_response
- name: parse_greenhouse_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: parse_greenhouse_response
- name: parse_lever_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: parse_lever_response
- name: parse_smartrecruiters_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: parse_smartrecruiters_response
- name: parse_workable_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: parse_workable_response
- name: search_ashby_board
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_ashby_board
- name: search_greenhouse_board
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_greenhouse_board
- name: search_jobs
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_jobs
- name: search_jobs_web
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_jobs_web
- name: search_lever_board
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_lever_board
- name: search_smartrecruiters_board
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_smartrecruiters_board
- name: search_workable_board
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/jobs.py
  symbol: search_workable_board
- name: debug
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/log.py
  symbol: debug
- name: source_log
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/log.py
  symbol: source_log
- name: filter_by_date_range
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/normalize.py
  symbol: filter_by_date_range
- name: normalize_source_items
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/normalize.py
  symbol: normalize_source_items
- name: search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/perplexity.py
  symbol: search
- name: parse_pinterest_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/pinterest.py
  symbol: parse_pinterest_response
- name: search_pinterest
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/pinterest.py
  symbol: search_pinterest
- name: available_sources
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/pipeline.py
  symbol: available_sources
- name: diagnose
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/pipeline.py
  symbol: diagnose
- name: normalize_requested_sources
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/pipeline.py
  symbol: normalize_requested_sources
- name: run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/pipeline.py
  symbol: run
- name: detect_language
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/planner.py
  symbol: detect_language
- name: plan_query
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/planner.py
  symbol: plan_query
- name: filter_items_against_keywords
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/polymarket.py
  symbol: filter_items_against_keywords
- name: filter_items_against_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/polymarket.py
  symbol: filter_items_against_topic
- name: parse_polymarket_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/polymarket.py
  symbol: parse_polymarket_response
- name: search_polymarket
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/polymarket.py
  symbol: search_polymarket
- name: check_class_1_trap
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/preflight.py
  symbol: check_class_1_trap
- name: GeminiClient
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: GeminiClient
- name: OpenAIClient
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: OpenAIClient
- name: OpenRouterClient
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: OpenRouterClient
- name: ReasoningClient
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: ReasoningClient
- name: XAIClient
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: XAIClient
- name: extract_gemini_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: extract_gemini_text
- name: extract_json
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: extract_json
- name: extract_openai_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: extract_openai_text
- name: mock_runtime
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: mock_runtime
- name: resolve_runtime
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/providers.py
  symbol: resolve_runtime
- name: compute_quality_score
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/quality_nudge.py
  symbol: compute_quality_score
- name: extract_compound_terms
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/query.py
  symbol: extract_compound_terms
- name: extract_core_subject
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/query.py
  symbol: extract_core_subject
- name: infer_query_intent
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/query.py
  symbol: infer_query_intent
- name: discover_subreddits
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: discover_subreddits
- name: enrich_with_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: enrich_with_comments
- name: expand_reddit_queries
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: expand_reddit_queries
- name: fetch_post_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: fetch_post_comments
- name: parse_reddit_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: parse_reddit_response
- name: search_and_enrich
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: search_and_enrich
- name: search_reddit
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit.py
  symbol: search_reddit
- name: RedditRateLimitError
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: RedditRateLimitError
- name: enrich_reddit_item
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: enrich_reddit_item
- name: enrich_reddit_item_sc
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: enrich_reddit_item_sc
- name: extract_comment_insights
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: extract_comment_insights
- name: extract_reddit_path
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: extract_reddit_path
- name: fetch_thread_data
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: fetch_thread_data
- name: get_top_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: get_top_comments
- name: parse_thread_data
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_enrich.py
  symbol: parse_thread_data
- name: search_and_enrich
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_keyless.py
  symbol: search_and_enrich
- name: fetch_listings
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_listing.py
  symbol: fetch_listings
- name: parse_cards
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_listing.py
  symbol: parse_cards
- name: score_index
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_listing.py
  symbol: score_index
- name: search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_public.py
  symbol: search
- name: search_reddit_public
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_public.py
  symbol: search_reddit_public
- name: search_rss
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_rss.py
  symbol: search_rss
- name: extract_post_ref
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_shreddit.py
  symbol: extract_post_ref
- name: fetch_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_shreddit.py
  symbol: fetch_comments
- name: parse_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/reddit_shreddit.py
  symbol: parse_comments
- name: PreparedQuery
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/relevance.py
  symbol: PreparedQuery
- name: token_overlap_relevance
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/relevance.py
  symbol: token_overlap_relevance
- name: tokenize
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/relevance.py
  symbol: tokenize
- name: collect_html_warnings
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: collect_html_warnings
- name: collect_html_warnings_comparison
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: collect_html_warnings_comparison
- name: render_brief
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_brief
- name: render_compact
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_compact
- name: render_comparison_multi
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_comparison_multi
- name: render_comparison_multi_context
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_comparison_multi_context
- name: render_context
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_context
- name: render_for_html
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_for_html
- name: render_for_html_comparison
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_for_html_comparison
- name: render_full
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/render.py
  symbol: render_full
- name: rerank_candidates
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/rerank.py
  symbol: rerank_candidates
- name: score_fun
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/rerank.py
  symbol: score_fun
- name: auto_resolve
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/resolve.py
  symbol: auto_resolve
- name: canonicalize_github_repos
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/resolve.py
  symbol: canonicalize_github_repos
- name: extract_safari_cookies_macos
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/safari_cookies.py
  symbol: extract_safari_cookies_macos
- name: Candidate
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: Candidate
- name: Cluster
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: Cluster
- name: ProviderRuntime
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: ProviderRuntime
- name: QueryPlan
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: QueryPlan
- name: Report
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: Report
- name: RetrievalBundle
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: RetrievalBundle
- name: SourceItem
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: SourceItem
- name: SubQuery
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: SubQuery
- name: candidate_best_published_at
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: candidate_best_published_at
- name: candidate_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: candidate_from_dict
- name: candidate_primary_item
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: candidate_primary_item
- name: candidate_source_label
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: candidate_source_label
- name: candidate_sources
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: candidate_sources
- name: cluster_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: cluster_from_dict
- name: provider_runtime_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: provider_runtime_from_dict
- name: query_plan_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: query_plan_from_dict
- name: report_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: report_from_dict
- name: source_item_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: source_item_from_dict
- name: subquery_from_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: subquery_from_dict
- name: to_dict
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/schema.py
  symbol: to_dict
- name: fetch_api_key
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: fetch_api_key
- name: get_setup_status_text
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: get_setup_status_text
- name: is_first_run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: is_first_run
- name: poll_device_auth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: poll_device_auth
- name: run_auto_setup
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: run_auto_setup
- name: run_device_auth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: run_device_auth
- name: run_full_device_auth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: run_full_device_auth
- name: run_github_auth
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: run_github_auth
- name: run_openclaw_setup
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: run_openclaw_setup
- name: write_setup_config
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/setup_wizard.py
  symbol: write_setup_config
- name: annotate_stream
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: annotate_stream
- name: engagement_raw
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: engagement_raw
- name: freshness
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: freshness
- name: local_relevance
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: local_relevance
- name: log1p_safe
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: log1p_safe
- name: normalize
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: normalize
- name: normalized_comment_vote
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: normalized_comment_vote
- name: prune_low_relevance
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: prune_low_relevance
- name: source_quality
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: source_quality
- name: top_comment_vote_signal
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/signals.py
  symbol: top_comment_vote_signal
- name: read_skill_version
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/skill_meta.py
  symbol: read_skill_version
- name: extract_best_snippet
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/snippet.py
  symbol: extract_best_snippet
- name: SubprocResult
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/subproc.py
  symbol: SubprocResult
- name: SubprocTimeout
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/subproc.py
  symbol: SubprocTimeout
- name: run_with_timeout
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/subproc.py
  symbol: run_with_timeout
- name: parse_threads_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/threads.py
  symbol: parse_threads_response
- name: search_threads
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/threads.py
  symbol: search_threads
- name: enrich_with_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/tiktok.py
  symbol: enrich_with_comments
- name: expand_tiktok_queries
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/tiktok.py
  symbol: expand_tiktok_queries
- name: fetch_captions
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/tiktok.py
  symbol: fetch_captions
- name: parse_tiktok_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/tiktok.py
  symbol: parse_tiktok_response
- name: search_and_enrich
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/tiktok.py
  symbol: search_and_enrich
- name: search_tiktok
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/tiktok.py
  symbol: search_tiktok
- name: TranscriptResult
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/transcribe.py
  symbol: TranscriptResult
- name: is_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/transcribe.py
  symbol: is_available
- name: transcribe_media
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/transcribe.py
  symbol: transcribe_media
- name: parse_truthsocial_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/truthsocial.py
  symbol: parse_truthsocial_response
- name: search_truthsocial
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/truthsocial.py
  symbol: search_truthsocial
- name: Colors
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/ui.py
  symbol: Colors
- name: ProgressDisplay
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/ui.py
  symbol: ProgressDisplay
- name: Spinner
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/ui.py
  symbol: Spinner
- name: print_phase
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/ui.py
  symbol: print_phase
- name: show_diagnostic_banner
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/ui.py
  symbol: show_diagnostic_banner
- name: KeylessFetchResult
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/web_fetch_keyless.py
  symbol: KeylessFetchResult
- name: fetch_markdown
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/web_fetch_keyless.py
  symbol: fetch_markdown
- name: keyless_search
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/web_search_keyless.py
  symbol: keyless_search
- name: parse_x_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xai_x.py
  symbol: parse_x_response
- name: search_x
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xai_x.py
  symbol: search_x
- name: search_feeds
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xiaohongshu_api.py
  symbol: search_feeds
- name: expand_xquik_queries
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xquik.py
  symbol: expand_xquik_queries
- name: parse_xquik_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xquik.py
  symbol: parse_xquik_response
- name: search_and_enrich
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xquik.py
  symbol: search_and_enrich
- name: search_xquik
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xquik.py
  symbol: search_xquik
- name: is_available
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xurl_x.py
  symbol: is_available
- name: parse_x_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xurl_x.py
  symbol: parse_x_response
- name: search_x
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/xurl_x.py
  symbol: search_x
- name: backfill_transcripts
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: backfill_transcripts
- name: enrich_with_comments
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: enrich_with_comments
- name: expand_youtube_queries
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: expand_youtube_queries
- name: extract_transcript_highlights
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: extract_transcript_highlights
- name: fetch_transcript
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: fetch_transcript
- name: fetch_transcripts_parallel
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: fetch_transcripts_parallel
- name: get_transcript_fetch_stats
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: get_transcript_fetch_stats
- name: is_ytdlp_installed
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: is_ytdlp_installed
- name: parse_youtube_response
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: parse_youtube_response
- name: reset_transcript_fetch_stats
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: reset_transcript_fetch_stats
- name: search_and_transcribe
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: search_and_transcribe
- name: search_youtube
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: search_youtube
- name: search_youtube_sc
  file: src/sevn/data/bundled_skills/core/last30days/scripts/lib/youtube_yt.py
  symbol: search_youtube_sc
- name: build_engine_argv
  file: src/sevn/data/bundled_skills/core/last30days/scripts/research.py
  symbol: build_engine_argv
- name: default_memory_dir
  file: src/sevn/data/bundled_skills/core/last30days/scripts/research.py
  symbol: default_memory_dir
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/research.py
  symbol: main
- name: resolve_python312
  file: src/sevn/data/bundled_skills/core/last30days/scripts/research.py
  symbol: resolve_python312
- name: skill_dir_from_env
  file: src/sevn/data/bundled_skills/core/last30days/scripts/research.py
  symbol: skill_dir_from_env
- name: add_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: add_topic
- name: compute_topic_delta
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: compute_topic_delta
- name: delete_finding
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: delete_finding
- name: dismiss_finding
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: dismiss_finding
- name: finding_from_candidate
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: finding_from_candidate
- name: findings_from_report
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: findings_from_report
- name: get_daily_cost
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_daily_cost
- name: get_findings_new_in_run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_findings_new_in_run
- name: get_latest_completed_runs
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_latest_completed_runs
- name: get_new_findings
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_new_findings
- name: get_setting
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_setting
- name: get_sightings_for_run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_sightings_for_run
- name: get_stats
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_stats
- name: get_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_topic
- name: get_trending
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: get_trending
- name: init_db
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: init_db
- name: list_topics
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: list_topics
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: main
- name: record_run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: record_run
- name: remove_topic
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: remove_topic
- name: search_findings
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: search_findings
- name: set_setting
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: set_setting
- name: store_findings
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: store_findings
- name: update_finding
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: update_finding
- name: update_run
  file: src/sevn/data/bundled_skills/core/last30days/scripts/store.py
  symbol: update_run
- name: build_parser
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: build_parser
- name: cmd_add
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_add
- name: cmd_config
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_config
- name: cmd_delta
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_delta
- name: cmd_list
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_list
- name: cmd_remove
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_remove
- name: cmd_run_all
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_run_all
- name: cmd_run_one
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: cmd_run_one
- name: main
  file: src/sevn/data/bundled_skills/core/last30days/scripts/watchlist.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/conversations_meta.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/describe.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/expand.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/expand_query.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/fetch.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/grep.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/list_conversations.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/search_summaries.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lcm/scripts/status.py
  symbol: main
- name: content_root_from_env
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/_cli.py
  symbol: content_root_from_env
- name: session_id_from_env
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/_cli.py
  symbol: session_id_from_env
- name: main
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/scrape_companies.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/scrape_connections.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/scrape_staff.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/scrape_users.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/linkedin-use/scripts/session_status.py
  symbol: main
- name: cli_output_payload
  file: src/sevn/data/bundled_skills/core/lume/scripts/_common.py
  symbol: cli_output_payload
- name: ensure_lume_ready
  file: src/sevn/data/bundled_skills/core/lume/scripts/_common.py
  symbol: ensure_lume_ready
- name: run_lume_cli
  file: src/sevn/data/bundled_skills/core/lume/scripts/_common.py
  symbol: run_lume_cli
- name: main
  file: src/sevn/data/bundled_skills/core/lume/scripts/ls.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lume/scripts/pull.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lume/scripts/run.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/lume/scripts/stop.py
  symbol: main
- name: content_root_from_env
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: content_root_from_env
- name: main_guard
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: main_guard
- name: run_media_generation
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/_common.py
  symbol: run_media_generation
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_image.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_music.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/media_generation/scripts/generate_video.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/mycode/scripts/scan.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/openwiki/scripts/generate.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/openwiki/scripts/status.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/pdf/scripts/pdf.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/pdf/scripts/pdf_load.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/pdf/scripts/pdf_read.py
  symbol: main
- name: enrich_controls
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_controls.py
  symbol: enrich_controls
- name: score_control
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_controls.py
  symbol: score_control
- name: suggest_selector
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_controls.py
  symbol: suggest_selector
- name: human_click
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_interact.py
  symbol: human_click
- name: human_fill
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_interact.py
  symbol: human_fill
- name: prepare_element
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_interact.py
  symbol: prepare_element
- name: emit_error
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_output.py
  symbol: emit_error
- name: emit_ok
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_output.py
  symbol: emit_ok
- name: main_guard
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_output.py
  symbol: main_guard
- name: playwright_missing
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_output.py
  symbol: playwright_missing
- name: classify_obstacles
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_page_intel.py
  symbol: classify_obstacles
- name: obstacle_signals
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_page_intel.py
  symbol: obstacle_signals
- name: try_click_recaptcha_checkbox
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_page_intel.py
  symbol: try_click_recaptcha_checkbox
- name: try_dismiss_cookie_banners
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_page_intel.py
  symbol: try_dismiss_cookie_banners
- name: add_tab_arg
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: add_tab_arg
- name: browser_session
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: browser_session
- name: cdp_port
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: cdp_port
- name: content_root_from_env
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: content_root_from_env
- name: default_cdp_url
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: default_cdp_url
- name: extract_tab_target_id
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: extract_tab_target_id
- name: session_id_from_env
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: session_id_from_env
- name: tab_session
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: tab_session
- name: wait_for_page_ready
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: wait_for_page_ready
- name: workspace_root
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_pw_session.py
  symbol: workspace_root
- name: add_human_arg
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_timing.py
  symbol: add_human_arg
- name: human_pause
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_timing.py
  symbol: human_pause
- name: human_typing_delay_ms
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/_lib/_timing.py
  symbol: human_typing_delay_ms
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/activate_tab.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/capture.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/cdp_probe.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/click_element.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/close_browser.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/close_tab.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/dismiss_cookies.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/evaluate.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/extract_page_text.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/fill.py
  symbol: main
- name: find_control_on_page
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/find_control.py
  symbol: find_control_on_page
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/find_control.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/find_tab.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/get_html.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/get_text.py
  symbol: main
- name: blob_url_to_raw
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/github_blob_to_raw.py
  symbol: blob_url_to_raw
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/github_blob_to_raw.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/goto.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/handle_blockers.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/hover.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/list_controls.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/list_tabs.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/new_tab.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/page_state.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/press.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/restart_browser.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/screenshot.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/scroll.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/scroll_into_view.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/select_option.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/session_status.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/type_text.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/playwright-browser/scripts/wait_for_selector.py
  symbol: main
- name: resolve_binary
  file: src/sevn/data/bundled_skills/core/printing-press-library/scripts/_pp_cli.py
  symbol: resolve_binary
- name: run_pp_cli
  file: src/sevn/data/bundled_skills/core/printing-press-library/scripts/_pp_cli.py
  symbol: run_pp_cli
- name: main
  file: src/sevn/data/bundled_skills/core/printing-press-library/scripts/espn.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/printing-press-library/scripts/flight_goat.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/printing-press-library/scripts/movie_goat.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/printing-press-library/scripts/recipe_goat.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/roam_code/scripts/query.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/scheduling/scripts/cron_add.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/scheduling/scripts/cron_delete.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/scheduling/scripts/cron_edit.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/scheduling/scripts/cron_list.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/scheduling/scripts/reminder.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/second_brain/scripts/file_back.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/second_brain/scripts/ingest.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/second_brain/scripts/lint.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/history.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/list.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/send.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/sessions.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/spawn.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/status.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/sessions_management/scripts/yield.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/skill_management/scripts/authoring_workflow.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/skill_management/scripts/list_inventory.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/skill_management/scripts/validate.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/telegram/scripts/buttons.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/telegram/scripts/forum_create.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/telegram/scripts/forum_find_group.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/x-use/scripts/search.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/x-use/scripts/session_status.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/x-use/scripts/timeline.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/yt-dlp/scripts/download.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/yt-dlp/scripts/metadata.py
  symbol: main
- name: SkillsStarterMissingError
  file: src/sevn/data/skills_index.py
  symbol: SkillsStarterMissingError
- name: ensure_workspace_index
  file: src/sevn/data/skills_index.py
  symbol: ensure_workspace_index
- name: read_skills_index
  file: src/sevn/data/skills_index.py
  symbol: read_skills_index
- name: DeployHost
  file: src/sevn/deploy/inventory.py
  symbol: DeployHost
- name: DeployInventory
  file: src/sevn/deploy/inventory.py
  symbol: DeployInventory
- name: DeployInventoryError
  file: src/sevn/deploy/inventory.py
  symbol: DeployInventoryError
- name: get_host
  file: src/sevn/deploy/inventory.py
  symbol: get_host
- name: load_inventory
  file: src/sevn/deploy/inventory.py
  symbol: load_inventory
- name: resolve_inventory_path
  file: src/sevn/deploy/inventory.py
  symbol: resolve_inventory_path
- name: DeployMode
  file: src/sevn/deploy/remote.py
  symbol: DeployMode
- name: DeployRunnerError
  file: src/sevn/deploy/remote.py
  symbol: DeployRunnerError
- name: RemoteDeployRunner
  file: src/sevn/deploy/remote.py
  symbol: RemoteDeployRunner
- name: ValidatedBundle
  file: src/sevn/deploy/remote.py
  symbol: ValidatedBundle
- name: validate_bundle
  file: src/sevn/deploy/remote.py
  symbol: validate_bundle
- name: DeployReport
  file: src/sevn/deploy/report.py
  symbol: DeployReport
- name: build_report_dict
  file: src/sevn/deploy/report.py
  symbol: build_report_dict
- name: find_latest_report
  file: src/sevn/deploy/report.py
  symbol: find_latest_report
- name: redact_report_for_display
  file: src/sevn/deploy/report.py
  symbol: redact_report_for_display
- name: write_deploy_report
  file: src/sevn/deploy/report.py
  symbol: write_deploy_report
- name: SSHCommandError
  file: src/sevn/deploy/ssh_runner.py
  symbol: SSHCommandError
- name: SSHResult
  file: src/sevn/deploy/ssh_runner.py
  symbol: SSHResult
- name: SSHRunner
  file: src/sevn/deploy/ssh_runner.py
  symbol: SSHRunner
- name: check_about_docs
  file: src/sevn/docs/about/check.py
  symbol: check_about_docs
- name: compute_doc_fingerprint
  file: src/sevn/docs/about/extract.py
  symbol: compute_doc_fingerprint
- name: extract_fields
  file: src/sevn/docs/about/extract.py
  symbol: extract_fields
- name: generate_body
  file: src/sevn/docs/about/generate.py
  symbol: generate_body
- name: index_path
  file: src/sevn/docs/about/index.py
  symbol: index_path
- name: render_index
  file: src/sevn/docs/about/index.py
  symbol: render_index
- name: dump_doc
  file: src/sevn/docs/about/loader.py
  symbol: dump_doc
- name: load_doc
  file: src/sevn/docs/about/loader.py
  symbol: load_doc
- name: split_frontmatter
  file: src/sevn/docs/about/loader.py
  symbol: split_frontmatter
- name: build_path_to_id_map
  file: src/sevn/docs/about/migrate.py
  symbol: build_path_to_id_map
- name: migrate_all
  file: src/sevn/docs/about/migrate.py
  symbol: migrate_all
- name: parse_legacy_metadata
  file: src/sevn/docs/about/migrate.py
  symbol: parse_legacy_metadata
- name: rewrite_markdown_refs
  file: src/sevn/docs/about/migrate.py
  symbol: rewrite_markdown_refs
- name: summary_from_legacy
  file: src/sevn/docs/about/migrate.py
  symbol: summary_from_legacy
- name: AboutDoc
  file: src/sevn/docs/about/model.py
  symbol: AboutDoc
- name: Interface
  file: src/sevn/docs/about/model.py
  symbol: Interface
- name: export_json_schema
  file: src/sevn/docs/about/model.py
  symbol: export_json_schema
- name: find_violations
  file: src/sevn/docs/about/refs.py
  symbol: find_violations
- name: is_allowed
  file: src/sevn/docs/about/refs.py
  symbol: is_allowed
- name: load_allowlist
  file: src/sevn/docs/about/refs.py
  symbol: load_allowlist
- name: default_manifest_path
  file: src/sevn/docs/about/registry.py
  symbol: default_manifest_path
- name: find_doc_path
  file: src/sevn/docs/about/registry.py
  symbol: find_doc_path
- name: load_manifest_entries
  file: src/sevn/docs/about/registry.py
  symbol: load_manifest_entries
- name: load_root_intro_lines
  file: src/sevn/docs/readme/brand.py
  symbol: load_root_intro_lines
- name: load_root_value_prop
  file: src/sevn/docs/readme/brand.py
  symbol: load_root_value_prop
- name: CatalogRow
  file: src/sevn/docs/readme/catalog.py
  symbol: CatalogRow
- name: build_catalog_rows
  file: src/sevn/docs/readme/catalog.py
  symbol: build_catalog_rows
- name: build_index_rows
  file: src/sevn/docs/readme/catalog.py
  symbol: build_index_rows
- name: build_subsystem_map_rows
  file: src/sevn/docs/readme/catalog.py
  symbol: build_subsystem_map_rows
- name: CheckResult
  file: src/sevn/docs/readme/check.py
  symbol: CheckResult
- name: check_readme_tree
  file: src/sevn/docs/readme/check.py
  symbol: check_readme_tree
- name: CurateResult
  file: src/sevn/docs/readme/curate.py
  symbol: CurateResult
- name: RunnerKind
  file: src/sevn/docs/readme/curate.py
  symbol: RunnerKind
- name: build_prompt
  file: src/sevn/docs/readme/curate.py
  symbol: build_prompt
- name: curate_entry
  file: src/sevn/docs/readme/curate.py
  symbol: curate_entry
- name: diff_for_globs
  file: src/sevn/docs/readme/curate.py
  symbol: diff_for_globs
- name: invoke_runner
  file: src/sevn/docs/readme/curate.py
  symbol: invoke_runner
- name: resolve_runner
  file: src/sevn/docs/readme/curate.py
  symbol: resolve_runner
- name: compute_digest
  file: src/sevn/docs/readme/fingerprint.py
  symbol: compute_digest
- name: default_fingerprints_path
  file: src/sevn/docs/readme/fingerprint.py
  symbol: default_fingerprints_path
- name: expand_source_globs
  file: src/sevn/docs/readme/fingerprint.py
  symbol: expand_source_globs
- name: load_fingerprints
  file: src/sevn/docs/readme/fingerprint.py
  symbol: load_fingerprints
- name: path_matches_source_glob
  file: src/sevn/docs/readme/fingerprint.py
  symbol: path_matches_source_glob
- name: save_fingerprints
  file: src/sevn/docs/readme/fingerprint.py
  symbol: save_fingerprints
- name: slugs_for_changed_paths
  file: src/sevn/docs/readme/fingerprint.py
  symbol: slugs_for_changed_paths
- name: stamp_entry
  file: src/sevn/docs/readme/fingerprint.py
  symbol: stamp_entry
- name: upsert_entry
  file: src/sevn/docs/readme/fingerprint.py
  symbol: upsert_entry
- name: glob_dir_prefix
  file: src/sevn/docs/readme/glob_paths.py
  symbol: glob_dir_prefix
- name: glob_to_pathspec
  file: src/sevn/docs/readme/glob_paths.py
  symbol: glob_to_pathspec
- name: L2ProsePolicy
  file: src/sevn/docs/readme/l2_prose.py
  symbol: L2ProsePolicy
- name: build_level2_how_it_works
  file: src/sevn/docs/readme/l2_prose.py
  symbol: build_level2_how_it_works
- name: build_level3_deep_dive
  file: src/sevn/docs/readme/l3_prose.py
  symbol: build_level3_deep_dive
- name: readme_relative_href
  file: src/sevn/docs/readme/links.py
  symbol: readme_relative_href
- name: validate_markdown_links
  file: src/sevn/docs/readme/links.py
  symbol: validate_markdown_links
- name: ReadmeEntry
  file: src/sevn/docs/readme/manifest.py
  symbol: ReadmeEntry
- name: ReadmeManifest
  file: src/sevn/docs/readme/manifest.py
  symbol: ReadmeManifest
- name: get_entry
  file: src/sevn/docs/readme/manifest.py
  symbol: get_entry
- name: load_manifest
  file: src/sevn/docs/readme/manifest.py
  symbol: load_manifest
- name: ReadmeAssembly
  file: src/sevn/docs/readme/model.py
  symbol: ReadmeAssembly
- name: SectionContent
  file: src/sevn/docs/readme/model.py
  symbol: SectionContent
- name: assemble_template_context
  file: src/sevn/docs/readme/model.py
  symbol: assemble_template_context
- name: format_module_symbols_for_prompt
  file: src/sevn/docs/readme/model.py
  symbol: format_module_symbols_for_prompt
- name: merge_section
  file: src/sevn/docs/readme/model.py
  symbol: merge_section
- name: offline_sections
  file: src/sevn/docs/readme/model.py
  symbol: offline_sections
- name: ModuleIndex
  file: src/sevn/docs/readme/module_index.py
  symbol: ModuleIndex
- name: build_module_indexes
  file: src/sevn/docs/readme/module_index.py
  symbol: build_module_indexes
- name: parse_module_index
  file: src/sevn/docs/readme/module_index.py
  symbol: parse_module_index
- name: build_level1_overview
  file: src/sevn/docs/readme/offline_sections.py
  symbol: build_level1_overview
- name: build_subsystem_summary
  file: src/sevn/docs/readme/offline_sections.py
  symbol: build_subsystem_summary
- name: catalog_items_with_hrefs
  file: src/sevn/docs/readme/offline_sections.py
  symbol: catalog_items_with_hrefs
- name: offline_catalog_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_catalog_sections
- name: offline_freeform_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_freeform_sections
- name: offline_guide_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_guide_sections
- name: offline_index_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_index_sections
- name: offline_modules_catalog_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_modules_catalog_sections
- name: offline_root_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_root_sections
- name: offline_skills_catalog_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_skills_catalog_sections
- name: offline_subsystem_sections
  file: src/sevn/docs/readme/offline_sections.py
  symbol: offline_subsystem_sections
- name: ProfileSchema
  file: src/sevn/docs/readme/profile_schemas.py
  symbol: ProfileSchema
- name: get_profile_schema
  file: src/sevn/docs/readme/profile_schemas.py
  symbol: get_profile_schema
- name: module_docstring_prose
  file: src/sevn/docs/readme/prose.py
  symbol: module_docstring_prose
- name: rewrite_design_doc_refs
  file: src/sevn/docs/readme/prose.py
  symbol: rewrite_design_doc_refs
- name: strip_inline_code
  file: src/sevn/docs/readme/prose.py
  symbol: strip_inline_code
- name: LlmProvider
  file: src/sevn/docs/readme/providers.py
  symbol: LlmProvider
- name: OfflineProvider
  file: src/sevn/docs/readme/providers.py
  symbol: OfflineProvider
- name: ReadmeProviderConfig
  file: src/sevn/docs/readme/providers.py
  symbol: ReadmeProviderConfig
- name: SectionProvider
  file: src/sevn/docs/readme/providers.py
  symbol: SectionProvider
- name: build_provider
  file: src/sevn/docs/readme/providers.py
  symbol: build_provider
- name: jinja_env
  file: src/sevn/docs/readme/render.py
  symbol: jinja_env
- name: render_all_fixtures
  file: src/sevn/docs/readme/render.py
  symbol: render_all_fixtures
- name: render_manifest_slug
  file: src/sevn/docs/readme/render.py
  symbol: render_manifest_slug
- name: render_profile
  file: src/sevn/docs/readme/render.py
  symbol: render_profile
- name: render_readme_markdown
  file: src/sevn/docs/readme/render.py
  symbol: render_readme_markdown
- name: validate_rendered_markdown
  file: src/sevn/docs/readme/render.py
  symbol: validate_rendered_markdown
- name: write_readme
  file: src/sevn/docs/readme/render.py
  symbol: write_readme
- name: scaffold_readme_tree
  file: src/sevn/docs/readme/scaffold.py
  symbol: scaffold_readme_tree
- name: ScanContext
  file: src/sevn/docs/readme/scan_context.py
  symbol: ScanContext
- name: extract_module_symbols
  file: src/sevn/docs/readme/scanner.py
  symbol: extract_module_symbols
- name: resolve_spec_path
  file: src/sevn/docs/readme/scanner.py
  symbol: resolve_spec_path
- name: scan_repo_context
  file: src/sevn/docs/readme/scanner.py
  symbol: scan_repo_context
- name: symbol_lineno_for_module
  file: src/sevn/docs/readme/scanner.py
  symbol: symbol_lineno_for_module
- name: ReadmePipelineSettings
  file: src/sevn/docs/readme/settings.py
  symbol: ReadmePipelineSettings
- name: default_offline_mode
  file: src/sevn/docs/readme/settings.py
  symbol: default_offline_mode
- name: provider_config_from_settings
  file: src/sevn/docs/readme/settings.py
  symbol: provider_config_from_settings
- name: resolve_readme_settings
  file: src/sevn/docs/readme/settings.py
  symbol: resolve_readme_settings
- name: callable_name_in_file
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: callable_name_in_file
- name: extract_curated_prose_section
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: extract_curated_prose_section
- name: extract_level3_section
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: extract_level3_section
- name: function_defined_in_file
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: function_defined_in_file
- name: symbol_defined_in_file
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: symbol_defined_in_file
- name: validate_path_refs
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: validate_path_refs
- name: validate_symbol_refs
  file: src/sevn/docs/readme/symbol_refs.py
  symbol: validate_symbol_refs
- name: SymbolRecord
  file: src/sevn/docs/readme/symbols.py
  symbol: SymbolRecord
- name: symbol_names
  file: src/sevn/docs/readme/symbols.py
  symbol: symbol_names
- name: Heading
  file: src/sevn/docs/readme/templates.py
  symbol: Heading
- name: TemplateError
  file: src/sevn/docs/readme/templates.py
  symbol: TemplateError
- name: load_template_headings
  file: src/sevn/docs/readme/templates.py
  symbol: load_template_headings
- name: resolve_template_path
  file: src/sevn/docs/readme/templates.py
  symbol: resolve_template_path
- name: validate_against_template
  file: src/sevn/docs/readme/templates.py
  symbol: validate_against_template
- name: first_sentence
  file: src/sevn/docs/readme/text_utils.py
  symbol: first_sentence
- name: format_path_list
  file: src/sevn/docs/readme/text_utils.py
  symbol: format_path_list
- name: role_from_summary
  file: src/sevn/docs/readme/text_utils.py
  symbol: role_from_summary
- name: truncate_at_sentence
  file: src/sevn/docs/readme/text_utils.py
  symbol: truncate_at_sentence
- name: SummaryLintFinding
  file: src/sevn/docs/readme/verify.py
  symbol: SummaryLintFinding
- name: lint_summaries
  file: src/sevn/docs/readme/verify.py
  symbol: lint_summaries
- name: EvolutionApproval
  file: src/sevn/evolution/approvals.py
  symbol: EvolutionApproval
- name: approval_to_api_dict
  file: src/sevn/evolution/approvals.py
  symbol: approval_to_api_dict
- name: approvals_dir
  file: src/sevn/evolution/approvals.py
  symbol: approvals_dir
- name: create_approval
  file: src/sevn/evolution/approvals.py
  symbol: create_approval
- name: ensure_issue_approval
  file: src/sevn/evolution/approvals.py
  symbol: ensure_issue_approval
- name: get_approval
  file: src/sevn/evolution/approvals.py
  symbol: get_approval
- name: list_approvals
  file: src/sevn/evolution/approvals.py
  symbol: list_approvals
- name: resolve_approval
  file: src/sevn/evolution/approvals.py
  symbol: resolve_approval
- name: save_approval
  file: src/sevn/evolution/approvals.py
  symbol: save_approval
- name: run_bug_pipeline
  file: src/sevn/evolution/bug_pipeline.py
  symbol: run_bug_pipeline
- name: CursorPollScheduler
  file: src/sevn/evolution/cursor_poll_scheduler.py
  symbol: CursorPollScheduler
- name: EvolutionIssueEventFanoutFn
  file: src/sevn/evolution/events.py
  symbol: EvolutionIssueEventFanoutFn
- name: EvolutionIssueEventPayload
  file: src/sevn/evolution/events.py
  symbol: EvolutionIssueEventPayload
- name: evolution_issue_ws_topic
  file: src/sevn/evolution/events.py
  symbol: evolution_issue_ws_topic
- name: maybe_publish_issue_event
  file: src/sevn/evolution/events.py
  symbol: maybe_publish_issue_event
- name: dispatch_local_implement
  file: src/sevn/evolution/executors/local.py
  symbol: dispatch_local_implement
- name: FeaturePipelineBlockedError
  file: src/sevn/evolution/feature_pipeline.py
  symbol: FeaturePipelineBlockedError
- name: feature_artefacts_dir
  file: src/sevn/evolution/feature_pipeline.py
  symbol: feature_artefacts_dir
- name: record_pipeline_approval
  file: src/sevn/evolution/feature_pipeline.py
  symbol: record_pipeline_approval
- name: run_feature_pipeline
  file: src/sevn/evolution/feature_pipeline.py
  symbol: run_feature_pipeline
- name: SyncResult
  file: src/sevn/evolution/github_sync.py
  symbol: SyncResult
- name: import_github_issue
  file: src/sevn/evolution/github_sync.py
  symbol: import_github_issue
- name: import_github_issue_with_created
  file: src/sevn/evolution/github_sync.py
  symbol: import_github_issue_with_created
- name: sync_github_issues
  file: src/sevn/evolution/github_sync.py
  symbol: sync_github_issues
- name: EvolutionIssue
  file: src/sevn/evolution/issues.py
  symbol: EvolutionIssue
- name: create_issue
  file: src/sevn/evolution/issues.py
  symbol: create_issue
- name: get_issue
  file: src/sevn/evolution/issues.py
  symbol: get_issue
- name: issue_to_api_dict
  file: src/sevn/evolution/issues.py
  symbol: issue_to_api_dict
- name: issues_dir
  file: src/sevn/evolution/issues.py
  symbol: issues_dir
- name: list_issues
  file: src/sevn/evolution/issues.py
  symbol: list_issues
- name: maybe_mirror_issue_to_github
  file: src/sevn/evolution/issues.py
  symbol: maybe_mirror_issue_to_github
- name: my_sevn_repo_slug
  file: src/sevn/evolution/issues.py
  symbol: my_sevn_repo_slug
- name: save_issue
  file: src/sevn/evolution/issues.py
  symbol: save_issue
- name: utc_now_iso
  file: src/sevn/evolution/issues.py
  symbol: utc_now_iso
- name: maybe_auto_run_pipeline_after_import
  file: src/sevn/evolution/pipeline_autostart.py
  symbol: maybe_auto_run_pipeline_after_import
- name: PipelineBlockedError
  file: src/sevn/evolution/pipeline_common.py
  symbol: PipelineBlockedError
- name: publish_transition
  file: src/sevn/evolution/pipeline_common.py
  symbol: publish_transition
- name: set_issue_stage
  file: src/sevn/evolution/pipeline_common.py
  symbol: set_issue_stage
- name: run_pipeline
  file: src/sevn/evolution/pipeline_runner.py
  symbol: run_pipeline
- name: PipelineStageRow
  file: src/sevn/evolution/pipelines.py
  symbol: PipelineStageRow
- name: append_pipeline_log
  file: src/sevn/evolution/pipelines.py
  symbol: append_pipeline_log
- name: get_pipeline_detail
  file: src/sevn/evolution/pipelines.py
  symbol: get_pipeline_detail
- name: issue_to_pipeline_dict
  file: src/sevn/evolution/pipelines.py
  symbol: issue_to_pipeline_dict
- name: kill_pipeline
  file: src/sevn/evolution/pipelines.py
  symbol: kill_pipeline
- name: list_active_pipelines
  file: src/sevn/evolution/pipelines.py
  symbol: list_active_pipelines
- name: pipeline_logs_path
  file: src/sevn/evolution/pipelines.py
  symbol: pipeline_logs_path
- name: PromotionError
  file: src/sevn/evolution/promotion.py
  symbol: PromotionError
- name: promote_issue
  file: src/sevn/evolution/promotion.py
  symbol: promote_issue
- name: reconcile_my_sevn_issues_sync_cron_job
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: reconcile_my_sevn_issues_sync_cron_job
- name: reconcile_my_sevn_sync_cron_job
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: reconcile_my_sevn_sync_cron_job
- name: run_scheduled_issues_sync
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: run_scheduled_issues_sync
- name: run_scheduled_repo_sync
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: run_scheduled_repo_sync
- name: ExecutorBlockedError
  file: src/sevn/evolution/router.py
  symbol: ExecutorBlockedError
- name: build_cursor_cloud_prompt
  file: src/sevn/evolution/router.py
  symbol: build_cursor_cloud_prompt
- name: dispatch_cursor_cloud_implement
  file: src/sevn/evolution/router.py
  symbol: dispatch_cursor_cloud_implement
- name: launch_cursor_cloud_for_issue
  file: src/sevn/evolution/router.py
  symbol: launch_cursor_cloud_for_issue
- name: poll_cursor_cloud_for_issue
  file: src/sevn/evolution/router.py
  symbol: poll_cursor_cloud_for_issue
- name: resolve_executor
  file: src/sevn/evolution/router.py
  symbol: resolve_executor
- name: resolve_target_repo_url
  file: src/sevn/evolution/router.py
  symbol: resolve_target_repo_url
- name: ConstitutionPayload
  file: src/sevn/evolution/spec_kit.py
  symbol: ConstitutionPayload
- name: SpecKitRunResult
  file: src/sevn/evolution/spec_kit.py
  symbol: SpecKitRunResult
- name: constitution_template_text
  file: src/sevn/evolution/spec_kit.py
  symbol: constitution_template_text
- name: load_constitution
  file: src/sevn/evolution/spec_kit.py
  symbol: load_constitution
- name: load_spec_kit_options
  file: src/sevn/evolution/spec_kit.py
  symbol: load_spec_kit_options
- name: run_specify_allowlisted
  file: src/sevn/evolution/spec_kit.py
  symbol: run_specify_allowlisted
- name: save_constitution
  file: src/sevn/evolution/spec_kit.py
  symbol: save_constitution
- name: save_spec_kit_options
  file: src/sevn/evolution/spec_kit.py
  symbol: save_spec_kit_options
- name: SpecKitRunRecord
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: SpecKitRunRecord
- name: append_spec_kit_run
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: append_spec_kit_run
- name: list_spec_kit_runs
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: list_spec_kit_runs
- name: new_run_id
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: new_run_id
- name: utc_now_iso
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: utc_now_iso
- name: compute_evolution_stats
  file: src/sevn/evolution/stats.py
  symbol: compute_evolution_stats
- name: last_sync_path
  file: src/sevn/evolution/stats.py
  symbol: last_sync_path
- name: load_last_sync_record
  file: src/sevn/evolution/stats.py
  symbol: load_last_sync_record
- name: record_last_sync
  file: src/sevn/evolution/stats.py
  symbol: record_last_sync
- name: CiSmokeResult
  file: src/sevn/evolution/worktree.py
  symbol: CiSmokeResult
- name: WorktreeError
  file: src/sevn/evolution/worktree.py
  symbol: WorktreeError
- name: WorktreeLease
  file: src/sevn/evolution/worktree.py
  symbol: WorktreeLease
- name: allocate_worktree
  file: src/sevn/evolution/worktree.py
  symbol: allocate_worktree
- name: code_worktrees_dir
  file: src/sevn/evolution/worktree.py
  symbol: code_worktrees_dir
- name: load_worktree_lease
  file: src/sevn/evolution/worktree.py
  symbol: load_worktree_lease
- name: promote_worktree
  file: src/sevn/evolution/worktree.py
  symbol: promote_worktree
- name: release_worktree
  file: src/sevn/evolution/worktree.py
  symbol: release_worktree
- name: run_ci_smoke
  file: src/sevn/evolution/worktree.py
  symbol: run_ci_smoke
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
- name: resolve_config_ref
  file: src/sevn/gateway/gateway_token.py
  symbol: resolve_config_ref
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
- name: subagent_menu_snapshot_from_router
  file: src/sevn/gateway/menu.py
  symbol: subagent_menu_snapshot_from_router
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
- name: fetch_subagents_mission_payload
  file: src/sevn/gateway/mission_api.py
  symbol: fetch_subagents_mission_payload
- name: kill_all_subagents_mission
  file: src/sevn/gateway/mission_api.py
  symbol: kill_all_subagents_mission
- name: kill_subagent_mission
  file: src/sevn/gateway/mission_api.py
  symbol: kill_subagent_mission
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
- name: build_subagents_mission_snapshot
  file: src/sevn/gateway/mission_subagents_snapshot.py
  symbol: build_subagents_mission_snapshot
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
- name: MultiDispatchHooks
  file: src/sevn/gateway/queue_multi.py
  symbol: MultiDispatchHooks
- name: MultiSpawnOutcome
  file: src/sevn/gateway/queue_multi.py
  symbol: MultiSpawnOutcome
- name: in_flight_task_summary_for_session
  file: src/sevn/gateway/queue_multi.py
  symbol: in_flight_task_summary_for_session
- name: spawn_multi_l1_via_supervisor
  file: src/sevn/gateway/queue_multi.py
  symbol: spawn_multi_l1_via_supervisor
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
- name: format_subagent_tag
  file: src/sevn/gateway/routing_footer.py
  symbol: format_subagent_tag
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
- name: build_announce_back_hook
  file: src/sevn/gateway/subagents_announce.py
  symbol: build_announce_back_hook
- name: register_subagents_boot_hook
  file: src/sevn/gateway/subagents_boot.py
  symbol: register_subagents_boot_hook
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
- name: CloudflareApiError
  file: src/sevn/infrastructure/cloudflare_tunnel_api.py
  symbol: CloudflareApiError
- name: CloudflareTunnelProvisionResult
  file: src/sevn/infrastructure/cloudflare_tunnel_api.py
  symbol: CloudflareTunnelProvisionResult
- name: dns_record_name_for_zone
  file: src/sevn/infrastructure/cloudflare_tunnel_api.py
  symbol: dns_record_name_for_zone
- name: normalize_public_hostname
  file: src/sevn/infrastructure/cloudflare_tunnel_api.py
  symbol: normalize_public_hostname
- name: provision_cloudflare_tunnel
  file: src/sevn/infrastructure/cloudflare_tunnel_api.py
  symbol: provision_cloudflare_tunnel
- name: tunnel_mission_control_url
  file: src/sevn/infrastructure/cloudflare_tunnel_api.py
  symbol: tunnel_mission_control_url
- name: ensure_cloudflared_binary
  file: src/sevn/infrastructure/cloudflared_provision.py
  symbol: ensure_cloudflared_binary
- name: parse_cloudflared_tunnel_input
  file: src/sevn/infrastructure/cloudflared_provision.py
  symbol: parse_cloudflared_tunnel_input
- name: extract_quick_tunnel_url
  file: src/sevn/infrastructure/cloudflared_quick_tunnel.py
  symbol: extract_quick_tunnel_url
- name: read_quick_tunnel_url
  file: src/sevn/infrastructure/cloudflared_quick_tunnel.py
  symbol: read_quick_tunnel_url
- name: TunnelModeSpec
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: TunnelModeSpec
- name: build_tunnel_launch
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: build_tunnel_launch
- name: build_tunnel_stop
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: build_tunnel_stop
- name: coerce_tunnel_local_port
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: coerce_tunnel_local_port
- name: install_hint_for_binary
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: install_hint_for_binary
- name: is_tailscale_mode
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: is_tailscale_mode
- name: normalize_tunnel_mode
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: normalize_tunnel_mode
- name: prepare_tunnel_runtime_cfg
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: prepare_tunnel_runtime_cfg
- name: runtime_secret_fields
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: runtime_secret_fields
- name: secret_binding
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: secret_binding
- name: stale_setup_fields
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: stale_setup_fields
- name: tunnel_binary
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: tunnel_binary
- name: tunnel_cfg_from_disk
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: tunnel_cfg_from_disk
- name: tunnel_cfg_from_raw
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: tunnel_cfg_from_raw
- name: tunnel_cfg_from_workspace
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: tunnel_cfg_from_workspace
- name: tunnel_mode_spec
  file: src/sevn/infrastructure/tunnel_config.py
  symbol: tunnel_mode_spec
- name: TunnelManager
  file: src/sevn/infrastructure/tunnel_manager.py
  symbol: TunnelManager
- name: TunnelStatus
  file: src/sevn/infrastructure/tunnel_manager.py
  symbol: TunnelStatus
- name: tunnel_pid_file
  file: src/sevn/infrastructure/tunnel_manager.py
  symbol: tunnel_pid_file
- name: artifact_download_url
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: artifact_download_url
- name: create_cloud_agent
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: create_cloud_agent
- name: get_agent
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: get_agent
- name: get_run
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: get_run
- name: list_artifacts
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: list_artifacts
- name: parse_mcp_servers_json
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: parse_mcp_servers_json
- name: parse_subagents_json
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: parse_subagents_json
- name: refresh_job_status
  file: src/sevn/integrations/cursor_cloud/client.py
  symbol: refresh_job_status
- name: CursorCloudSettings
  file: src/sevn/integrations/cursor_cloud/config.py
  symbol: CursorCloudSettings
- name: load_cursor_cloud_settings
  file: src/sevn/integrations/cursor_cloud/config.py
  symbol: load_cursor_cloud_settings
- name: CursorCloudJob
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: CursorCloudJob
- name: get_job
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: get_job
- name: insert_job
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: insert_job
- name: list_workspace_jobs
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: list_workspace_jobs
- name: update_job
  file: src/sevn/integrations/cursor_cloud/jobs.py
  symbol: update_job
- name: github_integration_call
  file: src/sevn/integrations/github_skill/client.py
  symbol: github_integration_call
- name: github_integration_call_sync
  file: src/sevn/integrations/github_skill/client.py
  symbol: github_integration_call_sync
- name: github_legacy_call
  file: src/sevn/integrations/github_skill/client.py
  symbol: github_legacy_call
- name: parse_github_repo
  file: src/sevn/integrations/github_skill/client.py
  symbol: parse_github_repo
- name: comment_on_issue
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: comment_on_issue
- name: create_issue
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: create_issue
- name: list_issues
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: list_issues
- name: view_issue
  file: src/sevn/integrations/github_skill/gh_issues.py
  symbol: view_issue
- name: close_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: close_pull_request
- name: create_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: create_pull_request
- name: list_pull_requests
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: list_pull_requests
- name: merge_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: merge_pull_request
- name: update_pull_request_reviewers
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: update_pull_request_reviewers
- name: view_pull_request
  file: src/sevn/integrations/github_skill/gh_pr.py
  symbol: view_pull_request
- name: create_branch
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: create_branch
- name: create_deployment
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: create_deployment
- name: delete_branch
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: delete_branch
- name: dispatch_workflow
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: dispatch_workflow
- name: list_branches
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_branches
- name: list_environments
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_environments
- name: list_repo_secrets
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_repo_secrets
- name: list_repo_variables
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_repo_variables
- name: list_workflows
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: list_workflows
- name: upsert_environment
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: upsert_environment
- name: upsert_repo_secret
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: upsert_repo_secret
- name: upsert_repo_variable
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: upsert_repo_variable
- name: workflow_run_logs
  file: src/sevn/integrations/github_skill/github_manager.py
  symbol: workflow_run_logs
- name: GithubSkillHooks
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: GithubSkillHooks
- name: integration_call_from_mapping
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: integration_call_from_mapping
- name: proxy_github_integration_call
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: proxy_github_integration_call
- name: resolve_github_skill_hooks
  file: src/sevn/integrations/github_skill/hooks.py
  symbol: resolve_github_skill_hooks
- name: LitellmLapClient
  file: src/sevn/integrations/litellm_lap/client.py
  symbol: LitellmLapClient
- name: integration_post_async
  file: src/sevn/integrations/proxy_client.py
  symbol: integration_post_async
- name: integration_post_sync
  file: src/sevn/integrations/proxy_client.py
  symbol: integration_post_sync
- name: AssembledContext
  file: src/sevn/lcm/assembler.py
  symbol: AssembledContext
- name: LcmAssembler
  file: src/sevn/lcm/assembler.py
  symbol: LcmAssembler
- name: CompactionResult
  file: src/sevn/lcm/compaction.py
  symbol: CompactionResult
- name: CompactionScheduler
  file: src/sevn/lcm/compaction.py
  symbol: CompactionScheduler
- name: completion_text
  file: src/sevn/lcm/compaction.py
  symbol: completion_text
- name: InboundLcmMessage
  file: src/sevn/lcm/engine.py
  symbol: InboundLcmMessage
- name: LcmEngine
  file: src/sevn/lcm/engine.py
  symbol: LcmEngine
- name: SessionSummaryHit
  file: src/sevn/lcm/engine.py
  symbol: SessionSummaryHit
- name: SessionView
  file: src/sevn/lcm/engine.py
  symbol: SessionView
- name: FlushDecodeOutcome
  file: src/sevn/lcm/flush.py
  symbol: FlushDecodeOutcome
- name: MemoryWrite
  file: src/sevn/lcm/flush.py
  symbol: MemoryWrite
- name: MemoryWrites
  file: src/sevn/lcm/flush.py
  symbol: MemoryWrites
- name: is_allowlisted_relative_path
  file: src/sevn/lcm/flush.py
  symbol: is_allowlisted_relative_path
- name: run_flush_decode_with_retry_once
  file: src/sevn/lcm/flush.py
  symbol: run_flush_decode_with_retry_once
- name: validate_memory_writes
  file: src/sevn/lcm/flush.py
  symbol: validate_memory_writes
- name: LargeFileSpill
  file: src/sevn/lcm/large_files.py
  symbol: LargeFileSpill
- name: maybe_spill_large_payload
  file: src/sevn/lcm/large_files.py
  symbol: maybe_spill_large_payload
- name: conversation_ids_for_scope
  file: src/sevn/lcm/query.py
  symbol: conversation_ids_for_scope
- name: conversations_meta
  file: src/sevn/lcm/query.py
  symbol: conversations_meta
- name: describe_item
  file: src/sevn/lcm/query.py
  symbol: describe_item
- name: expand_query
  file: src/sevn/lcm/query.py
  symbol: expand_query
- name: expand_summary
  file: src/sevn/lcm/query.py
  symbol: expand_summary
- name: fetch_message
  file: src/sevn/lcm/query.py
  symbol: fetch_message
- name: fetch_recent_messages
  file: src/sevn/lcm/query.py
  symbol: fetch_recent_messages
- name: grep_messages
  file: src/sevn/lcm/query.py
  symbol: grep_messages
- name: list_conversations
  file: src/sevn/lcm/query.py
  symbol: list_conversations
- name: resolve_conversation_id
  file: src/sevn/lcm/query.py
  symbol: resolve_conversation_id
- name: search_summaries_scoped
  file: src/sevn/lcm/query.py
  symbol: search_summaries_scoped
- name: cap_script_row_limit
  file: src/sevn/lcm/script_cli.py
  symbol: cap_script_row_limit
- name: open_workspace_db
  file: src/sevn/lcm/script_cli.py
  symbol: open_workspace_db
- name: session_key_from
  file: src/sevn/lcm/script_cli.py
  symbol: session_key_from
- name: workspace_from_env
  file: src/sevn/lcm/script_cli.py
  symbol: workspace_from_env
- name: write_error
  file: src/sevn/lcm/script_cli.py
  symbol: write_error
- name: write_ok
  file: src/sevn/lcm/script_cli.py
  symbol: write_ok
- name: search_session_summaries
  file: src/sevn/lcm/search.py
  symbol: search_session_summaries
- name: InterceptHandler
  file: src/sevn/logging/bridge.py
  symbol: InterceptHandler
- name: configure_intercept_logging
  file: src/sevn/logging/bridge.py
  symbol: configure_intercept_logging
- name: get_message_id
  file: src/sevn/logging/context.py
  symbol: get_message_id
- name: inject_message_id
  file: src/sevn/logging/context.py
  symbol: inject_message_id
- name: set_message_id
  file: src/sevn/logging/context.py
  symbol: set_message_id
- name: redact_log_line
  file: src/sevn/logging/log_redact.py
  symbol: redact_log_line
- name: ServiceLogSweepResult
  file: src/sevn/logging/retention.py
  symbol: ServiceLogSweepResult
- name: archive_rotated_log
  file: src/sevn/logging/retention.py
  symbol: archive_rotated_log
- name: effective_logging_config
  file: src/sevn/logging/retention.py
  symbol: effective_logging_config
- name: iter_expired_rotated_logs
  file: src/sevn/logging/retention.py
  symbol: iter_expired_rotated_logs
- name: sweep_rotated_service_logs
  file: src/sevn/logging/retention.py
  symbol: sweep_rotated_service_logs
- name: boot_service_logging
  file: src/sevn/logging/setup.py
  symbol: boot_service_logging
- name: maybe_boot_service_logging
  file: src/sevn/logging/setup.py
  symbol: maybe_boot_service_logging
- name: resolve_service_log_format
  file: src/sevn/logging/setup.py
  symbol: resolve_service_log_format
- name: resolve_service_log_timezone
  file: src/sevn/logging/setup.py
  symbol: resolve_service_log_timezone
- name: rotate_active_log_on_restart
  file: src/sevn/logging/setup.py
  symbol: rotate_active_log_on_restart
- name: setup_service_logging
  file: src/sevn/logging/setup.py
  symbol: setup_service_logging
- name: debug_event
  file: src/sevn/logging/structured.py
  symbol: debug_event
- name: preview
  file: src/sevn/logging/structured.py
  symbol: preview
- name: build_download_argv
  file: src/sevn/media/yt_dlp_skill.py
  symbol: build_download_argv
- name: build_metadata_argv
  file: src/sevn/media/yt_dlp_skill.py
  symbol: build_metadata_argv
- name: dry_run_requested
  file: src/sevn/media/yt_dlp_skill.py
  symbol: dry_run_requested
- name: host_allowed
  file: src/sevn/media/yt_dlp_skill.py
  symbol: host_allowed
- name: resolve_path_under_workspace
  file: src/sevn/media/yt_dlp_skill.py
  symbol: resolve_path_under_workspace
- name: run_yt_dlp
  file: src/sevn/media/yt_dlp_skill.py
  symbol: run_yt_dlp
- name: validate_media_url
  file: src/sevn/media/yt_dlp_skill.py
  symbol: validate_media_url
- name: yt_dlp_available
  file: src/sevn/media/yt_dlp_skill.py
  symbol: yt_dlp_available
- name: yt_dlp_missing_message
  file: src/sevn/media/yt_dlp_skill.py
  symbol: yt_dlp_missing_message
- name: format_ack_required_trace_attrs
  file: src/sevn/memory/dreaming/ack_policy.py
  symbol: format_ack_required_trace_attrs
- name: iter_backfill_dates
  file: src/sevn/memory/dreaming/backfill.py
  symbol: iter_backfill_dates
- name: DreamingEngine
  file: src/sevn/memory/dreaming/engine.py
  symbol: DreamingEngine
- name: content_has_llmignore_provenance
  file: src/sevn/memory/dreaming/filters.py
  symbol: content_has_llmignore_provenance
- name: lcm_channel_allows_dreaming
  file: src/sevn/memory/dreaming/filters.py
  symbol: lcm_channel_allows_dreaming
- name: session_allows_dreaming
  file: src/sevn/memory/dreaming/filters.py
  symbol: session_allows_dreaming
- name: DreamingCandidate
  file: src/sevn/memory/dreaming/models.py
  symbol: DreamingCandidate
- name: DreamingRunResult
  file: src/sevn/memory/dreaming/models.py
  symbol: DreamingRunResult
- name: MemoryMdAnchor
  file: src/sevn/memory/dreaming/models.py
  symbol: MemoryMdAnchor
- name: PromotedBatchManifest
  file: src/sevn/memory/dreaming/models.py
  symbol: PromotedBatchManifest
- name: PromotedManifestRow
  file: src/sevn/memory/dreaming/models.py
  symbol: PromotedManifestRow
- name: append_dreams_diary
  file: src/sevn/memory/dreaming/promoter.py
  symbol: append_dreams_diary
- name: build_run_result
  file: src/sevn/memory/dreaming/promoter.py
  symbol: build_run_result
- name: dreams_dir
  file: src/sevn/memory/dreaming/promoter.py
  symbol: dreams_dir
- name: ensure_tree
  file: src/sevn/memory/dreaming/promoter.py
  symbol: ensure_tree
- name: promote_auto_batch
  file: src/sevn/memory/dreaming/promoter.py
  symbol: promote_auto_batch
- name: render_memory_lines
  file: src/sevn/memory/dreaming/promoter.py
  symbol: render_memory_lines
- name: write_candidate_snapshot
  file: src/sevn/memory/dreaming/promoter.py
  symbol: write_candidate_snapshot
- name: write_pending_files
  file: src/sevn/memory/dreaming/promoter.py
  symbol: write_pending_files
- name: format_run_summary
  file: src/sevn/memory/dreaming/review.py
  symbol: format_run_summary
- name: latest_promoted_manifest
  file: src/sevn/memory/dreaming/rollback.py
  symbol: latest_promoted_manifest
- name: rollback_last_auto_batch
  file: src/sevn/memory/dreaming/rollback.py
  symbol: rollback_last_auto_batch
- name: rollback_manifest
  file: src/sevn/memory/dreaming/rollback.py
  symbol: rollback_manifest
- name: effective_dreaming
  file: src/sevn/memory/dreaming/scheduler.py
  symbol: effective_dreaming
- name: reconcile_dreaming_cron_job
  file: src/sevn/memory/dreaming/scheduler.py
  symbol: reconcile_dreaming_cron_job
- name: build_candidates
  file: src/sevn/memory/dreaming/scorer.py
  symbol: build_candidates
- name: maybe_llm_rerank
  file: src/sevn/memory/dreaming/scorer.py
  symbol: maybe_llm_rerank
- name: RawMemorySignal
  file: src/sevn/memory/dreaming/sources.py
  symbol: RawMemorySignal
- name: load_daily_log_signals
  file: src/sevn/memory/dreaming/sources.py
  symbol: load_daily_log_signals
- name: load_lcm_summary_signals
  file: src/sevn/memory/dreaming/sources.py
  symbol: load_lcm_summary_signals
- name: load_memory_signals
  file: src/sevn/memory/dreaming/sources.py
  symbol: load_memory_signals
- name: load_recall_weights
  file: src/sevn/memory/search_telemetry.py
  symbol: load_recall_weights
- name: record_memory_recall_signal
  file: src/sevn/memory/search_telemetry.py
  symbol: record_memory_recall_signal
- name: record_memory_search_event
  file: src/sevn/memory/search_telemetry.py
  symbol: record_memory_search_event
- name: UserModelControl
  file: src/sevn/memory/user_model/control.py
  symbol: UserModelControl
- name: topic_denied
  file: src/sevn/memory/user_model/deny_topics.py
  symbol: topic_denied
- name: UserModelExtractor
  file: src/sevn/memory/user_model/extractor.py
  symbol: UserModelExtractor
- name: UserModelMerger
  file: src/sevn/memory/user_model/merger.py
  symbol: UserModelMerger
- name: InferredFact
  file: src/sevn/memory/user_model/models.py
  symbol: InferredFact
- name: UserProfile
  file: src/sevn/memory/user_model/models.py
  symbol: UserProfile
- name: UserModelExtractionQueue
  file: src/sevn/memory/user_model/queue.py
  symbol: UserModelExtractionQueue
- name: schedule_user_model_extraction
  file: src/sevn/memory/user_model/queue.py
  symbol: schedule_user_model_extraction
- name: render_profile_block
  file: src/sevn/memory/user_model/renderer.py
  symbol: render_profile_block
- name: UserModelStore
  file: src/sevn/memory/user_model/store.py
  symbol: UserModelStore
- name: personality_bump_allowed
  file: src/sevn/memory/user_model/throttle.py
  symbol: personality_bump_allowed
- name: BrowserSession
  file: src/sevn/onboarding/browser_automation.py
  symbol: BrowserSession
- name: BrowserStartRequest
  file: src/sevn/onboarding/browser_automation.py
  symbol: BrowserStartRequest
- name: get_browser_session
  file: src/sevn/onboarding/browser_automation.py
  symbol: get_browser_session
- name: register_shutdown_hooks
  file: src/sevn/onboarding/browser_automation.py
  symbol: register_shutdown_hooks
- name: reset_browser_session_for_tests
  file: src/sevn/onboarding/browser_automation.py
  symbol: reset_browser_session_for_tests
- name: resolve_start_request
  file: src/sevn/onboarding/browser_automation.py
  symbol: resolve_start_request
- name: stop_browser_on_shutdown
  file: src/sevn/onboarding/browser_automation.py
  symbol: stop_browser_on_shutdown
- name: CapabilityEntry
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: CapabilityEntry
- name: CapabilityGroup
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: CapabilityGroup
- name: CapabilityManifest
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: CapabilityManifest
- name: GroupWithCapabilities
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: GroupWithCapabilities
- name: InstallAction
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: InstallAction
- name: index_skill_capability_ids
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: index_skill_capability_ids
- name: list_groups
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: list_groups
- name: load_manifest
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: load_manifest
- name: manifest_resource_path
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: manifest_resource_path
- name: merged_capability_defaults
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: merged_capability_defaults
- name: resolve_install_plan
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: resolve_install_plan
- name: skill_capability_id
  file: src/sevn/onboarding/capabilities_manifest.py
  symbol: skill_capability_id
- name: CDPOnboardingBrowser
  file: src/sevn/onboarding/cdp_browser.py
  symbol: CDPOnboardingBrowser
- name: apply_web_ui_url_for_dashboard
  file: src/sevn/onboarding/dashboard_url.py
  symbol: apply_web_ui_url_for_dashboard
- name: mission_control_entry_url
  file: src/sevn/onboarding/dashboard_url.py
  symbol: mission_control_entry_url
- name: DraftLock
  file: src/sevn/onboarding/draft_store.py
  symbol: DraftLock
- name: discard_draft
  file: src/sevn/onboarding/draft_store.py
  symbol: discard_draft
- name: draft_path
  file: src/sevn/onboarding/draft_store.py
  symbol: draft_path
- name: lock_path
  file: src/sevn/onboarding/draft_store.py
  symbol: lock_path
- name: read_draft
  file: src/sevn/onboarding/draft_store.py
  symbol: read_draft
- name: write_draft
  file: src/sevn/onboarding/draft_store.py
  symbol: write_draft
- name: OnboardingDraftLockError
  file: src/sevn/onboarding/errors.py
  symbol: OnboardingDraftLockError
- name: ExportBundle
  file: src/sevn/onboarding/export_bundle.py
  symbol: ExportBundle
- name: ExportBundleError
  file: src/sevn/onboarding/export_bundle.py
  symbol: ExportBundleError
- name: ExportResult
  file: src/sevn/onboarding/export_bundle.py
  symbol: ExportResult
- name: build_export_text
  file: src/sevn/onboarding/export_bundle.py
  symbol: build_export_text
- name: bundle_seed_secrets
  file: src/sevn/onboarding/export_bundle.py
  symbol: bundle_seed_secrets
- name: parse_export_text
  file: src/sevn/onboarding/export_bundle.py
  symbol: parse_export_text
- name: provider_bindings_from_config_doc
  file: src/sevn/onboarding/export_bundle.py
  symbol: provider_bindings_from_config_doc
- name: resolve_export_workspace
  file: src/sevn/onboarding/export_bundle.py
  symbol: resolve_export_workspace
- name: run_export_secrets
  file: src/sevn/onboarding/export_bundle.py
  symbol: run_export_secrets
- name: FastOnboardError
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardError
- name: FastOnboardPreconditionError
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardPreconditionError
- name: FastOnboardResult
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardResult
- name: FastOnboardValidationError
  file: src/sevn/onboarding/fast_onboard.py
  symbol: FastOnboardValidationError
- name: merge_config_layers
  file: src/sevn/onboarding/fast_onboard.py
  symbol: merge_config_layers
- name: run_fast_onboard
  file: src/sevn/onboarding/fast_onboard.py
  symbol: run_fast_onboard
- name: spawn_gateway_background
  file: src/sevn/onboarding/gateway_spawn.py
  symbol: spawn_gateway_background
- name: build_authorize_url
  file: src/sevn/onboarding/github_oauth.py
  symbol: build_authorize_url
- name: callback_redirect_uri
  file: src/sevn/onboarding/github_oauth.py
  symbol: callback_redirect_uri
- name: clear_oauth_states
  file: src/sevn/onboarding/github_oauth.py
  symbol: clear_oauth_states
- name: clear_wizard_oauth_credentials
  file: src/sevn/onboarding/github_oauth.py
  symbol: clear_wizard_oauth_credentials
- name: exchange_code_for_token
  file: src/sevn/onboarding/github_oauth.py
  symbol: exchange_code_for_token
- name: fetch_github_user
  file: src/sevn/onboarding/github_oauth.py
  symbol: fetch_github_user
- name: mint_oauth_state
  file: src/sevn/onboarding/github_oauth.py
  symbol: mint_oauth_state
- name: oauth_client_credentials
  file: src/sevn/onboarding/github_oauth.py
  symbol: oauth_client_credentials
- name: oauth_configured
  file: src/sevn/onboarding/github_oauth.py
  symbol: oauth_configured
- name: set_wizard_oauth_credentials
  file: src/sevn/onboarding/github_oauth.py
  symbol: set_wizard_oauth_credentials
- name: validate_oauth_state
  file: src/sevn/onboarding/github_oauth.py
  symbol: validate_oauth_state
- name: execute_install_action
  file: src/sevn/onboarding/install_actions/executors.py
  symbol: execute_install_action
- name: idempotent_check_satisfied
  file: src/sevn/onboarding/install_actions/executors.py
  symbol: idempotent_check_satisfied
- name: run_computer_use_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_computer_use_validate
- name: run_cua_agent_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_cua_agent_validate
- name: run_lume_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_lume_validate
- name: run_openwiki_validate
  file: src/sevn/onboarding/install_actions/special.py
  symbol: run_openwiki_validate
- name: InstallGateState
  file: src/sevn/onboarding/install_gate.py
  symbol: InstallGateState
- name: InstallResolution
  file: src/sevn/onboarding/install_gate.py
  symbol: InstallResolution
- name: apply_install_resolution
  file: src/sevn/onboarding/install_gate.py
  symbol: apply_install_resolution
- name: bind_operator_home
  file: src/sevn/onboarding/install_gate.py
  symbol: bind_operator_home
- name: install_gate_state
  file: src/sevn/onboarding/install_gate.py
  symbol: install_gate_state
- name: prompt_install_gate_tty
  file: src/sevn/onboarding/install_gate.py
  symbol: prompt_install_gate_tty
- name: prompt_keystore_passphrase_tty
  file: src/sevn/onboarding/install_gate.py
  symbol: prompt_keystore_passphrase_tty
- name: replace_keystore
  file: src/sevn/onboarding/install_gate.py
  symbol: replace_keystore
- name: resolve_install_action
  file: src/sevn/onboarding/install_gate.py
  symbol: resolve_install_action
- name: wipe_operator_home
  file: src/sevn/onboarding/install_gate.py
  symbol: wipe_operator_home
- name: InstallPlan
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: InstallPlan
- name: InstallPlanStep
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: InstallPlanStep
- name: InstallRunSummary
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: InstallRunSummary
- name: build_install_plan
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: build_install_plan
- name: collect_install_run
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: collect_install_run
- name: format_ndjson_event
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: format_ndjson_event
- name: resolve_install_root
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: resolve_install_root
- name: run_install_plan
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: run_install_plan
- name: selected_capability_ids
  file: src/sevn/onboarding/install_orchestrator.py
  symbol: selected_capability_ids
- name: InstallStatusRow
  file: src/sevn/onboarding/live_validate.py
  symbol: InstallStatusRow
- name: ValidationCheck
  file: src/sevn/onboarding/live_validate.py
  symbol: ValidationCheck
- name: ValidationReport
  file: src/sevn/onboarding/live_validate.py
  symbol: ValidationReport
- name: asyncio_subprocess_run
  file: src/sevn/onboarding/live_validate.py
  symbol: asyncio_subprocess_run
- name: emit_openai_oauth_warnings
  file: src/sevn/onboarding/live_validate.py
  symbol: emit_openai_oauth_warnings
- name: github_hub_enabled
  file: src/sevn/onboarding/live_validate.py
  symbol: github_hub_enabled
- name: handoff_credential_keys_for_doc
  file: src/sevn/onboarding/live_validate.py
  symbol: handoff_credential_keys_for_doc
- name: install_status_to_dict
  file: src/sevn/onboarding/live_validate.py
  symbol: install_status_to_dict
- name: llm_provider_configured
  file: src/sevn/onboarding/live_validate.py
  symbol: llm_provider_configured
- name: openai_oauth_mode_active
  file: src/sevn/onboarding/live_validate.py
  symbol: openai_oauth_mode_active
- name: probe_capability_install_status
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_capability_install_status
- name: probe_github_hub
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_github_hub
- name: probe_llm_reachability
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_llm_reachability
- name: probe_mcp_reachability
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_mcp_reachability
- name: probe_openai_oauth_credential
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_openai_oauth_credential
- name: probe_pdf_weasyprint
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_pdf_weasyprint
- name: probe_secrets_backend
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_secrets_backend
- name: probe_webapp_https
  file: src/sevn/onboarding/live_validate.py
  symbol: probe_webapp_https
- name: run_live_validation
  file: src/sevn/onboarding/live_validate.py
  symbol: run_live_validation
- name: section_uses_encrypted_file
  file: src/sevn/onboarding/live_validate.py
  symbol: section_uses_encrypted_file
- name: telegram_channel_enabled
  file: src/sevn/onboarding/live_validate.py
  symbol: telegram_channel_enabled
- name: merge_layers
  file: src/sevn/onboarding/merge.py
  symbol: merge_layers
- name: MigrationPlan
  file: src/sevn/onboarding/migrate.py
  symbol: MigrationPlan
- name: describe_schema_upgrade
  file: src/sevn/onboarding/migrate.py
  symbol: describe_schema_upgrade
- name: import_foreign_workspace
  file: src/sevn/onboarding/migrate.py
  symbol: import_foreign_workspace
- name: upgrade_schema_inplace
  file: src/sevn/onboarding/migrate.py
  symbol: upgrade_schema_inplace
- name: MyTelegramApiExtract
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: MyTelegramApiExtract
- name: MyTelegramSkipError
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: MyTelegramSkipError
- name: extract_api_hash_from_text
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: extract_api_hash_from_text
- name: extract_api_id_from_text
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: extract_api_id_from_text
- name: normalize_phone
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: normalize_phone
- name: run_fetch_my_telegram_api
  file: src/sevn/onboarding/my_telegram_automation.py
  symbol: run_fetch_my_telegram_api
- name: WizardCodexOAuthStart
  file: src/sevn/onboarding/openai_oauth.py
  symbol: WizardCodexOAuthStart
- name: clear_wizard_codex_oauth_flows
  file: src/sevn/onboarding/openai_oauth.py
  symbol: clear_wizard_codex_oauth_flows
- name: poll_wizard_codex_oauth
  file: src/sevn/onboarding/openai_oauth.py
  symbol: poll_wizard_codex_oauth
- name: start_wizard_codex_oauth
  file: src/sevn/onboarding/openai_oauth.py
  symbol: start_wizard_codex_oauth
- name: build_profile_inspector_payload
  file: src/sevn/onboarding/profile_inspector.py
  symbol: build_profile_inspector_payload
- name: format_inspector_value
  file: src/sevn/onboarding/profile_inspector.py
  symbol: format_inspector_value
- name: get_config_at_path
  file: src/sevn/onboarding/profile_inspector.py
  symbol: get_config_at_path
- name: load_profile_catalog
  file: src/sevn/onboarding/profiles.py
  symbol: load_profile_catalog
- name: load_profile_catalog_for_wizard
  file: src/sevn/onboarding/profiles.py
  symbol: load_profile_catalog_for_wizard
- name: load_profile_fragment
  file: src/sevn/onboarding/profiles.py
  symbol: load_profile_fragment
- name: profile_catalog_path
  file: src/sevn/onboarding/profiles.py
  symbol: profile_catalog_path
- name: profile_default_sandbox_mode
  file: src/sevn/onboarding/profiles.py
  symbol: profile_default_sandbox_mode
- name: profile_has_capabilities_defaults
  file: src/sevn/onboarding/profiles.py
  symbol: profile_has_capabilities_defaults
- name: promote_draft
  file: src/sevn/onboarding/promote.py
  symbol: promote_draft
- name: spawn_proxy_background
  file: src/sevn/onboarding/proxy_spawn.py
  symbol: spawn_proxy_background
- name: ensure_skills_user_dir
  file: src/sevn/onboarding/seed.py
  symbol: ensure_skills_user_dir
- name: expected_core_skill_ids
  file: src/sevn/onboarding/seed.py
  symbol: expected_core_skill_ids
- name: list_deployed_core_skill_ids
  file: src/sevn/onboarding/seed.py
  symbol: list_deployed_core_skill_ids
- name: load_personality_presets
  file: src/sevn/onboarding/seed.py
  symbol: load_personality_presets
- name: load_template
  file: src/sevn/onboarding/seed.py
  symbol: load_template
- name: opt_in_skill_ids_from_capabilities
  file: src/sevn/onboarding/seed.py
  symbol: opt_in_skill_ids_from_capabilities
- name: refresh_bundled_core_skills
  file: src/sevn/onboarding/seed.py
  symbol: refresh_bundled_core_skills
- name: render_template
  file: src/sevn/onboarding/seed.py
  symbol: render_template
- name: resolve_agent_display_name
  file: src/sevn/onboarding/seed.py
  symbol: resolve_agent_display_name
- name: seed_bundled_skills
  file: src/sevn/onboarding/seed.py
  symbol: seed_bundled_skills
- name: seed_llm_params
  file: src/sevn/onboarding/seed.py
  symbol: seed_llm_params
- name: seed_narrative_templates
  file: src/sevn/onboarding/seed.py
  symbol: seed_narrative_templates
- name: seed_personality_from_wizard
  file: src/sevn/onboarding/seed.py
  symbol: seed_personality_from_wizard
- name: seed_tracing_defaults
  file: src/sevn/onboarding/seed.py
  symbol: seed_tracing_defaults
- name: verify_core_skills_deployed
  file: src/sevn/onboarding/seed.py
  symbol: verify_core_skills_deployed
- name: restart_services_after_promote
  file: src/sevn/onboarding/service_restart.py
  symbol: restart_services_after_promote
- name: handoff_child_env
  file: src/sevn/onboarding/spawn_env.py
  symbol: handoff_child_env
- name: TelegramBotExtract
  file: src/sevn/onboarding/telegram_automation.py
  symbol: TelegramBotExtract
- name: extract_bot_token_from_text
  file: src/sevn/onboarding/telegram_automation.py
  symbol: extract_bot_token_from_text
- name: extract_bot_username_from_text
  file: src/sevn/onboarding/telegram_automation.py
  symbol: extract_bot_username_from_text
- name: normalize_bot_username
  file: src/sevn/onboarding/telegram_automation.py
  symbol: normalize_bot_username
- name: open_telegram_web
  file: src/sevn/onboarding/telegram_automation.py
  symbol: open_telegram_web
- name: run_create_new_bot
  file: src/sevn/onboarding/telegram_automation.py
  symbol: run_create_new_bot
- name: run_lookup_existing_bot
  file: src/sevn/onboarding/telegram_automation.py
  symbol: run_lookup_existing_bot
- name: suggest_owner_user_id_from_text
  file: src/sevn/onboarding/telegram_automation.py
  symbol: suggest_owner_user_id_from_text
- name: wait_for_login
  file: src/sevn/onboarding/telegram_automation.py
  symbol: wait_for_login
- name: OnboardApp
  file: src/sevn/onboarding/tui.py
  symbol: OnboardApp
- name: run_textual_onboarding
  file: src/sevn/onboarding/tui.py
  symbol: run_textual_onboarding
- name: emit_unused_provider_warnings
  file: src/sevn/onboarding/validate.py
  symbol: emit_unused_provider_warnings
- name: validate_workspace_document
  file: src/sevn/onboarding/validate.py
  symbol: validate_workspace_document
- name: apply_model_slot_policy
  file: src/sevn/onboarding/web_app.py
  symbol: apply_model_slot_policy
- name: create_onboarding_app
  file: src/sevn/onboarding/web_app.py
  symbol: create_onboarding_app
- name: normalize_llm_main_model_layer
  file: src/sevn/onboarding/web_app.py
  symbol: normalize_llm_main_model_layer
- name: normalize_secrets_backend_section
  file: src/sevn/onboarding/web_app.py
  symbol: normalize_secrets_backend_section
- name: credentials_status
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: credentials_status
- name: default_wizard_secrets_section
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: default_wizard_secrets_section
- name: delete_wizard_credential
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: delete_wizard_credential
- name: get_wizard_credential
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: get_wizard_credential
- name: probe_host_github_token
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: probe_host_github_token
- name: read_wizard_credential_values
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: read_wizard_credential_values
- name: resolve_wizard_secrets_section
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: resolve_wizard_secrets_section
- name: secrets_section_from_sevn_json
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: secrets_section_from_sevn_json
- name: store_wizard_credentials
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: store_wizard_credentials
- name: unlock_wizard_keystore
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: unlock_wizard_keystore
- name: verify_wizard_passphrase
  file: src/sevn/onboarding/wizard_credentials.py
  symbol: verify_wizard_passphrase
- name: create_github_repo_via_api
  file: src/sevn/onboarding/workspace_backup.py
  symbol: create_github_repo_via_api
- name: create_repo_via_gh_cli
  file: src/sevn/onboarding/workspace_backup.py
  symbol: create_repo_via_gh_cli
- name: create_workspace_backup_repo
  file: src/sevn/onboarding/workspace_backup.py
  symbol: create_workspace_backup_repo
- name: default_backup_repo_name
  file: src/sevn/onboarding/workspace_backup.py
  symbol: default_backup_repo_name
- name: repo_url_from_api_response
  file: src/sevn/onboarding/workspace_backup.py
  symbol: repo_url_from_api_response
- name: resolve_backup_default_name
  file: src/sevn/onboarding/workspace_backup.py
  symbol: resolve_backup_default_name
- name: sanitize_repo_name
  file: src/sevn/onboarding/workspace_backup.py
  symbol: sanitize_repo_name
- name: PdfDoctorRow
  file: src/sevn/pdf/doctor_check.py
  symbol: PdfDoctorRow
- name: probe_pdf_optional_extra
  file: src/sevn/pdf/doctor_check.py
  symbol: probe_pdf_optional_extra
- name: probe_weasyprint_render
  file: src/sevn/pdf/doctor_check.py
  symbol: probe_weasyprint_render
- name: weasyprint_native_fix_commands
  file: src/sevn/pdf/doctor_check.py
  symbol: weasyprint_native_fix_commands
- name: fpdf2_available
  file: src/sevn/pdf/fallback_render.py
  symbol: fpdf2_available
- name: normalize_fallback_text
  file: src/sevn/pdf/fallback_render.py
  symbol: normalize_fallback_text
- name: render_pdf_fpdf2_fallback
  file: src/sevn/pdf/fallback_render.py
  symbol: render_pdf_fpdf2_fallback
- name: load_pdf
  file: src/sevn/pdf/load.py
  symbol: load_pdf
- name: openparse_available
  file: src/sevn/pdf/load.py
  symbol: openparse_available
- name: install_weasyprint_native_libs
  file: src/sevn/pdf/native_libs.py
  symbol: install_weasyprint_native_libs
- name: maybe_install_pdf_native_libs_after_promote
  file: src/sevn/pdf/native_libs.py
  symbol: maybe_install_pdf_native_libs_after_promote
- name: resolve_path_under_workspace
  file: src/sevn/pdf/paths.py
  symbol: resolve_path_under_workspace
- name: pdfplumber_available
  file: src/sevn/pdf/read.py
  symbol: pdfplumber_available
- name: read_pdf
  file: src/sevn/pdf/read.py
  symbol: read_pdf
- name: render_pdf_bytes
  file: src/sevn/pdf/render.py
  symbol: render_pdf_bytes
- name: PluginCommandSpec
  file: src/sevn/plugins/command_spec.py
  symbol: PluginCommandSpec
- name: PluginSlashBinding
  file: src/sevn/plugins/command_spec.py
  symbol: PluginSlashBinding
- name: Block
  file: src/sevn/plugins/hook.py
  symbol: Block
- name: Continue
  file: src/sevn/plugins/hook.py
  symbol: Continue
- name: HookContext
  file: src/sevn/plugins/hook.py
  symbol: HookContext
- name: PluginHook
  file: src/sevn/plugins/hook.py
  symbol: PluginHook
- name: PluginHookBase
  file: src/sevn/plugins/hook.py
  symbol: PluginHookBase
- name: Replace
  file: src/sevn/plugins/hook.py
  symbol: Replace
- name: ChannelPluginSpec
  file: src/sevn/plugins/registry.py
  symbol: ChannelPluginSpec
- name: DashboardBadgeEntry
  file: src/sevn/plugins/registry.py
  symbol: DashboardBadgeEntry
- name: build_trigger_mux
  file: src/sevn/plugins/registry.py
  symbol: build_trigger_mux
- name: collect_plugin_slash_bindings
  file: src/sevn/plugins/registry.py
  symbol: collect_plugin_slash_bindings
- name: load_channel_plugin_classes
  file: src/sevn/plugins/registry.py
  symbol: load_channel_plugin_classes
- name: load_dashboard_badge_entries
  file: src/sevn/plugins/registry.py
  symbol: load_dashboard_badge_entries
- name: load_plugin_hook_chain
  file: src/sevn/plugins/registry.py
  symbol: load_plugin_hook_chain
- name: order_hooks_by_runs_after
  file: src/sevn/plugins/registry.py
  symbol: order_hooks_by_runs_after
- name: valid_hook_name
  file: src/sevn/plugins/registry.py
  symbol: valid_hook_name
- name: PluginHookChain
  file: src/sevn/plugins/runner.py
  symbol: PluginHookChain
- name: RegisteredHook
  file: src/sevn/plugins/runner.py
  symbol: RegisteredHook
- name: TriggerPluginHooksMux
  file: src/sevn/plugins/trigger_mux.py
  symbol: TriggerPluginHooksMux
- name: as_trigger_surface
  file: src/sevn/plugins/trigger_mux.py
  symbol: as_trigger_surface
- name: format_cascade_budget_exhausted_message
  file: src/sevn/prompts/fallbacks.py
  symbol: format_cascade_budget_exhausted_message
- name: format_empty_output_message
  file: src/sevn/prompts/fallbacks.py
  symbol: format_empty_output_message
- name: format_tier_b_operator_failure_report
  file: src/sevn/prompts/fallbacks.py
  symbol: format_tier_b_operator_failure_report
- name: is_retry_back_reference_phrase
  file: src/sevn/prompts/fallbacks.py
  symbol: is_retry_back_reference_phrase
- name: looks_like_unfinished_assistant_reply
  file: src/sevn/prompts/fallbacks.py
  symbol: looks_like_unfinished_assistant_reply
- name: match_continuation_phrase
  file: src/sevn/prompts/fallbacks.py
  symbol: match_continuation_phrase
- name: normalize_short_message
  file: src/sevn/prompts/fallbacks.py
  symbol: normalize_short_message
- name: render_no_answer_message
  file: src/sevn/prompts/fallbacks.py
  symbol: render_no_answer_message
- name: unfinished_reply_markers
  file: src/sevn/prompts/fallbacks.py
  symbol: unfinished_reply_markers
- name: tier_b_architecture_context_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_architecture_context_prompt
- name: tier_b_bound_skill_playbook_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_bound_skill_playbook_prompt
- name: tier_b_brevity_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_brevity_prompt
- name: tier_b_codemode_playbook_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_codemode_playbook_prompt
- name: tier_b_file_link_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_file_link_prompt
- name: tier_b_github_repo_eval_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_github_repo_eval_prompt
- name: tier_b_hallucination_guard_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_hallucination_guard_prompt
- name: tier_b_identity_answer_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_identity_answer_prompt
- name: tier_b_identity_boundary_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_identity_boundary_prompt
- name: tier_b_index_architecture_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_index_architecture_prompt
- name: tier_b_last30days_playbook_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_last30days_playbook_prompt
- name: tier_b_list_registry_playbook_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_list_registry_playbook_prompt
- name: tier_b_live_factual_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_live_factual_prompt
- name: tier_b_log_provenance_playbook_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_log_provenance_playbook_prompt
- name: tier_b_log_query_playbook_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_log_query_playbook_prompt
- name: tier_b_memorize_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_memorize_prompt
- name: tier_b_no_preamble_echo_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_no_preamble_echo_prompt
- name: tier_b_no_silent_substitution_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_no_silent_substitution_prompt
- name: tier_b_persistence_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_persistence_prompt
- name: tier_b_playwright_browser_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_playwright_browser_prompt
- name: tier_b_process_install_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_process_install_prompt
- name: tier_b_retrieval_honesty_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_retrieval_honesty_prompt
- name: tier_b_sessions_context_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_sessions_context_prompt
- name: tier_b_spill_recovery_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_spill_recovery_prompt
- name: tier_b_telegram_formatting_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_telegram_formatting_prompt
- name: tier_b_tool_economy_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_tool_economy_prompt
- name: tier_b_tools_vs_skills_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_tools_vs_skills_prompt
- name: tier_b_triager_bound_mandate_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_triager_bound_mandate_prompt
- name: tier_b_workspace_code_search_prompt
  file: src/sevn/prompts/tier_b.py
  symbol: tier_b_workspace_code_search_prompt
- name: HostDep
  file: src/sevn/provisioning/host_deps.py
  symbol: HostDep
- name: ProvisionOutcome
  file: src/sevn/provisioning/host_deps.py
  symbol: ProvisionOutcome
- name: ProvisionReport
  file: src/sevn/provisioning/host_deps.py
  symbol: ProvisionReport
- name: host_dep_ids
  file: src/sevn/provisioning/host_deps.py
  symbol: host_dep_ids
- name: provision_host_deps
  file: src/sevn/provisioning/host_deps.py
  symbol: provision_host_deps
- name: summarize_report
  file: src/sevn/provisioning/host_deps.py
  symbol: summarize_report
- name: normalize_anthropic_request_body
  file: src/sevn/proxy/anthropic_body.py
  symbol: normalize_anthropic_request_body
- name: create_app
  file: src/sevn/proxy/app.py
  symbol: create_app
- name: llm_post_auth_failure
  file: src/sevn/proxy/auth.py
  symbol: llm_post_auth_failure
- name: converse_via_bedrock
  file: src/sevn/proxy/bedrock_converse.py
  symbol: converse_via_bedrock
- name: aggregate_responses_sse
  file: src/sevn/proxy/codex_translation.py
  symbol: aggregate_responses_sse
- name: translate_chat_to_responses_request
  file: src/sevn/proxy/codex_translation.py
  symbol: translate_chat_to_responses_request
- name: translate_responses_sse_to_chat_stream
  file: src/sevn/proxy/codex_translation.py
  symbol: translate_responses_sse_to_chat_stream
- name: translate_responses_to_chat_completion
  file: src/sevn/proxy/codex_translation.py
  symbol: translate_responses_to_chat_completion
- name: build_codex_request_headers
  file: src/sevn/proxy/codex_transport.py
  symbol: build_codex_request_headers
- name: codex_responses_url
  file: src/sevn/proxy/codex_transport.py
  symbol: codex_responses_url
- name: ProviderCredentialEntry
  file: src/sevn/proxy/credentials.py
  symbol: ProviderCredentialEntry
- name: ProviderCredentials
  file: src/sevn/proxy/credentials.py
  symbol: ProviderCredentials
- name: build_proxy_settings
  file: src/sevn/proxy/credentials.py
  symbol: build_proxy_settings
- name: build_proxy_settings_sync
  file: src/sevn/proxy/credentials.py
  symbol: build_proxy_settings_sync
- name: credential_unresolved_detail
  file: src/sevn/proxy/credentials.py
  symbol: credential_unresolved_detail
- name: resolve_oauth_request_credential
  file: src/sevn/proxy/credentials.py
  symbol: resolve_oauth_request_credential
- name: resolve_oauth_request_credential_async
  file: src/sevn/proxy/credentials.py
  symbol: resolve_oauth_request_credential_async
- name: resolve_request_credential
  file: src/sevn/proxy/credentials.py
  symbol: resolve_request_credential
- name: post_json
  file: src/sevn/proxy/forward.py
  symbol: post_json
- name: post_sse_stream
  file: src/sevn/proxy/forward.py
  symbol: post_sse_stream
- name: redact_headers
  file: src/sevn/proxy/forward.py
  symbol: redact_headers
- name: summarize_request_body
  file: src/sevn/proxy/forward.py
  symbol: summarize_request_body
- name: build_proxy_upstream_timeout
  file: src/sevn/proxy/http_client.py
  symbol: build_proxy_upstream_timeout
- name: create_proxy_http_client
  file: src/sevn/proxy/http_client.py
  symbol: create_proxy_http_client
- name: dispatch_cursor
  file: src/sevn/proxy/integration/cursor.py
  symbol: dispatch_cursor
- name: dispatch_github
  file: src/sevn/proxy/integration/github.py
  symbol: dispatch_github
- name: deep_expand_secret_refs
  file: src/sevn/proxy/integration/mcp_expand.py
  symbol: deep_expand_secret_refs
- name: merge_mcp_profile_into_args
  file: src/sevn/proxy/integration/mcp_expand.py
  symbol: merge_mcp_profile_into_args
- name: integration_post
  file: src/sevn/proxy/integration/router.py
  symbol: integration_post
- name: OauthCredentialMissingError
  file: src/sevn/proxy/oauth_lifecycle.py
  symbol: OauthCredentialMissingError
- name: ensure_fresh_oauth_credential
  file: src/sevn/proxy/oauth_lifecycle.py
  symbol: ensure_fresh_oauth_credential
- name: is_oauth_credential_fresh
  file: src/sevn/proxy/oauth_lifecycle.py
  symbol: is_oauth_credential_fresh
- name: ProxySettings
  file: src/sevn/proxy/settings.py
  symbol: ProxySettings
- name: brave_search_json
  file: src/sevn/proxy/web_forward.py
  symbol: brave_search_json
- name: web_fetch_json
  file: src/sevn/proxy/web_forward.py
  symbol: web_fetch_json
- name: spawn_logged
  file: src/sevn/runtime/background_tasks.py
  symbol: spawn_logged
- name: augment_macos_dyld_library_path
  file: src/sevn/runtime/operator_path.py
  symbol: augment_macos_dyld_library_path
- name: augment_operator_path
  file: src/sevn/runtime/operator_path.py
  symbol: augment_operator_path
- name: operator_path_prefixes
  file: src/sevn/runtime/operator_path.py
  symbol: operator_path_prefixes
- name: legacy_native_second_brain_ingest_stub_enabled
  file: src/sevn/second_brain/__init__.py
  symbol: legacy_native_second_brain_ingest_stub_enabled
- name: register_second_brain_tools
  file: src/sevn/second_brain/__init__.py
  symbol: register_second_brain_tools
- name: second_brain_ingest_stub_tool
  file: src/sevn/second_brain/__init__.py
  symbol: second_brain_ingest_stub_tool
- name: second_brain_query_tool
  file: src/sevn/second_brain/__init__.py
  symbol: second_brain_query_tool
- name: wiki_apply_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_apply_tool
- name: wiki_get_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_get_tool
- name: wiki_lint_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_lint_tool
- name: wiki_search_tool
  file: src/sevn/second_brain/__init__.py
  symbol: wiki_search_tool
- name: ensure_second_brain_scope_layout
  file: src/sevn/second_brain/bootstrap.py
  symbol: ensure_second_brain_scope_layout
- name: SecondBrainError
  file: src/sevn/second_brain/errors.py
  symbol: SecondBrainError
- name: SecondBrainMergeNeededError
  file: src/sevn/second_brain/errors.py
  symbol: SecondBrainMergeNeededError
- name: SecondBrainPathError
  file: src/sevn/second_brain/errors.py
  symbol: SecondBrainPathError
- name: SecondBrainFetchError
  file: src/sevn/second_brain/fetch.py
  symbol: SecondBrainFetchError
- name: fetch_url_to_raw
  file: src/sevn/second_brain/fetch.py
  symbol: fetch_url_to_raw
- name: list_workspace_subdirs
  file: src/sevn/second_brain/folder_picker.py
  symbol: list_workspace_subdirs
- name: normalise_browse_path
  file: src/sevn/second_brain/folder_picker.py
  symbol: normalise_browse_path
- name: compose_page
  file: src/sevn/second_brain/frontmatter.py
  symbol: compose_page
- name: dumps_frontmatter
  file: src/sevn/second_brain/frontmatter.py
  symbol: dumps_frontmatter
- name: missing_okf_type
  file: src/sevn/second_brain/frontmatter.py
  symbol: missing_okf_type
- name: normalise_agent_keys
  file: src/sevn/second_brain/frontmatter.py
  symbol: normalise_agent_keys
- name: okf_type_required
  file: src/sevn/second_brain/frontmatter.py
  symbol: okf_type_required
- name: split_frontmatter
  file: src/sevn/second_brain/frontmatter.py
  symbol: split_frontmatter
- name: raw_content_hash
  file: src/sevn/second_brain/ingest.py
  symbol: raw_content_hash
- name: run_ingest
  file: src/sevn/second_brain/ingest.py
  symbol: run_ingest
- name: run_ingest_stub
  file: src/sevn/second_brain/ingest_stub.py
  symbol: run_ingest_stub
- name: SecondBrainLayoutProbe
  file: src/sevn/second_brain/layout_probe.py
  symbol: SecondBrainLayoutProbe
- name: fix_second_brain_layout
  file: src/sevn/second_brain/layout_probe.py
  symbol: fix_second_brain_layout
- name: probe_second_brain_vault_layout
  file: src/sevn/second_brain/layout_probe.py
  symbol: probe_second_brain_vault_layout
- name: index_line_targets
  file: src/sevn/second_brain/links.py
  symbol: index_line_targets
- name: iter_internal_link_targets
  file: src/sevn/second_brain/links.py
  symbol: iter_internal_link_targets
- name: resolve_wiki_target
  file: src/sevn/second_brain/links.py
  symbol: resolve_wiki_target
- name: LintIssue
  file: src/sevn/second_brain/lint_local.py
  symbol: LintIssue
- name: issues_to_json
  file: src/sevn/second_brain/lint_local.py
  symbol: issues_to_json
- name: lint_wiki_tree
  file: src/sevn/second_brain/lint_local.py
  symbol: lint_wiki_tree
- name: SecondBrainMergeToolError
  file: src/sevn/second_brain/merge.py
  symbol: SecondBrainMergeToolError
- name: try_git_merge
  file: src/sevn/second_brain/merge.py
  symbol: try_git_merge
- name: assert_wiki_relative_safe
  file: src/sevn/second_brain/paths.py
  symbol: assert_wiki_relative_safe
- name: display_scope_root_relative
  file: src/sevn/second_brain/paths.py
  symbol: display_scope_root_relative
- name: effective_scope
  file: src/sevn/second_brain/paths.py
  symbol: effective_scope
- name: legacy_shared_vault_root
  file: src/sevn/second_brain/paths.py
  symbol: legacy_shared_vault_root
- name: outputs_dir_for_scope
  file: src/sevn/second_brain/paths.py
  symbol: outputs_dir_for_scope
- name: raw_dir_for_scope
  file: src/sevn/second_brain/paths.py
  symbol: raw_dir_for_scope
- name: resolve_raw_file
  file: src/sevn/second_brain/paths.py
  symbol: resolve_raw_file
- name: resolve_scope_root
  file: src/sevn/second_brain/paths.py
  symbol: resolve_scope_root
- name: resolve_vault_base
  file: src/sevn/second_brain/paths.py
  symbol: resolve_vault_base
- name: resolve_wiki_file
  file: src/sevn/second_brain/paths.py
  symbol: resolve_wiki_file
- name: shared_wiki_root
  file: src/sevn/second_brain/paths.py
  symbol: shared_wiki_root
- name: user_scope_root
  file: src/sevn/second_brain/paths.py
  symbol: user_scope_root
- name: vault_root
  file: src/sevn/second_brain/paths.py
  symbol: vault_root
- name: wiki_dir_for_scope
  file: src/sevn/second_brain/paths.py
  symbol: wiki_dir_for_scope
- name: second_brain_query
  file: src/sevn/second_brain/query.py
  symbol: second_brain_query
- name: SearchHit
  file: src/sevn/second_brain/search.py
  symbol: SearchHit
- name: wiki_search
  file: src/sevn/second_brain/search.py
  symbol: wiki_search
- name: content_sha256_hex
  file: src/sevn/second_brain/wiki_io.py
  symbol: content_sha256_hex
- name: file_sha256_hex
  file: src/sevn/second_brain/wiki_io.py
  symbol: file_sha256_hex
- name: wiki_apply_atomic
  file: src/sevn/second_brain/wiki_io.py
  symbol: wiki_apply_atomic
- name: wiki_read
  file: src/sevn/second_brain/wiki_io.py
  symbol: wiki_read
- name: WitchcraftConfig
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: WitchcraftConfig
- name: build_wiki_index
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: build_wiki_index
- name: index_age_seconds
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: index_age_seconds
- name: maybe_reindex_on_startup
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: maybe_reindex_on_startup
- name: maybe_semantic_scores
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: maybe_semantic_scores
- name: schedule_reindex_debounced
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: schedule_reindex_debounced
- name: semantic_mode_allowed
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: semantic_mode_allowed
- name: witchcraft_indexer_available
  file: src/sevn/second_brain/witchcraft_bridge.py
  symbol: witchcraft_indexer_available
- name: maybe_reindex_workspace_on_startup
  file: src/sevn/second_brain/witchcraft_reindex.py
  symbol: maybe_reindex_workspace_on_startup
- name: reindex_workspace_wiki
  file: src/sevn/second_brain/witchcraft_reindex.py
  symbol: reindex_workspace_wiki
- name: resolve_index_wiki_paths
  file: src/sevn/second_brain/witchcraft_reindex.py
  symbol: resolve_index_wiki_paths
- name: fingerprint_sha256_hex
  file: src/sevn/secrets/fingerprint.py
  symbol: fingerprint_sha256_hex
- name: PromotionResult
  file: src/sevn/secrets/migrate.py
  symbol: PromotionResult
- name: encrypted_file_backend_for_workspace
  file: src/sevn/secrets/migrate.py
  symbol: encrypted_file_backend_for_workspace
- name: legacy_plaintext_entries
  file: src/sevn/secrets/migrate.py
  symbol: legacy_plaintext_entries
- name: non_legacy_files_present
  file: src/sevn/secrets/migrate.py
  symbol: non_legacy_files_present
- name: promote_legacy_plaintext_to_encrypted_store
  file: src/sevn/secrets/migrate.py
  symbol: promote_legacy_plaintext_to_encrypted_store
- name: promote_legacy_plaintext_to_encrypted_store_sync
  file: src/sevn/secrets/migrate.py
  symbol: promote_legacy_plaintext_to_encrypted_store_sync
- name: remove_legacy_plaintext_artifacts
  file: src/sevn/secrets/migrate.py
  symbol: remove_legacy_plaintext_artifacts
- name: secrets_dir_under_content_root
  file: src/sevn/secrets/migrate.py
  symbol: secrets_dir_under_content_root
- name: store_enc_reserved_path
  file: src/sevn/secrets/migrate.py
  symbol: store_enc_reserved_path
- name: apply_namespace_egress_firewall
  file: src/sevn/security/egress_firewall.py
  symbol: apply_namespace_egress_firewall
- name: egress_firewall_noop
  file: src/sevn/security/egress_firewall.py
  symbol: egress_firewall_noop
- name: write_linux_iptables_ruleset
  file: src/sevn/security/egress_firewall.py
  symbol: write_linux_iptables_ruleset
- name: write_macos_pf_ruleset
  file: src/sevn/security/egress_firewall.py
  symbol: write_macos_pf_ruleset
- name: BlockReason
  file: src/sevn/security/llm_guard_scanner.py
  symbol: BlockReason
- name: LLMGuardScanner
  file: src/sevn/security/llm_guard_scanner.py
  symbol: LLMGuardScanner
- name: ScanResult
  file: src/sevn/security/llm_guard_scanner.py
  symbol: ScanResult
- name: ScanVerdict
  file: src/sevn/security/llm_guard_scanner.py
  symbol: ScanVerdict
- name: scan_patch_diff
  file: src/sevn/security/llm_guard_scanner.py
  symbol: scan_patch_diff
- name: assert_shadow_workspace_excludes_llmignore
  file: src/sevn/security/llmignore.py
  symbol: assert_shadow_workspace_excludes_llmignore
- name: ensure_llmignore_layout
  file: src/sevn/security/llmignore.py
  symbol: ensure_llmignore_layout
- name: is_llmignored
  file: src/sevn/security/llmignore.py
  symbol: is_llmignored
- name: resolve_llmignore_root
  file: src/sevn/security/llmignore.py
  symbol: resolve_llmignore_root
- name: sweep_expired
  file: src/sevn/security/llmignore.py
  symbol: sweep_expired
- name: write_blocked_feedback
  file: src/sevn/security/llmignore.py
  symbol: write_blocked_feedback
- name: write_blocked_inbound
  file: src/sevn/security/llmignore.py
  symbol: write_blocked_inbound
- name: AuthorizationFlow
  file: src/sevn/security/oauth/authorize.py
  symbol: AuthorizationFlow
- name: build_authorization_flow
  file: src/sevn/security/oauth/authorize.py
  symbol: build_authorization_flow
- name: OAuthCallbackResult
  file: src/sevn/security/oauth/callback.py
  symbol: OAuthCallbackResult
- name: OAuthCallbackServer
  file: src/sevn/security/oauth/callback.py
  symbol: OAuthCallbackServer
- name: parse_pasted_oauth_redirect
  file: src/sevn/security/oauth/callback.py
  symbol: parse_pasted_oauth_redirect
- name: start_local_callback_server
  file: src/sevn/security/oauth/callback.py
  symbol: start_local_callback_server
- name: CodexOAuthCredential
  file: src/sevn/security/oauth/credential.py
  symbol: CodexOAuthCredential
- name: oauth_openai_secret_alias
  file: src/sevn/security/oauth/credential.py
  symbol: oauth_openai_secret_alias
- name: resolution_probe_credential
  file: src/sevn/security/oauth/credential.py
  symbol: resolution_probe_credential
- name: capture_codex_oauth_callback
  file: src/sevn/security/oauth/login_flow.py
  symbol: capture_codex_oauth_callback
- name: complete_codex_oauth_login
  file: src/sevn/security/oauth/login_flow.py
  symbol: complete_codex_oauth_login
- name: exchange_and_persist_codex_oauth
  file: src/sevn/security/oauth/login_flow.py
  symbol: exchange_and_persist_codex_oauth
- name: load_codex_oauth_credential_from_workspace
  file: src/sevn/security/oauth/login_flow.py
  symbol: load_codex_oauth_credential_from_workspace
- name: PkcePair
  file: src/sevn/security/oauth/pkce.py
  symbol: PkcePair
- name: generate_pkce_pair
  file: src/sevn/security/oauth/pkce.py
  symbol: generate_pkce_pair
- name: load_codex_oauth_credential
  file: src/sevn/security/oauth/storage.py
  symbol: load_codex_oauth_credential
- name: persist_codex_oauth_credential
  file: src/sevn/security/oauth/storage.py
  symbol: persist_codex_oauth_credential
- name: TokenExchangeResult
  file: src/sevn/security/oauth/token_client.py
  symbol: TokenExchangeResult
- name: exchange_authorization_code
  file: src/sevn/security/oauth/token_client.py
  symbol: exchange_authorization_code
- name: extract_account_id
  file: src/sevn/security/oauth/token_client.py
  symbol: extract_account_id
- name: refresh_access_token
  file: src/sevn/security/oauth/token_client.py
  symbol: refresh_access_token
- name: SandboxConfigurationError
  file: src/sevn/security/sandbox_errors.py
  symbol: SandboxConfigurationError
- name: SandboxError
  file: src/sevn/security/sandbox_errors.py
  symbol: SandboxError
- name: SandboxPolicyViolationError
  file: src/sevn/security/sandbox_errors.py
  symbol: SandboxPolicyViolationError
- name: DockerSandboxRuntime
  file: src/sevn/security/sandbox_runtime.py
  symbol: DockerSandboxRuntime
- name: SandboxDriver
  file: src/sevn/security/sandbox_runtime.py
  symbol: SandboxDriver
- name: SandboxRuntime
  file: src/sevn/security/sandbox_runtime.py
  symbol: SandboxRuntime
- name: SubprocessSandboxRuntime
  file: src/sevn/security/sandbox_runtime.py
  symbol: SubprocessSandboxRuntime
- name: build_sandbox_child_env
  file: src/sevn/security/sandbox_runtime.py
  symbol: build_sandbox_child_env
- name: check_self_preservation_argv
  file: src/sevn/security/sandbox_runtime.py
  symbol: check_self_preservation_argv
- name: docker_daemon_reachable
  file: src/sevn/security/sandbox_runtime.py
  symbol: docker_daemon_reachable
- name: load_snapshot_manifest_version
  file: src/sevn/security/sandbox_runtime.py
  symbol: load_snapshot_manifest_version
- name: make_runtime_for_driver
  file: src/sevn/security/sandbox_runtime.py
  symbol: make_runtime_for_driver
- name: materialize_shadow_workspace
  file: src/sevn/security/sandbox_runtime.py
  symbol: materialize_shadow_workspace
- name: pid_target_gate_stub
  file: src/sevn/security/sandbox_runtime.py
  symbol: pid_target_gate_stub
- name: prune_workspace_snapshots
  file: src/sevn/security/sandbox_runtime.py
  symbol: prune_workspace_snapshots
- name: resolve_sandbox_driver
  file: src/sevn/security/sandbox_runtime.py
  symbol: resolve_sandbox_driver
- name: snapshot_tarball_format_supported
  file: src/sevn/security/sandbox_runtime.py
  symbol: snapshot_tarball_format_supported
- name: snapshots_dir
  file: src/sevn/security/sandbox_runtime.py
  symbol: snapshots_dir
- name: write_workspace_snapshot_tarball
  file: src/sevn/security/sandbox_runtime.py
  symbol: write_workspace_snapshot_tarball
- name: SandboxLabeledContainer
  file: src/sevn/security/sandbox_sweeper.py
  symbol: SandboxLabeledContainer
- name: SandboxRunRegistry
  file: src/sevn/security/sandbox_sweeper.py
  symbol: SandboxRunRegistry
- name: orphan_container_should_kill
  file: src/sevn/security/sandbox_sweeper.py
  symbol: orphan_container_should_kill
- name: sweep_orphan_labels
  file: src/sevn/security/sandbox_sweeper.py
  symbol: sweep_orphan_labels
- name: EncryptedFileBackend
  file: src/sevn/security/secrets/backends/encrypted_file.py
  symbol: EncryptedFileBackend
- name: default_encrypted_store_path
  file: src/sevn/security/secrets/backends/encrypted_file.py
  symbol: default_encrypted_store_path
- name: LinuxSecretServiceBackend
  file: src/sevn/security/secrets/backends/linux_secret_service.py
  symbol: LinuxSecretServiceBackend
- name: MacOSKeychainBackend
  file: src/sevn/security/secrets/backends/macos_keychain.py
  symbol: MacOSKeychainBackend
- name: OpenBaoBackend
  file: src/sevn/security/secrets/backends/openbao.py
  symbol: OpenBaoBackend
- name: ProtonPassCliBackend
  file: src/sevn/security/secrets/backends/proton_pass.py
  symbol: ProtonPassCliBackend
- name: ResolvedSecretsCache
  file: src/sevn/security/secrets/cache.py
  symbol: ResolvedSecretsCache
- name: SecretsChain
  file: src/sevn/security/secrets/chain.py
  symbol: SecretsChain
- name: SecretsChainWriteError
  file: src/sevn/security/secrets/chain.py
  symbol: SecretsChainWriteError
- name: get_secret_resilient
  file: src/sevn/security/secrets/chain.py
  symbol: get_secret_resilient
- name: SecretUnresolvedError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretUnresolvedError
- name: SecretsBackendError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsBackendError
- name: SecretsError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsError
- name: SecretsStoreCorruptError
  file: src/sevn/security/secrets/errors.py
  symbol: SecretsStoreCorruptError
- name: is_encrypted_store_decrypt_failure
  file: src/sevn/security/secrets/errors.py
  symbol: is_encrypted_store_decrypt_failure
- name: is_encrypted_store_unlock_error
  file: src/sevn/security/secrets/errors.py
  symbol: is_encrypted_store_unlock_error
- name: default_chain_entries
  file: src/sevn/security/secrets/factory.py
  symbol: default_chain_entries
- name: parse_optional_master_key_hex
  file: src/sevn/security/secrets/factory.py
  symbol: parse_optional_master_key_hex
- name: resolve_backend
  file: src/sevn/security/secrets/factory.py
  symbol: resolve_backend
- name: resolve_primary_encrypted_store_path
  file: src/sevn/security/secrets/factory.py
  symbol: resolve_primary_encrypted_store_path
- name: secrets_chain_from_workspace
  file: src/sevn/security/secrets/factory.py
  symbol: secrets_chain_from_workspace
- name: fetch_unlock_secret_from_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: fetch_unlock_secret_from_keychain
- name: keychain_has_unlock_secret
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: keychain_has_unlock_secret
- name: prime_unlock_env_from_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: prime_unlock_env_from_keychain
- name: reconcile_unlock_env_with_keychain
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: reconcile_unlock_env_with_keychain
- name: unlock_env_var_for
  file: src/sevn/security/secrets/passphrase_prime.py
  symbol: unlock_env_var_for
- name: SecretsBackend
  file: src/sevn/security/secrets/protocol.py
  symbol: SecretsBackend
- name: EnvUnresolvedError
  file: src/sevn/security/secrets/value_expand.py
  symbol: EnvUnresolvedError
- name: expand_env_refs
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_env_refs
- name: expand_refs_env_then_secret
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_refs_env_then_secret
- name: expand_secret_refs
  file: src/sevn/security/secrets/value_expand.py
  symbol: expand_secret_refs
- name: effective_self_improve_enabled
  file: src/sevn/self_improve/effective.py
  symbol: effective_self_improve_enabled
- name: ImproveJobResult
  file: src/sevn/self_improve/eval/__init__.py
  symbol: ImproveJobResult
- name: eval_docker_required
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_docker_required
- name: eval_in_process_override
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_in_process_override
- name: eval_report_passed
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_report_passed
- name: golden_routing_fixture_path
  file: src/sevn/self_improve/eval/__init__.py
  symbol: golden_routing_fixture_path
- name: resolve_repo_root
  file: src/sevn/self_improve/eval/__init__.py
  symbol: resolve_repo_root
- name: run_docker_eval_graph
  file: src/sevn/self_improve/eval/__init__.py
  symbol: run_docker_eval_graph
- name: run_eval_graph
  file: src/sevn/self_improve/eval/__init__.py
  symbol: run_eval_graph
- name: LastKnownGoodRecord
  file: src/sevn/self_improve/eval/baseline.py
  symbol: LastKnownGoodRecord
- name: baseline_path_for_job_bundle
  file: src/sevn/self_improve/eval/baseline.py
  symbol: baseline_path_for_job_bundle
- name: baseline_section_for_report
  file: src/sevn/self_improve/eval/baseline.py
  symbol: baseline_section_for_report
- name: compute_metric_deltas
  file: src/sevn/self_improve/eval/baseline.py
  symbol: compute_metric_deltas
- name: load_last_known_good
  file: src/sevn/self_improve/eval/baseline.py
  symbol: load_last_known_good
- name: parse_token_budget_daily
  file: src/sevn/self_improve/eval/baseline.py
  symbol: parse_token_budget_daily
- name: save_last_known_good
  file: src/sevn/self_improve/eval/baseline.py
  symbol: save_last_known_good
- name: run_eval_in_docker
  file: src/sevn/self_improve/eval/docker.py
  symbol: run_eval_in_docker
- name: main
  file: src/sevn/self_improve/eval/launcher.py
  symbol: main
- name: EvalSegmentResult
  file: src/sevn/self_improve/eval/replay.py
  symbol: EvalSegmentResult
- name: GoldenRoutingMetrics
  file: src/sevn/self_improve/eval/replay.py
  symbol: GoldenRoutingMetrics
- name: GoldenRoutingReplayResult
  file: src/sevn/self_improve/eval/replay.py
  symbol: GoldenRoutingReplayResult
- name: LiveReplaySmokeResult
  file: src/sevn/self_improve/eval/replay.py
  symbol: LiveReplaySmokeResult
- name: golden_routing_fixture_path
  file: src/sevn/self_improve/eval/replay.py
  symbol: golden_routing_fixture_path
- name: run_golden_routing_replay
  file: src/sevn/self_improve/eval/replay.py
  symbol: run_golden_routing_replay
- name: run_live_replay_smoke
  file: src/sevn/self_improve/eval/replay.py
  symbol: run_live_replay_smoke
- name: strip_corpus_locale_prefix
  file: src/sevn/self_improve/eval/replay.py
  symbol: strip_corpus_locale_prefix
- name: improve_export_dir
  file: src/sevn/self_improve/export.py
  symbol: improve_export_dir
- name: prune_stale_export_bundles
  file: src/sevn/self_improve/export.py
  symbol: prune_stale_export_bundles
- name: scaffold_improve_export_bundle
  file: src/sevn/self_improve/export.py
  symbol: scaffold_improve_export_bundle
- name: abort_improve_job
  file: src/sevn/self_improve/facade.py
  symbol: abort_improve_job
- name: enqueue_improve_job
  file: src/sevn/self_improve/facade.py
  symbol: enqueue_improve_job
- name: ensure_preset_c_auto_merge_allowed
  file: src/sevn/self_improve/facade.py
  symbol: ensure_preset_c_auto_merge_allowed
- name: run_improve_job_eval
  file: src/sevn/self_improve/facade.py
  symbol: run_improve_job_eval
- name: insert_feedback_event
  file: src/sevn/self_improve/feedback/__init__.py
  symbol: insert_feedback_event
- name: mirror_structured_feedback_to_events
  file: src/sevn/self_improve/feedback/__init__.py
  symbol: mirror_structured_feedback_to_events
- name: forge_api_base
  file: src/sevn/self_improve/forge_providers.py
  symbol: forge_api_base
- name: ImproveJobEventFanoutFn
  file: src/sevn/self_improve/jobs/events.py
  symbol: ImproveJobEventFanoutFn
- name: ImproveJobEventPayload
  file: src/sevn/self_improve/jobs/events.py
  symbol: ImproveJobEventPayload
- name: improve_job_ws_topic
  file: src/sevn/self_improve/jobs/events.py
  symbol: improve_job_ws_topic
- name: maybe_publish_job_event
  file: src/sevn/self_improve/jobs/events.py
  symbol: maybe_publish_job_event
- name: ImproveJobRow
  file: src/sevn/self_improve/jobs/store.py
  symbol: ImproveJobRow
- name: abort_job_row
  file: src/sevn/self_improve/jobs/store.py
  symbol: abort_job_row
- name: claim_next_queued_job
  file: src/sevn/self_improve/jobs/store.py
  symbol: claim_next_queued_job
- name: enqueue_job_row
  file: src/sevn/self_improve/jobs/store.py
  symbol: enqueue_job_row
- name: fetch_job_row
  file: src/sevn/self_improve/jobs/store.py
  symbol: fetch_job_row
- name: list_recent_job_rows
  file: src/sevn/self_improve/jobs/store.py
  symbol: list_recent_job_rows
- name: requeue_after_plan_approval
  file: src/sevn/self_improve/jobs/store.py
  symbol: requeue_after_plan_approval
- name: update_job_state
  file: src/sevn/self_improve/jobs/store.py
  symbol: update_job_state
- name: EvalGraphRunner
  file: src/sevn/self_improve/jobs/worker.py
  symbol: EvalGraphRunner
- name: ImproveJobWorker
  file: src/sevn/self_improve/jobs/worker.py
  symbol: ImproveJobWorker
- name: Lesson
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: Lesson
- name: emit_recall_audit
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: emit_recall_audit
- name: recall_lessons
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: recall_lessons
- name: append_jsonl_locked
  file: src/sevn/self_improve/lessons/io.py
  symbol: append_jsonl_locked
- name: record_openui_render_error
  file: src/sevn/self_improve/openui_telemetry.py
  symbol: record_openui_render_error
- name: snapshot_openui_buckets
  file: src/sevn/self_improve/openui_telemetry.py
  symbol: snapshot_openui_buckets
- name: improve_root
  file: src/sevn/self_improve/paths.py
  symbol: improve_root
- name: job_bundle_dir
  file: src/sevn/self_improve/paths.py
  symbol: job_bundle_dir
- name: self_improve_audit_path
  file: src/sevn/self_improve/paths.py
  symbol: self_improve_audit_path
- name: reject_patch_diff
  file: src/sevn/self_improve/proposer/__init__.py
  symbol: reject_patch_diff
- name: PatchProposal
  file: src/sevn/self_improve/proposer/agent.py
  symbol: PatchProposal
- name: run_patch_proposal_agent
  file: src/sevn/self_improve/proposer/agent.py
  symbol: run_patch_proposal_agent
- name: build_context_pack_payload
  file: src/sevn/self_improve/proposer/context_loader.py
  symbol: build_context_pack_payload
- name: load_context_pack
  file: src/sevn/self_improve/proposer/context_loader.py
  symbol: load_context_pack
- name: write_context_pack
  file: src/sevn/self_improve/proposer/context_loader.py
  symbol: write_context_pack
- name: PatchAuthorResult
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: PatchAuthorResult
- name: author_patch_from_shortlist
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: author_patch_from_shortlist
- name: paths_in_unified_diff
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: paths_in_unified_diff
- name: preset_requires_proposer
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: preset_requires_proposer
- name: proposer_budget_exhausted
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: proposer_budget_exhausted
- name: reject_patch_glob_scope
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: reject_patch_glob_scope
- name: reject_patch_policy
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: reject_patch_policy
- name: resolve_patch_author_mode
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: resolve_patch_author_mode
- name: write_patch_artefacts
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: write_patch_artefacts
- name: stub_author_patch_from_shortlist
  file: src/sevn/self_improve/proposer/patch_author_stub.py
  symbol: stub_author_patch_from_shortlist
- name: build_patch_author_prompt
  file: src/sevn/self_improve/proposer/prompt.py
  symbol: build_patch_author_prompt
- name: prune_stale_job_bundles
  file: src/sevn/self_improve/retention.py
  symbol: prune_stale_job_bundles
- name: ShortlistCandidate
  file: src/sevn/self_improve/sampler/__init__.py
  symbol: ShortlistCandidate
- name: allocate_shortlist
  file: src/sevn/self_improve/sampler/__init__.py
  symbol: allocate_shortlist
- name: load_sampler_candidates
  file: src/sevn/self_improve/sampler/sources.py
  symbol: load_sampler_candidates
- name: improve_spec_kit_dir
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: improve_spec_kit_dir
- name: mark_plan_approved
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: mark_plan_approved
- name: plan_hitl_blocks_patch
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: plan_hitl_blocks_patch
- name: run_improve_spec_kit_plan
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: run_improve_spec_kit_plan
- name: spec_kit_plan_stage_enabled
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: spec_kit_plan_stage_enabled
- name: write_context_pack
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: write_context_pack
- name: emit_self_improve_trace
  file: src/sevn/self_improve/trace_events.py
  symbol: emit_self_improve_trace
- name: TrajectoryTurn
  file: src/sevn/self_improve/trajectories/__init__.py
  symbol: TrajectoryTurn
- name: stable_turn_id
  file: src/sevn/self_improve/trajectories/__init__.py
  symbol: stable_turn_id
- name: TrajectoryIngestResult
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: TrajectoryIngestResult
- name: ingest_trajectory_fact_for_turn
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: ingest_trajectory_fact_for_turn
- name: ingest_trajectory_facts_from_traces
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: ingest_trajectory_facts_from_traces
- name: trajectory_reconciliation_rate
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: trajectory_reconciliation_rate
- name: schedule_trajectory_ingest
  file: src/sevn/self_improve/trajectories/queue.py
  symbol: schedule_trajectory_ingest
- name: run_trajectory_ingest
  file: src/sevn/self_improve/trajectories/runner.py
  symbol: run_trajectory_ingest
- name: effective_trajectories
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: effective_trajectories
- name: read_last_trajectory_ingest_ts_ns
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: read_last_trajectory_ingest_ts_ns
- name: reconcile_trajectory_ingest_cron_job
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: reconcile_trajectory_ingest_cron_job
- name: run_scheduled_trajectory_ingest
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: run_scheduled_trajectory_ingest
- name: write_last_trajectory_ingest_ts_ns
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: write_last_trajectory_ingest_ts_ns
- name: OwnerPrincipal
  file: src/sevn/self_improve/types.py
  symbol: OwnerPrincipal
- name: prune_orphan_browser_profiles
  file: src/sevn/skills/browser_gc.py
  symbol: prune_orphan_browser_profiles
- name: BrowserReadiness
  file: src/sevn/skills/browser_session.py
  symbol: BrowserReadiness
- name: BrowserSessionRegistry
  file: src/sevn/skills/browser_session.py
  symbol: BrowserSessionRegistry
- name: CloseBrowserResult
  file: src/sevn/skills/browser_session.py
  symbol: CloseBrowserResult
- name: TabOperationError
  file: src/sevn/skills/browser_session.py
  symbol: TabOperationError
- name: TabSessionView
  file: src/sevn/skills/browser_session.py
  symbol: TabSessionView
- name: activate_tab
  file: src/sevn/skills/browser_session.py
  symbol: activate_tab
- name: browser_autoclose_enabled
  file: src/sevn/skills/browser_session.py
  symbol: browser_autoclose_enabled
- name: browser_page
  file: src/sevn/skills/browser_session.py
  symbol: browser_page
- name: browser_readiness_snapshot
  file: src/sevn/skills/browser_session.py
  symbol: browser_readiness_snapshot
- name: cdp_list_page_targets
  file: src/sevn/skills/browser_session.py
  symbol: cdp_list_page_targets
- name: cdp_port_from_url
  file: src/sevn/skills/browser_session.py
  symbol: cdp_port_from_url
- name: cdp_port_seed
  file: src/sevn/skills/browser_session.py
  symbol: cdp_port_seed
- name: cdp_reachable
  file: src/sevn/skills/browser_session.py
  symbol: cdp_reachable
- name: clear_registry
  file: src/sevn/skills/browser_session.py
  symbol: clear_registry
- name: close_all_gateway_browsers
  file: src/sevn/skills/browser_session.py
  symbol: close_all_gateway_browsers
- name: close_browser_session
  file: src/sevn/skills/browser_session.py
  symbol: close_browser_session
- name: close_idle_browser_sessions
  file: src/sevn/skills/browser_session.py
  symbol: close_idle_browser_sessions
- name: close_tab
  file: src/sevn/skills/browser_session.py
  symbol: close_tab
- name: connected_tab_session
  file: src/sevn/skills/browser_session.py
  symbol: connected_tab_session
- name: default_cdp_url
  file: src/sevn/skills/browser_session.py
  symbol: default_cdp_url
- name: is_brave_executable
  file: src/sevn/skills/browser_session.py
  symbol: is_brave_executable
- name: list_tabs
  file: src/sevn/skills/browser_session.py
  symbol: list_tabs
- name: merge_browser_proc_env
  file: src/sevn/skills/browser_session.py
  symbol: merge_browser_proc_env
- name: open_tab
  file: src/sevn/skills/browser_session.py
  symbol: open_tab
- name: page_target_id
  file: src/sevn/skills/browser_session.py
  symbol: page_target_id
- name: persist_active_target_id
  file: src/sevn/skills/browser_session.py
  symbol: persist_active_target_id
- name: pick_work_page
  file: src/sevn/skills/browser_session.py
  symbol: pick_work_page
- name: read_devtools_active_port
  file: src/sevn/skills/browser_session.py
  symbol: read_devtools_active_port
- name: read_registry
  file: src/sevn/skills/browser_session.py
  symbol: read_registry
- name: registry_path
  file: src/sevn/skills/browser_session.py
  symbol: registry_path
- name: resolve_browser_engine
  file: src/sevn/skills/browser_session.py
  symbol: resolve_browser_engine
- name: resolve_browser_extra_args
  file: src/sevn/skills/browser_session.py
  symbol: resolve_browser_extra_args
- name: resolve_browser_headless
  file: src/sevn/skills/browser_session.py
  symbol: resolve_browser_headless
- name: resolve_cdp_url
  file: src/sevn/skills/browser_session.py
  symbol: resolve_cdp_url
- name: resolve_chrome_executable
  file: src/sevn/skills/browser_session.py
  symbol: resolve_chrome_executable
- name: resolve_idle_close_seconds
  file: src/sevn/skills/browser_session.py
  symbol: resolve_idle_close_seconds
- name: resolve_profile_dir
  file: src/sevn/skills/browser_session.py
  symbol: resolve_profile_dir
- name: resolve_target_page
  file: src/sevn/skills/browser_session.py
  symbol: resolve_target_page
- name: restart_browser_session
  file: src/sevn/skills/browser_session.py
  symbol: restart_browser_session
- name: session_status_payload
  file: src/sevn/skills/browser_session.py
  symbol: session_status_payload
- name: spawn_chrome
  file: src/sevn/skills/browser_session.py
  symbol: spawn_chrome
- name: try_persist_active_page
  file: src/sevn/skills/browser_session.py
  symbol: try_persist_active_page
- name: wait_for_page_ready
  file: src/sevn/skills/browser_session.py
  symbol: wait_for_page_ready
- name: write_registry
  file: src/sevn/skills/browser_session.py
  symbol: write_registry
- name: build_skill_capability_rows
  file: src/sevn/skills/capabilities.py
  symbol: build_skill_capability_rows
- name: computer_use_config_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_config_enabled
- name: computer_use_mcp_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_mcp_enabled
- name: computer_use_snapshot_annotate_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_snapshot_annotate_enabled
- name: computer_use_trajectory_export_dir
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_trajectory_export_dir
- name: computer_use_trajectory_share_enabled
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_trajectory_share_enabled
- name: computer_use_uses_cua_driver_mcp
  file: src/sevn/skills/computer_use.py
  symbol: computer_use_uses_cua_driver_mcp
- name: gate_computer_use_core_skill
  file: src/sevn/skills/computer_use.py
  symbol: gate_computer_use_core_skill
- name: mcp_stdio_entry
  file: src/sevn/skills/computer_use.py
  symbol: mcp_stdio_entry
- name: merge_computer_use_mcp_server
  file: src/sevn/skills/computer_use.py
  symbol: merge_computer_use_mcp_server
- name: resolve_computer_use_target
  file: src/sevn/skills/computer_use.py
  symbol: resolve_computer_use_target
- name: resolve_cua_cli_command
  file: src/sevn/skills/computer_use.py
  symbol: resolve_cua_cli_command
- name: resolve_cua_do_switch_provider
  file: src/sevn/skills/computer_use.py
  symbol: resolve_cua_do_switch_provider
- name: resolve_cua_driver_command
  file: src/sevn/skills/computer_use.py
  symbol: resolve_cua_driver_command
- name: validate_computer_use_host
  file: src/sevn/skills/computer_use.py
  symbol: validate_computer_use_host
- name: cua_agent_approval_mode
  file: src/sevn/skills/cua_agent.py
  symbol: cua_agent_approval_mode
- name: cua_agent_config_enabled
  file: src/sevn/skills/cua_agent.py
  symbol: cua_agent_config_enabled
- name: cua_agent_require_computer_use
  file: src/sevn/skills/cua_agent.py
  symbol: cua_agent_require_computer_use
- name: gate_cua_agent_core_skill
  file: src/sevn/skills/cua_agent.py
  symbol: gate_cua_agent_core_skill
- name: validate_cua_agent_host
  file: src/sevn/skills/cua_agent.py
  symbol: validate_cua_agent_host
- name: validate_cua_agent_run
  file: src/sevn/skills/cua_agent.py
  symbol: validate_cua_agent_run
- name: CuaDoctorRow
  file: src/sevn/skills/cua_doctor_check.py
  symbol: CuaDoctorRow
- name: probe_cua_skill_checks
  file: src/sevn/skills/cua_doctor_check.py
  symbol: probe_cua_skill_checks
- name: cursor_cloud_config_enabled
  file: src/sevn/skills/cursor_cloud.py
  symbol: cursor_cloud_config_enabled
- name: gate_cursor_cloud_core_skill
  file: src/sevn/skills/cursor_cloud.py
  symbol: gate_cursor_cloud_core_skill
- name: EmailAccount
  file: src/sevn/skills/email_management.py
  symbol: EmailAccount
- name: ImapClientProtocol
  file: src/sevn/skills/email_management.py
  symbol: ImapClientProtocol
- name: MessageSummary
  file: src/sevn/skills/email_management.py
  symbol: MessageSummary
- name: StdlibImapClient
  file: src/sevn/skills/email_management.py
  symbol: StdlibImapClient
- name: account_public_dict
  file: src/sevn/skills/email_management.py
  symbol: account_public_dict
- name: create_imap_client
  file: src/sevn/skills/email_management.py
  symbol: create_imap_client
- name: dry_run_requested
  file: src/sevn/skills/email_management.py
  symbol: dry_run_requested
- name: fetch_recent_messages
  file: src/sevn/skills/email_management.py
  symbol: fetch_recent_messages
- name: gmail_api_plan
  file: src/sevn/skills/email_management.py
  symbol: gmail_api_plan
- name: list_imap_folders
  file: src/sevn/skills/email_management.py
  symbol: list_imap_folders
- name: load_accounts
  file: src/sevn/skills/email_management.py
  symbol: load_accounts
- name: resolve_account
  file: src/sevn/skills/email_management.py
  symbol: resolve_account
- name: resolve_password
  file: src/sevn/skills/email_management.py
  symbol: resolve_password
- name: search_imap_messages
  file: src/sevn/skills/email_management.py
  symbol: search_imap_messages
- name: send_smtp_message
  file: src/sevn/skills/email_management.py
  symbol: send_smtp_message
- name: summaries_to_dicts
  file: src/sevn/skills/email_management.py
  symbol: summaries_to_dicts
- name: reserved_skills_plugin_row
  file: src/sevn/skills/entrypoints.py
  symbol: reserved_skills_plugin_row
- name: SkillExecutionError
  file: src/sevn/skills/errors.py
  symbol: SkillExecutionError
- name: failure_envelope
  file: src/sevn/skills/errors.py
  symbol: failure_envelope
- name: success_envelope
  file: src/sevn/skills/errors.py
  symbol: success_envelope
- name: SkillsIndex
  file: src/sevn/skills/index.py
  symbol: SkillsIndex
- name: SkillsIndexBuilder
  file: src/sevn/skills/index.py
  symbol: SkillsIndexBuilder
- name: augment_index_with_aliases
  file: src/sevn/skills/index.py
  symbol: augment_index_with_aliases
- name: resolve_skill_alias
  file: src/sevn/skills/index.py
  symbol: resolve_skill_alias
- name: gate_lume_core_skill
  file: src/sevn/skills/lume.py
  symbol: gate_lume_core_skill
- name: lume_config_enabled
  file: src/sevn/skills/lume.py
  symbol: lume_config_enabled
- name: resolve_lume_command
  file: src/sevn/skills/lume.py
  symbol: resolve_lume_command
- name: validate_lume_host
  file: src/sevn/skills/lume.py
  symbol: validate_lume_host
- name: SkillsManager
  file: src/sevn/skills/manager.py
  symbol: SkillsManager
- name: did_you_mean_skill_script
  file: src/sevn/skills/manager.py
  symbol: did_you_mean_skill_script
- name: RunnableEntry
  file: src/sevn/skills/manifest.py
  symbol: RunnableEntry
- name: SkillManifest
  file: src/sevn/skills/manifest.py
  symbol: SkillManifest
- name: SkillScriptEntry
  file: src/sevn/skills/manifest.py
  symbol: SkillScriptEntry
- name: downgrade_manifest
  file: src/sevn/skills/manifest.py
  symbol: downgrade_manifest
- name: infer_abortable_for_script
  file: src/sevn/skills/manifest.py
  symbol: infer_abortable_for_script
- name: manifest_from_mapping
  file: src/sevn/skills/manifest.py
  symbol: manifest_from_mapping
- name: parse_skill_markdown
  file: src/sevn/skills/manifest.py
  symbol: parse_skill_markdown
- name: required_positional_arg_count
  file: src/sevn/skills/manifest.py
  symbol: required_positional_arg_count
- name: split_frontmatter
  file: src/sevn/skills/manifest.py
  symbol: split_frontmatter
- name: validate_script_argv
  file: src/sevn/skills/manifest.py
  symbol: validate_script_argv
- name: validate_script_paths
  file: src/sevn/skills/manifest.py
  symbol: validate_script_paths
- name: SkillRecord
  file: src/sevn/skills/models.py
  symbol: SkillRecord
- name: gate_openwiki_core_skill
  file: src/sevn/skills/openwiki.py
  symbol: gate_openwiki_core_skill
- name: openwiki_config_enabled
  file: src/sevn/skills/openwiki.py
  symbol: openwiki_config_enabled
- name: OpenwikiDoctorRow
  file: src/sevn/skills/openwiki_doctor_check.py
  symbol: OpenwikiDoctorRow
- name: probe_openwiki_skill_checks
  file: src/sevn/skills/openwiki_doctor_check.py
  symbol: probe_openwiki_skill_checks
- name: probe_openwiki_skill_checks_async
  file: src/sevn/skills/openwiki_doctor_check.py
  symbol: probe_openwiki_skill_checks_async
- name: check_node_for_openwiki
  file: src/sevn/skills/openwiki_install.py
  symbol: check_node_for_openwiki
- name: openwiki_cli_installed
  file: src/sevn/skills/openwiki_install.py
  symbol: openwiki_cli_installed
- name: run_openwiki_install
  file: src/sevn/skills/openwiki_install.py
  symbol: run_openwiki_install
- name: merge_openwiki_proc_env
  file: src/sevn/skills/openwiki_secrets.py
  symbol: merge_openwiki_proc_env
- name: openwiki_credentials_hint
  file: src/sevn/skills/openwiki_secrets.py
  symbol: openwiki_credentials_hint
- name: openwiki_credentials_resolved
  file: src/sevn/skills/openwiki_secrets.py
  symbol: openwiki_credentials_resolved
- name: BaselineSuppression
  file: src/sevn/skills/security_scan.py
  symbol: BaselineSuppression
- name: ScanIssue
  file: src/sevn/skills/security_scan.py
  symbol: ScanIssue
- name: ScanResult
  file: src/sevn/skills/security_scan.py
  symbol: ScanResult
- name: apply_baseline
  file: src/sevn/skills/security_scan.py
  symbol: apply_baseline
- name: emit_security_scan_trace
  file: src/sevn/skills/security_scan.py
  symbol: emit_security_scan_trace
- name: filter_by_severities
  file: src/sevn/skills/security_scan.py
  symbol: filter_by_severities
- name: load_baseline
  file: src/sevn/skills/security_scan.py
  symbol: load_baseline
- name: normalize_skill_path
  file: src/sevn/skills/security_scan.py
  symbol: normalize_skill_path
- name: parse_skillspector_report
  file: src/sevn/skills/security_scan.py
  symbol: parse_skillspector_report
- name: read_workspace_scan_summary
  file: src/sevn/skills/security_scan.py
  symbol: read_workspace_scan_summary
- name: resolve_skillspector_command
  file: src/sevn/skills/security_scan.py
  symbol: resolve_skillspector_command
- name: run_skillspector_subprocess
  file: src/sevn/skills/security_scan.py
  symbol: run_skillspector_subprocess
- name: scan_skill_path
  file: src/sevn/skills/security_scan.py
  symbol: scan_skill_path
- name: workspace_scan_summary_path
  file: src/sevn/skills/security_scan.py
  symbol: workspace_scan_summary_path
- name: write_workspace_scan_summary
  file: src/sevn/skills/security_scan.py
  symbol: write_workspace_scan_summary
- name: cdp_reachable
  file: src/sevn/skills/social_browser.py
  symbol: cdp_reachable
- name: default_cdp_url
  file: src/sevn/skills/social_browser.py
  symbol: default_cdp_url
- name: dry_run_requested
  file: src/sevn/skills/social_browser.py
  symbol: dry_run_requested
- name: facebook_search_url
  file: src/sevn/skills/social_browser.py
  symbol: facebook_search_url
- name: fetch_page_snapshot
  file: src/sevn/skills/social_browser.py
  symbol: fetch_page_snapshot
- name: host_allowed
  file: src/sevn/skills/social_browser.py
  symbol: host_allowed
- name: logged_in_browser_page
  file: src/sevn/skills/social_browser.py
  symbol: logged_in_browser_page
- name: merge_social_browser_proc_env
  file: src/sevn/skills/social_browser.py
  symbol: merge_social_browser_proc_env
- name: resolve_browser_profile
  file: src/sevn/skills/social_browser.py
  symbol: resolve_browser_profile
- name: session_status_payload
  file: src/sevn/skills/social_browser.py
  symbol: session_status_payload
- name: validate_social_url
  file: src/sevn/skills/social_browser.py
  symbol: validate_social_url
- name: x_search_url
  file: src/sevn/skills/social_browser.py
  symbol: x_search_url
- name: conventional_commits_markdown
  file: src/sevn/standards/conventional_commits.py
  symbol: conventional_commits_markdown
- name: conventional_commits_prompt_block
  file: src/sevn/standards/conventional_commits.py
  symbol: conventional_commits_prompt_block
- name: D1Backend
  file: src/sevn/storage/d1.py
  symbol: D1Backend
- name: D1BackendConfig
  file: src/sevn/storage/d1_backend.py
  symbol: D1BackendConfig
- name: D1StorageBackend
  file: src/sevn/storage/d1_backend.py
  symbol: D1StorageBackend
- name: MigrationError
  file: src/sevn/storage/errors.py
  symbol: MigrationError
- name: StorageError
  file: src/sevn/storage/errors.py
  symbol: StorageError
- name: apply_migrations
  file: src/sevn/storage/migrate.py
  symbol: apply_migrations
- name: is_turn_bundle_day_slug
  file: src/sevn/storage/paths.py
  symbol: is_turn_bundle_day_slug
- name: sevn_db_path
  file: src/sevn/storage/paths.py
  symbol: sevn_db_path
- name: traces_sqlite_path
  file: src/sevn/storage/paths.py
  symbol: traces_sqlite_path
- name: turn_bundle_day_dir
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_day_dir
- name: turn_bundle_day_slug
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_day_slug
- name: turn_bundle_file_path
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_file_path
- name: turn_bundle_index_path
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_index_path
- name: turn_bundles_dir
  file: src/sevn/storage/paths.py
  symbol: turn_bundles_dir
- name: connect_sqlite
  file: src/sevn/storage/sqlite.py
  symbol: connect_sqlite
- name: open_sevn_sqlite
  file: src/sevn/storage/sqlite.py
  symbol: open_sevn_sqlite
- name: BoundToolCallable
  file: src/sevn/tools/base.py
  symbol: BoundToolCallable
- name: FunctionTool
  file: src/sevn/tools/base.py
  symbol: FunctionTool
- name: Tool
  file: src/sevn/tools/base.py
  symbol: Tool
- name: ToolCall
  file: src/sevn/tools/base.py
  symbol: ToolCall
- name: ToolDefinition
  file: src/sevn/tools/base.py
  symbol: ToolDefinition
- name: ToolExecutor
  file: src/sevn/tools/base.py
  symbol: ToolExecutor
- name: enveloped_failure
  file: src/sevn/tools/base.py
  symbol: enveloped_failure
- name: enveloped_success
  file: src/sevn/tools/base.py
  symbol: enveloped_success
- name: maybe_spill_large_payload
  file: src/sevn/tools/base.py
  symbol: maybe_spill_large_payload
- name: browser_tool
  file: src/sevn/tools/browser.py
  symbol: browser_tool
- name: register_browser_tool
  file: src/sevn/tools/browser.py
  symbol: register_browser_tool
- name: set_eval_allowed
  file: src/sevn/tools/browser.py
  symbol: set_eval_allowed
- name: LoadedBodyCache
  file: src/sevn/tools/cache.py
  symbol: LoadedBodyCache
- name: ToolResultCode
  file: src/sevn/tools/codes.py
  symbol: ToolResultCode
- name: coding_agent_invoke
  file: src/sevn/tools/coding_agent_invoke.py
  symbol: coding_agent_invoke
- name: coding_agent_invoke_tool
  file: src/sevn/tools/coding_agent_invoke.py
  symbol: coding_agent_invoke_tool
- name: register_coding_agent_invoke_tool
  file: src/sevn/tools/coding_agent_invoke.py
  symbol: register_coding_agent_invoke_tool
- name: ToolContext
  file: src/sevn/tools/context.py
  symbol: ToolContext
- name: sevn_tool
  file: src/sevn/tools/decorator.py
  symbol: sevn_tool
- name: tool_from_decorated
  file: src/sevn/tools/decorator.py
  symbol: tool_from_decorated
- name: reserved_plugin_row
  file: src/sevn/tools/entrypoints.py
  symbol: reserved_plugin_row
- name: file_evolution_issue_tool
  file: src/sevn/tools/evolution_issues.py
  symbol: file_evolution_issue_tool
- name: register_evolution_issue_tools
  file: src/sevn/tools/evolution_issues.py
  symbol: register_evolution_issue_tools
- name: register_file_ops_tools
  file: src/sevn/tools/file_ops/__init__.py
  symbol: register_file_ops_tools
- name: delete_tool
  file: src/sevn/tools/file_ops/delete.py
  symbol: delete_tool
- name: get_module_docstring_tool
  file: src/sevn/tools/file_ops/docstrings.py
  symbol: get_module_docstring_tool
- name: get_symbol_docstring_tool
  file: src/sevn/tools/file_ops/docstrings.py
  symbol: get_symbol_docstring_tool
- name: list_symbols_tool
  file: src/sevn/tools/file_ops/docstrings.py
  symbol: list_symbols_tool
- name: graphify_prefix_for_search_path
  file: src/sevn/tools/file_ops/graphify_result_prefix.py
  symbol: graphify_prefix_for_search_path
- name: file_info_tool
  file: src/sevn/tools/file_ops/list_glob.py
  symbol: file_info_tool
- name: find_file_tool
  file: src/sevn/tools/file_ops/list_glob.py
  symbol: find_file_tool
- name: glob_tool
  file: src/sevn/tools/file_ops/list_glob.py
  symbol: glob_tool
- name: list_dir_tool
  file: src/sevn/tools/file_ops/list_glob.py
  symbol: list_dir_tool
- name: read_tool
  file: src/sevn/tools/file_ops/read.py
  symbol: read_tool
- name: search_in_file_tool
  file: src/sevn/tools/file_ops/search.py
  symbol: search_in_file_tool
- name: atomic_write_text
  file: src/sevn/tools/file_ops/write.py
  symbol: atomic_write_text
- name: copy_file_tool
  file: src/sevn/tools/file_ops/write.py
  symbol: copy_file_tool
- name: create_folder_tool
  file: src/sevn/tools/file_ops/write.py
  symbol: create_folder_tool
- name: edit_tool
  file: src/sevn/tools/file_ops/write.py
  symbol: edit_tool
- name: move_file_tool
  file: src/sevn/tools/file_ops/write.py
  symbol: move_file_tool
- name: write_tool
  file: src/sevn/tools/file_ops/write.py
  symbol: write_tool
- name: is_integration_mutator
  file: src/sevn/tools/integration_classifier.py
  symbol: is_integration_mutator
- name: legacy_gh_repo_integration_kwargs
  file: src/sevn/tools/integration_gh_repo.py
  symbol: legacy_gh_repo_integration_kwargs
- name: EgressIntegrationProxyClient
  file: src/sevn/tools/integration_proxy_client.py
  symbol: EgressIntegrationProxyClient
- name: IntegrationCredentialRequired
  file: src/sevn/tools/integration_proxy_client.py
  symbol: IntegrationCredentialRequired
- name: build_integration_proxy_client
  file: src/sevn/tools/integration_proxy_client.py
  symbol: build_integration_proxy_client
- name: llm_guard_scan_tool
  file: src/sevn/tools/llm_guard_tool.py
  symbol: llm_guard_scan_tool
- name: register_llm_guard_tool
  file: src/sevn/tools/llm_guard_tool.py
  symbol: register_llm_guard_tool
- name: scan_result_to_tool_payload
  file: src/sevn/tools/llm_guard_tool.py
  symbol: scan_result_to_tool_payload
- name: scanner_tool_enabled
  file: src/sevn/tools/llm_guard_tool.py
  symbol: scanner_tool_enabled
- name: LogLineSpan
  file: src/sevn/tools/log_query.py
  symbol: LogLineSpan
- name: LogQueryResult
  file: src/sevn/tools/log_query.py
  symbol: LogQueryResult
- name: coerce_log_range_args
  file: src/sevn/tools/log_query.py
  symbol: coerce_log_range_args
- name: list_available_log_files
  file: src/sevn/tools/log_query.py
  symbol: list_available_log_files
- name: log_query_tool
  file: src/sevn/tools/log_query.py
  symbol: log_query_tool
- name: parse_log_ranges
  file: src/sevn/tools/log_query.py
  symbol: parse_log_ranges
- name: query_log_lines
  file: src/sevn/tools/log_query.py
  symbol: query_log_lines
- name: register_log_query_tool
  file: src/sevn/tools/log_query.py
  symbol: register_log_query_tool
- name: resolve_log_path
  file: src/sevn/tools/log_query.py
  symbol: resolve_log_path
- name: resolve_sevn_log_path
  file: src/sevn/tools/log_query.py
  symbol: resolve_sevn_log_path
- name: summarize_log_result
  file: src/sevn/tools/log_query.py
  symbol: summarize_log_result
- name: tail_log_lines
  file: src/sevn/tools/log_query.py
  symbol: tail_log_lines
- name: SevnMcpStdioClient
  file: src/sevn/tools/mcp_stdio_client.py
  symbol: SevnMcpStdioClient
- name: build_mcp_stdio_client
  file: src/sevn/tools/mcp_stdio_client.py
  symbol: build_mcp_stdio_client
- name: discover_mcp_tool_definitions
  file: src/sevn/tools/mcp_stdio_client.py
  symbol: discover_mcp_tool_definitions
- name: list_tools_from_server
  file: src/sevn/tools/mcp_stdio_client.py
  symbol: list_tools_from_server
- name: federated_memory_search
  file: src/sevn/tools/memory_tools.py
  symbol: federated_memory_search
- name: get_memory_row
  file: src/sevn/tools/memory_tools.py
  symbol: get_memory_row
- name: memory_get_tool
  file: src/sevn/tools/memory_tools.py
  symbol: memory_get_tool
- name: memory_search_tool
  file: src/sevn/tools/memory_tools.py
  symbol: memory_search_tool
- name: memory_store_tool
  file: src/sevn/tools/memory_tools.py
  symbol: memory_store_tool
- name: register_memory_tools
  file: src/sevn/tools/memory_tools.py
  symbol: register_memory_tools
- name: store_memory_row
  file: src/sevn/tools/memory_tools.py
  symbol: store_memory_row
- name: request_escalation_pydantic
  file: src/sevn/tools/meta_escalation.py
  symbol: request_escalation_pydantic
- name: request_escalation_pydantic_tool
  file: src/sevn/tools/meta_escalation.py
  symbol: request_escalation_pydantic_tool
- name: ListRegistryImplementation
  file: src/sevn/tools/meta_loaders.py
  symbol: ListRegistryImplementation
- name: LoadSkillImplementation
  file: src/sevn/tools/meta_loaders.py
  symbol: LoadSkillImplementation
- name: LoadToolImplementation
  file: src/sevn/tools/meta_loaders.py
  symbol: LoadToolImplementation
- name: attach_meta_loaders
  file: src/sevn/tools/meta_loaders.py
  symbol: attach_meta_loaders
- name: message_tool
  file: src/sevn/tools/outbound.py
  symbol: message_tool
- name: register_outbound_tools
  file: src/sevn/tools/outbound.py
  symbol: register_outbound_tools
- name: send_file_tool
  file: src/sevn/tools/outbound.py
  symbol: send_file_tool
- name: tts_tool
  file: src/sevn/tools/outbound.py
  symbol: tts_tool
- name: WorkspacePathError
  file: src/sevn/tools/paths.py
  symbol: WorkspacePathError
- name: display_path_for_tool
  file: src/sevn/tools/paths.py
  symbol: display_path_for_tool
- name: ensure_path_not_under_llmignore
  file: src/sevn/tools/paths.py
  symbol: ensure_path_not_under_llmignore
- name: filter_visible_entries
  file: src/sevn/tools/paths.py
  symbol: filter_visible_entries
- name: rebase_checkout_absolute_path
  file: src/sevn/tools/paths.py
  symbol: rebase_checkout_absolute_path
- name: resolve_artifact_tool_path
  file: src/sevn/tools/paths.py
  symbol: resolve_artifact_tool_path
- name: resolve_tool_path
  file: src/sevn/tools/paths.py
  symbol: resolve_tool_path
- name: resolve_workspace_relative_path
  file: src/sevn/tools/paths.py
  symbol: resolve_workspace_relative_path
- name: AllowAllPermissionPolicy
  file: src/sevn/tools/permissions.py
  symbol: AllowAllPermissionPolicy
- name: AttributeBasedPermissionPolicy
  file: src/sevn/tools/permissions.py
  symbol: AttributeBasedPermissionPolicy
- name: DenyingPermissionPolicy
  file: src/sevn/tools/permissions.py
  symbol: DenyingPermissionPolicy
- name: PermissionPolicy
  file: src/sevn/tools/permissions.py
  symbol: PermissionPolicy
- name: apply_permission_scope_narrowing
  file: src/sevn/tools/permissions.py
  symbol: apply_permission_scope_narrowing
- name: resolve_principal
  file: src/sevn/tools/permissions.py
  symbol: resolve_principal
- name: BackgroundJob
  file: src/sevn/tools/process.py
  symbol: BackgroundJob
- name: list_session_jobs
  file: src/sevn/tools/process.py
  symbol: list_session_jobs
- name: process_tool
  file: src/sevn/tools/process.py
  symbol: process_tool
- name: register_process_tools
  file: src/sevn/tools/process.py
  symbol: register_process_tools
- name: reset_process_store_for_tests
  file: src/sevn/tools/process.py
  symbol: reset_process_store_for_tests
- name: readiness_for_tool
  file: src/sevn/tools/readiness.py
  symbol: readiness_for_tool
- name: readiness_notes_for_tools
  file: src/sevn/tools/readiness.py
  symbol: readiness_notes_for_tools
- name: set_tool_readiness_override
  file: src/sevn/tools/readiness.py
  symbol: set_tool_readiness_override
- name: McpUnavailableTool
  file: src/sevn/tools/registry.py
  symbol: McpUnavailableTool
- name: ToolSet
  file: src/sevn/tools/registry.py
  symbol: ToolSet
- name: TracingToolExecutor
  file: src/sevn/tools/registry.py
  symbol: TracingToolExecutor
- name: build_session_registry
  file: src/sevn/tools/registry.py
  symbol: build_session_registry
- name: combine_registry_version
  file: src/sevn/tools/registry.py
  symbol: combine_registry_version
- name: load_plugin_tools
  file: src/sevn/tools/registry.py
  symbol: load_plugin_tools
- name: merge_skill_manifests
  file: src/sevn/tools/registry.py
  symbol: merge_skill_manifests
- name: plugin_entrypoint_allowed
  file: src/sevn/tools/registry.py
  symbol: plugin_entrypoint_allowed
- name: register_feature_stubs
  file: src/sevn/tools/registry.py
  symbol: register_feature_stubs
- name: snapshot_tool_set
  file: src/sevn/tools/registry.py
  symbol: snapshot_tool_set
- name: apply_readiness_from_bindings
  file: src/sevn/tools/runtime_bindings_factory.py
  symbol: apply_readiness_from_bindings
- name: build_runtime_tool_bindings
  file: src/sevn/tools/runtime_bindings_factory.py
  symbol: build_runtime_tool_bindings
- name: IntegrationProxyClient
  file: src/sevn/tools/runtime_dispatch.py
  symbol: IntegrationProxyClient
- name: McpStdioClient
  file: src/sevn/tools/runtime_dispatch.py
  symbol: McpStdioClient
- name: McpStdioTool
  file: src/sevn/tools/runtime_dispatch.py
  symbol: McpStdioTool
- name: RuntimeToolBindings
  file: src/sevn/tools/runtime_dispatch.py
  symbol: RuntimeToolBindings
- name: SandboxExecutorClient
  file: src/sevn/tools/runtime_dispatch.py
  symbol: SandboxExecutorClient
- name: make_integration_call_tool
  file: src/sevn/tools/runtime_dispatch.py
  symbol: make_integration_call_tool
- name: make_sandbox_exec_tool
  file: src/sevn/tools/runtime_dispatch.py
  symbol: make_sandbox_exec_tool
- name: register_semantic_search_tool
  file: src/sevn/tools/semantic_search.py
  symbol: register_semantic_search_tool
- name: run_semantic_search
  file: src/sevn/tools/semantic_search.py
  symbol: run_semantic_search
- name: semantic_search_tool
  file: src/sevn/tools/semantic_search.py
  symbol: semantic_search_tool
- name: witchcraft_tool_enabled
  file: src/sevn/tools/semantic_search.py
  symbol: witchcraft_tool_enabled
- name: SkillsBackedLoadSkillTool
  file: src/sevn/tools/skills_register.py
  symbol: SkillsBackedLoadSkillTool
- name: register_skill_tools
  file: src/sevn/tools/skills_register.py
  symbol: register_skill_tools
- name: register_skill_tools_unconfigured
  file: src/sevn/tools/skills_register.py
  symbol: register_skill_tools_unconfigured
- name: prune_orphan_tool_result_dirs
  file: src/sevn/tools/spill_gc.py
  symbol: prune_orphan_tool_result_dirs
- name: register_subagent_spawn_tools
  file: src/sevn/tools/subagent_spawn.py
  symbol: register_subagent_spawn_tools
- name: spawn_subagent_tool
  file: src/sevn/tools/subagent_spawn.py
  symbol: spawn_subagent_tool
- name: TerminalSession
  file: src/sevn/tools/terminal.py
  symbol: TerminalSession
- name: register_terminal_tools
  file: src/sevn/tools/terminal.py
  symbol: register_terminal_tools
- name: reset_terminal_store_for_tests
  file: src/sevn/tools/terminal.py
  symbol: reset_terminal_store_for_tests
- name: terminal_close_tool
  file: src/sevn/tools/terminal.py
  symbol: terminal_close_tool
- name: terminal_run_tool
  file: src/sevn/tools/terminal.py
  symbol: terminal_run_tool
- name: terminal_spawn_tool
  file: src/sevn/tools/terminal.py
  symbol: terminal_spawn_tool
- name: history_tool
  file: src/sevn/tools/transcript.py
  symbol: history_tool
- name: read_transcript_tool
  file: src/sevn/tools/transcript.py
  symbol: read_transcript_tool
- name: ValidationIssue
  file: src/sevn/tools/validation.py
  symbol: ValidationIssue
- name: coerce_string_scalars_to_schema
  file: src/sevn/tools/validation.py
  symbol: coerce_string_scalars_to_schema
- name: validate_json_schema_subset
  file: src/sevn/tools/validation.py
  symbol: validate_json_schema_subset
- name: build_egress_web_headers
  file: src/sevn/tools/web.py
  symbol: build_egress_web_headers
- name: get_page_content_tool
  file: src/sevn/tools/web.py
  symbol: get_page_content_tool
- name: proxy_post_json
  file: src/sevn/tools/web.py
  symbol: proxy_post_json
- name: register_web_tools
  file: src/sevn/tools/web.py
  symbol: register_web_tools
- name: reset_proxy_http_client_for_tests
  file: src/sevn/tools/web.py
  symbol: reset_proxy_http_client_for_tests
- name: serp_tool
  file: src/sevn/tools/web.py
  symbol: serp_tool
- name: web_fetch_tool
  file: src/sevn/tools/web.py
  symbol: web_fetch_tool
- name: web_search_tool
  file: src/sevn/tools/web.py
  symbol: web_search_tool
- name: register_write_workspace_md
  file: src/sevn/tools/workspace_files.py
  symbol: register_write_workspace_md
- name: write_workspace_md
  file: src/sevn/tools/workspace_files.py
  symbol: write_workspace_md
- name: OtlpExportTarget
  file: src/sevn/tracing/otel_pipeline.py
  symbol: OtlpExportTarget
- name: configure_gateway_otel
  file: src/sevn/tracing/otel_pipeline.py
  symbol: configure_gateway_otel
- name: configure_gateway_otel_async
  file: src/sevn/tracing/otel_pipeline.py
  symbol: configure_gateway_otel_async
- name: configure_proxy_otel
  file: src/sevn/tracing/otel_pipeline.py
  symbol: configure_proxy_otel
- name: instrumentation_capability
  file: src/sevn/tracing/otel_pipeline.py
  symbol: instrumentation_capability
- name: is_otel_export_configured
  file: src/sevn/tracing/otel_pipeline.py
  symbol: is_otel_export_configured
- name: reset_otel_pipeline_for_tests
  file: src/sevn/tracing/otel_pipeline.py
  symbol: reset_otel_pipeline_for_tests
- name: resolve_otlp_targets
  file: src/sevn/tracing/otel_pipeline.py
  symbol: resolve_otlp_targets
- name: resolve_trace_sink_token
  file: src/sevn/tracing/trace_secrets_resolve.py
  symbol: resolve_trace_sink_token
- name: RunCreateBody
  file: src/sevn/triggers/api_router.py
  symbol: RunCreateBody
- name: build_api_router
  file: src/sevn/triggers/api_router.py
  symbol: build_api_router
- name: triggers_api_auth_required
  file: src/sevn/triggers/auth.py
  symbol: triggers_api_auth_required
- name: verify_triggers_api_bearer
  file: src/sevn/triggers/auth.py
  symbol: verify_triggers_api_bearer
- name: coding_agent_loop_trigger
  file: src/sevn/triggers/coding_agent_loop.py
  symbol: coding_agent_loop_trigger
- name: mine_session_trajectories
  file: src/sevn/triggers/coding_agent_loop.py
  symbol: mine_session_trajectories
- name: CronJobDetail
  file: src/sevn/triggers/cron.py
  symbol: CronJobDetail
- name: CronJobRow
  file: src/sevn/triggers/cron.py
  symbol: CronJobRow
- name: SqliteCronStore
  file: src/sevn/triggers/cron.py
  symbol: SqliteCronStore
- name: add_cron_job
  file: src/sevn/triggers/cron.py
  symbol: add_cron_job
- name: add_reminder
  file: src/sevn/triggers/cron.py
  symbol: add_reminder
- name: compute_next_fire_ns
  file: src/sevn/triggers/cron.py
  symbol: compute_next_fire_ns
- name: cron_job_to_dict
  file: src/sevn/triggers/cron.py
  symbol: cron_job_to_dict
- name: cron_job_to_list_dict
  file: src/sevn/triggers/cron.py
  symbol: cron_job_to_list_dict
- name: cron_tick
  file: src/sevn/triggers/cron.py
  symbol: cron_tick
- name: delete_cron_job
  file: src/sevn/triggers/cron.py
  symbol: delete_cron_job
- name: edit_cron_job
  file: src/sevn/triggers/cron.py
  symbol: edit_cron_job
- name: format_next_fire_at_iso
  file: src/sevn/triggers/cron.py
  symbol: format_next_fire_at_iso
- name: list_cron_jobs
  file: src/sevn/triggers/cron.py
  symbol: list_cron_jobs
- name: prune_webhook_dedupe_expired
  file: src/sevn/triggers/dedupe.py
  symbol: prune_webhook_dedupe_expired
- name: try_insert_webhook_dedupe
  file: src/sevn/triggers/dedupe.py
  symbol: try_insert_webhook_dedupe
- name: trigger_runs_dir
  file: src/sevn/triggers/delivery.py
  symbol: trigger_runs_dir
- name: write_log_result
  file: src/sevn/triggers/delivery.py
  symbol: write_log_result
- name: TriggerDispatchGate
  file: src/sevn/triggers/dispatcher.py
  symbol: TriggerDispatchGate
- name: agent_dispatch_kwargs
  file: src/sevn/triggers/dispatcher.py
  symbol: agent_dispatch_kwargs
- name: dispatch_notify_only
  file: src/sevn/triggers/dispatcher.py
  symbol: dispatch_notify_only
- name: dispatch_run
  file: src/sevn/triggers/dispatcher.py
  symbol: dispatch_run
- name: TriggerPluginHookSurface
  file: src/sevn/triggers/hooks_protocol.py
  symbol: TriggerPluginHookSurface
- name: inbox_dir
  file: src/sevn/triggers/inbox.py
  symbol: inbox_dir
- name: maybe_spill_prompt_to_inbox
  file: src/sevn/triggers/inbox.py
  symbol: maybe_spill_prompt_to_inbox
- name: prune_inbox_spill
  file: src/sevn/triggers/inbox.py
  symbol: prune_inbox_spill
- name: DispatchRequest
  file: src/sevn/triggers/request.py
  symbol: DispatchRequest
- name: NotifyHandle
  file: src/sevn/triggers/request.py
  symbol: NotifyHandle
- name: ResultChannel
  file: src/sevn/triggers/request.py
  symbol: ResultChannel
- name: RunHandle
  file: src/sevn/triggers/request.py
  symbol: RunHandle
- name: effective_max_concurrent
  file: src/sevn/triggers/settings.py
  symbol: effective_max_concurrent
- name: effective_max_inline_bytes
  file: src/sevn/triggers/settings.py
  symbol: effective_max_inline_bytes
- name: GitHubPayload
  file: src/sevn/triggers/sources/github.py
  symbol: GitHubPayload
- name: compose_github_prompt
  file: src/sevn/triggers/sources/github.py
  symbol: compose_github_prompt
- name: compose_prompt
  file: src/sevn/triggers/sources/github.py
  symbol: compose_prompt
- name: verify_github_payload
  file: src/sevn/triggers/sources/github.py
  symbol: verify_github_payload
- name: build_webhook_router
  file: src/sevn/triggers/webhook_router.py
  symbol: build_webhook_router
- name: maybe_import_github_issue_event
  file: src/sevn/triggers/webhook_router.py
  symbol: maybe_import_github_issue_event
- name: resolve_webhook_signing_secret
  file: src/sevn/triggers/webhook_secret.py
  symbol: resolve_webhook_signing_secret
- name: trigger_run_ws_topic
  file: src/sevn/triggers/ws_topics.py
  symbol: trigger_run_ws_topic
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
- name: mission_subagent_kill
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: mission_subagent_kill
- name: mission_subagents_get
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: mission_subagents_get
- name: mission_subagents_kill_all
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: mission_subagents_kill_all
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
- name: tracing_logfire_get
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: tracing_logfire_get
- name: tracing_logfire_put
  file: src/sevn/ui/dashboard/api/ops.py
  symbol: tracing_logfire_put
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
- name: generate_dashboard_login_password
  file: src/sevn/ui/dashboard/dashboard_password.py
  symbol: generate_dashboard_login_password
- name: resolve_dashboard_login_password_ref
  file: src/sevn/ui/dashboard/dashboard_password.py
  symbol: resolve_dashboard_login_password_ref
- name: validate_dashboard_login_password_plaintext
  file: src/sevn/ui/dashboard/dashboard_password.py
  symbol: validate_dashboard_login_password_plaintext
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
- name: EdgeTtsBackend
  file: src/sevn/voice/backends.py
  symbol: EdgeTtsBackend
- name: KokoroBackend
  file: src/sevn/voice/backends.py
  symbol: KokoroBackend
- name: SpeechToTextBackend
  file: src/sevn/voice/backends.py
  symbol: SpeechToTextBackend
- name: SynthesisResult
  file: src/sevn/voice/backends.py
  symbol: SynthesisResult
- name: TextToSpeechBackend
  file: src/sevn/voice/backends.py
  symbol: TextToSpeechBackend
- name: TranscriptionResult
  file: src/sevn/voice/backends.py
  symbol: TranscriptionResult
- name: WhisperCppBackend
  file: src/sevn/voice/backends.py
  symbol: WhisperCppBackend
- name: build_stt_backend
  file: src/sevn/voice/backends.py
  symbol: build_stt_backend
- name: build_tts_backend
  file: src/sevn/voice/backends.py
  symbol: build_tts_backend
- name: validate_voice_backend_tags
  file: src/sevn/voice/backends.py
  symbol: validate_voice_backend_tags
- name: whisper_cpp_missing_prereqs
  file: src/sevn/voice/backends.py
  symbol: whisper_cpp_missing_prereqs
- name: voice_http_base_url
  file: src/sevn/voice/egress.py
  symbol: voice_http_base_url
- name: VoiceRuntimeSettings
  file: src/sevn/voice/factory.py
  symbol: VoiceRuntimeSettings
- name: build_stt_pipeline
  file: src/sevn/voice/factory.py
  symbol: build_stt_pipeline
- name: build_tts_pipeline
  file: src/sevn/voice/factory.py
  symbol: build_tts_pipeline
- name: maybe_preload_local_tts
  file: src/sevn/voice/factory.py
  symbol: maybe_preload_local_tts
- name: probe_voice_backends
  file: src/sevn/voice/factory.py
  symbol: probe_voice_backends
- name: prune_stale_tts_files
  file: src/sevn/voice/factory.py
  symbol: prune_stale_tts_files
- name: resolve_effective_tts_mode
  file: src/sevn/voice/factory.py
  symbol: resolve_effective_tts_mode
- name: voice_enabled
  file: src/sevn/voice/factory.py
  symbol: voice_enabled
- name: voice_runtime_settings
  file: src/sevn/voice/factory.py
  symbol: voice_runtime_settings
- name: maybe_resolve_whisper_model_env
  file: src/sevn/voice/host_deps.py
  symbol: maybe_resolve_whisper_model_env
- name: provision_voice_deps
  file: src/sevn/voice/host_deps.py
  symbol: provision_voice_deps
- name: voice_host_dep_ids
  file: src/sevn/voice/host_deps.py
  symbol: voice_host_dep_ids
- name: compile_voice_trigger_patterns
  file: src/sevn/voice/keywords.py
  symbol: compile_voice_trigger_patterns
- name: user_text_matches_voice_trigger
  file: src/sevn/voice/keywords.py
  symbol: user_text_matches_voice_trigger
- name: SpeechToTextBackend
  file: src/sevn/voice/stt.py
  symbol: SpeechToTextBackend
- name: SpeechToTextPipeline
  file: src/sevn/voice/stt.py
  symbol: SpeechToTextPipeline
- name: transcribe_placeholder
  file: src/sevn/voice/stt.py
  symbol: transcribe_placeholder
- name: emit_voice_event
  file: src/sevn/voice/trace_events.py
  symbol: emit_voice_event
- name: TextToSpeechBackend
  file: src/sevn/voice/tts.py
  symbol: TextToSpeechBackend
- name: TextToSpeechPipeline
  file: src/sevn/voice/tts.py
  symbol: TextToSpeechPipeline
- name: TtsSynthOutcome
  file: src/sevn/voice/tts.py
  symbol: TtsSynthOutcome
- name: speak_placeholder
  file: src/sevn/voice/tts.py
  symbol: speak_placeholder
- name: WhisperModelSpec
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: WhisperModelSpec
- name: default_whisper_model_cache_dir
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: default_whisper_model_cache_dir
- name: ensure_whisper_model
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: ensure_whisper_model
- name: is_whisper_model_cached
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: is_whisper_model_cached
- name: model_path_for
  file: src/sevn/voice/whisper_model_provisioner.py
  symbol: model_path_for
- name: artifact_output_prefix
  file: src/sevn/workspace/artifact_output.py
  symbol: artifact_output_prefix
- name: artifact_output_prefix_from_env
  file: src/sevn/workspace/artifact_output.py
  symbol: artifact_output_prefix_from_env
- name: is_protected_structured_root_path
  file: src/sevn/workspace/artifact_output.py
  symbol: is_protected_structured_root_path
- name: normalise_output_dir_rel
  file: src/sevn/workspace/artifact_output.py
  symbol: normalise_output_dir_rel
- name: path_is_under_output_prefix
  file: src/sevn/workspace/artifact_output.py
  symbol: path_is_under_output_prefix
- name: rebase_artifact_relative_path
  file: src/sevn/workspace/artifact_output.py
  symbol: rebase_artifact_relative_path
- name: WorkspaceLayout
  file: src/sevn/workspace/layout.py
  symbol: WorkspaceLayout
- name: WorkspaceLayoutValidationResult
  file: src/sevn/workspace/layout_validate.py
  symbol: WorkspaceLayoutValidationResult
- name: validate_workspace_layout
  file: src/sevn/workspace/layout_validate.py
  symbol: validate_workspace_layout
- name: validate_workspace_layout_at_boot
  file: src/sevn/workspace/layout_validate.py
  symbol: validate_workspace_layout_at_boot
- name: UnsafeWorkspaceRootError
  file: src/sevn/workspace/safe_root.py
  symbol: UnsafeWorkspaceRootError
- name: is_sevn_package_checkout
  file: src/sevn/workspace/safe_root.py
  symbol: is_sevn_package_checkout
- name: reject_package_checkout_content_root
  file: src/sevn/workspace/safe_root.py
  symbol: reject_package_checkout_content_root
- name: sync_source_copy
  file: src/sevn/workspace/source_copy.py
  symbol: sync_source_copy
- name: merge_tools_md_body
  file: src/sevn/workspace/tools_md.py
  symbol: merge_tools_md_body
- name: read_tools_md_body
  file: src/sevn/workspace/tools_md.py
  symbol: read_tools_md_body
- name: render_registry_markdown
  file: src/sevn/workspace/tools_md.py
  symbol: render_registry_markdown
- name: sync_tools_md
  file: src/sevn/workspace/tools_md.py
  symbol: sync_tools_md
- name: sync_tools_md_for_config
  file: src/sevn/workspace/tools_md.py
  symbol: sync_tools_md_for_config
specs: []
personas: []
prd_profile: null
---

## Purpose

Deliver the lowest layer every later spec assumes: a src/sevn/ package layout, uv-managed Python 3.12+ project (hatchling build backend), a root Makefile as the single recurring-command surface, pre-c

Implementation spans [`src/sevn`](src/sevn/__init__.py). The frontmatter `interfaces:` block is code-owned (refresh with `make about-docs-extract DOC_ID=spec-00-foundation`).

<!-- HUMAN-INPUT[owner=operator]: Author the full normative contract for this mega-spec — do not hand-expand the whole-tree interfaces dump. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`default_codemode_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`install_monty_resource_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`lambda_rlm_filter`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`to_dspy_tools`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`EgressBridgeContext`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_anthropic_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_httpx_event_hooks`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_openai_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_httpx_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_llm_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_proxy_transport_request`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`resolve_proxy_shared_secret`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- _…and 3973 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`default_codemode_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`install_monty_resource_limits`](src/sevn/agent/adapters/_monty_limits.py) — `src/sevn/agent/adapters/_monty_limits.py`
- [`lambda_rlm_filter`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`to_dspy_tools`](src/sevn/agent/adapters/dspy_adapter.py) — `src/sevn/agent/adapters/dspy_adapter.py`
- [`EgressBridgeContext`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_anthropic_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_httpx_event_hooks`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`build_sevn_openai_client`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_httpx_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_llm_request_snapshot`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`redact_proxy_transport_request`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- [`resolve_proxy_shared_secret`](src/sevn/agent/adapters/egress_bridge.py) — `src/sevn/agent/adapters/egress_bridge.py`
- _…and 3973 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn`](src/sevn/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn`](src/sevn/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
