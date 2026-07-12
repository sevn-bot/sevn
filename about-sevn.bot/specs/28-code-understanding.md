---
id: spec-28-code-understanding
kind: spec
title: Code understanding — Spec
status: done
owner: Alex
summary: 'Deliver the code-orientation stack the coding companion PRD names: five
  orthogonal capabilities (MYCODE, Memgraph CGR, code-review-graph (SQLite MCP), roam-code,
  Graphify) that Triager and executors c'
last_updated: '2026-07-12'
fingerprint: sha256:5a97e9841a414ba088717f40956b00e55c59c77add891779e0555da9bb2c9f93
related: []
sources:
- src/sevn/code_understanding/**
parent_prd: prd-08-coding-companion
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-06-secrets
- spec-07-egress-proxy
- spec-08-sandbox
- spec-09-security-scanner
- spec-11-tools-registry
- spec-12-skills-system
- spec-13-rlm-triager
build_phase: null
interfaces:
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
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Purpose.

## Public Interface

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Public Interface.

## Data Model

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Data Model.

## Internal Architecture

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Internal Architecture.

## Behavior

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Behavior.

## Failure Modes

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Failure Modes.

## Test Strategy

Offline scaffold for Code understanding — Spec (spec-28-code-understanding) — Test Strategy.
