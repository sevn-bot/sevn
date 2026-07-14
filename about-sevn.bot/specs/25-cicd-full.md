---
id: spec-25-cicd-full
kind: spec
title: CI/CD (mature pipeline) — Spec
status: scaffold
owner: Alex
summary: 'Grow spec-00-foundation’s minimal verify loop into a phase-strict delivery
  pipeline: broader CI matrices, checked-in Dockerfile validation for spec-08-sandbox
  (and any ASGI image built for spec-07-egr'
last_updated: '2026-07-14'
fingerprint: sha256:4046eea79e99f21fdef5bd3ee60f2384aa6fecc4400df1e94da1766386c002b8
related: []
sources:
- .github/workflows/**
- wave-orchestrator/**
- src/sevn/docs/**
parent_prd: prd-06-setup-and-operations
depends_on:
- spec-00-foundation
build_phase: null
interfaces:
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
---

## Purpose

Grow spec-00-foundation’s minimal verify loop into a phase-strict delivery pipeline: broader CI matrices, checked-in Dockerfile validation for spec-08-sandbox (and any ASGI image built for spec-07-egr

Implementation spans [`src/sevn`](src/sevn/__init__.py), `wave-orchestrator/` (gitignored local operator tree when present), and [`.github/workflows/ci.yml`](.github/workflows/ci.yml). The frontmatter `interfaces:` block is code-owned (refresh with `make about-docs-extract DOC_ID=spec-25-cicd-full`).

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

See **Implemented by** and [`src/sevn`](src/sevn/__init__.py), `wave-orchestrator/`, [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn`](src/sevn/__init__.py), `wave-orchestrator/`, and [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
