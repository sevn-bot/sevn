---
id: spec-11-tools-registry
kind: spec
title: Tools registry — Spec
status: scaffold
owner: Alex
summary: 'Own the Layer-3 tool callables and Layer-2 framework adapters that every
  executor tier uses: one implementation per tool name, registered in a session-scoped
  ToolSet, exposed to LLM frameworks without'
last_updated: '2026-07-14'
fingerprint: sha256:207556c8650740a8335885e8fa26f8946cef7f269b331f4957fbb74207414f2c
related: []
sources:
- src/sevn/tools/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-05-llm-transports
- spec-06-secrets
- spec-08-sandbox
- spec-09-security-scanner
- spec-10-schema-ontology
build_phase: null
interfaces:
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
specs: []
personas: []
prd_profile: null
---


## Purpose

Own the Layer-3 tool callables and Layer-2 framework adapters that every executor tier uses: one implementation per tool name, registered in a session-scoped ToolSet, exposed to LLM frameworks without

Primary code trees: [`src/sevn/tools`](src/sevn/tools/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`BoundToolCallable`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`FunctionTool`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`Tool`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`ToolCall`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`ToolDefinition`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`ToolExecutor`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`enveloped_failure`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`enveloped_success`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`maybe_spill_large_payload`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`browser_tool`](src/sevn/tools/browser.py) — `src/sevn/tools/browser.py`
- [`register_browser_tool`](src/sevn/tools/browser.py) — `src/sevn/tools/browser.py`
- [`set_eval_allowed`](src/sevn/tools/browser.py) — `src/sevn/tools/browser.py`
- _…and 143 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`BoundToolCallable`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`FunctionTool`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`Tool`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`ToolCall`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`ToolDefinition`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`ToolExecutor`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`enveloped_failure`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`enveloped_success`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`maybe_spill_large_payload`](src/sevn/tools/base.py) — `src/sevn/tools/base.py`
- [`browser_tool`](src/sevn/tools/browser.py) — `src/sevn/tools/browser.py`
- [`register_browser_tool`](src/sevn/tools/browser.py) — `src/sevn/tools/browser.py`
- [`set_eval_allowed`](src/sevn/tools/browser.py) — `src/sevn/tools/browser.py`
- _…and 143 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/tools`](src/sevn/tools/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/tools`](src/sevn/tools/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
