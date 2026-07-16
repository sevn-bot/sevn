---
id: spec-25-cicd-full
kind: spec
title: CI/CD (mature pipeline) — Spec
status: done
owner: Alex
summary: 'Grow spec-00-foundation’s minimal verify loop into a phase-strict delivery
  pipeline: broader CI matrices, checked-in Dockerfile validation for spec-08-sandbox
  (and any ASGI image built for spec-07-egr'
last_updated: '2026-07-16'
fingerprint: sha256:7843346af2aadbae285f99f907790ba432e28e534f73e4951f064d20e9ccd9c0
related: []
sources:
- .github/workflows/**
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

Document the **mature delivery pipeline** grown from spec-00-foundation: GitHub Actions
workflows, composable Makefile CI tiers, resumable full gates, path-aware partial gates,
and docs/skills/infra checks that block regressions before merge.

## Public Interface

| Target | Role |
|--------|------|
| `make ci` | Full pre-merge gate (all tiers) |
| `make ci-resume` / `make ci-reset` | Resumable / reset CI checkpoint |
| `make ci-core` | lockcheck, lint, typecheck, pyright, test, doctest, security, build, doctor |
| `make ci-infra` | config-schema, onboarding schemas, git guards, manifests |
| `make ci-docs` | about-site, readme, changelog, skw spec/prd gates, telegram menu docs |
| `make ci-skills` | skillspector + skill inventory checks |
| `make ci-parity` | code-index, deploy report parity |
| `make ci-affected` / `make ci-changed` | Path-aware partial gates |
| `make ci-quality` | Advisory (ruff ratchet, vulture, codespell — not in `make ci`) |
| `.github/workflows/ci.yml` | Primary CI workflow |
| `.github/workflows/ci-cd.yml` | Release / CD workflow |
| `scripts/ci_resume.sh` | Ordered `CI_STEPS` driver |

Docs tooling in scope: `src/sevn/docs/about/check.py` (`check_about_docs`),
`make about-docs-check` (chains `make spec-check` + `make prd-check`),
`make changelog-check` (Keep a Changelog + Unreleased datestamp via `skw.changelog_validate`).

## Data Model

### `CI_STEPS` (32 ordered steps)

Defined in root `Makefile` — consumed by `make ci-resume` via `scripts/ci_resume.sh`.
First infra step includes `make config-schema` against `infra/sevn.schema.json` goldens.

### Workflow matrix (`.github/workflows/`)

| Workflow | Purpose |
|----------|---------|
| `ci.yml` | Main CI (invokes make targets) |
| `ci-supplementary.yml` | Supplementary checks |
| `ci-cd.yml` | CD / release |
| `docker.yml` | Container build validation |
| `style-guide-pages.yml` | Style guide site |

### Partial gate inputs

`SEVN_CI_BASE` (default `origin/main`), `SEVN_PYTEST_JOBS` for xdist control.

## Internal Architecture

```text
PR / push → GitHub Actions → make ci (or subset)
    → ci-core (Python quality + test + build)
    → ci-infra (schemas, guards)
    → ci-docs (about/readme/changelog/menu)
    → ci-skills
    → ci-parity
Local iteration → make ci-affected / ci-changed → subset only
Final wave loop → make ci-resume until all steps pass
```

Wave agents: mid-wave **`make ci-affected`** only; wave boundary **`make ci`** or **`make ci-resume`**.

## Behavior

1. **`make lockcheck`** — `uv lock --check` first in CI core.
2. **`make lint`** / **`make typecheck`** — mandatory on Python changes.
3. **`make test`** — full pytest; parallel via xdist unless `SEVN_PYTEST_JOBS=0`.
4. **`make config-schema`** — JSON Schema vs fixture configs.
5. **`make about-docs-check`** — about-sevn.bot doc integrity, status honesty, and skw folder gates (`spec-check`, `prd-check`).
6. **`make changelog-check`** — Keep a Changelog + Unreleased datestamp rules (`skw.changelog_validate`).
7. **`make ci-resume`** — stops at first failure; reruns skip passed steps (checkpoint not re-verifying earlier steps — finish with clean `make ci` before merge).

## Failure Modes

| Failure | Signal |
|---------|--------|
| Any CI step non-zero | `make ci` / Actions job red |
| Checkpoint stale after early-step regression | Operator runs `make ci-reset` then full gate |
| Schema drift | `make config-schema` fails |
| Doc regression | `make about-docs-check`, `make spec-check`, `make prd-check`, or `make readme-check` fails |
| Git guard missing | `make check-git-guards` fails (blocks destructive clean) |

## Test Strategy

| Gate | Validates |
|------|-----------|
| `make ci` | Entire pipeline (~12–15 min) |
| `make ci-resume` | Iterative final-wave fix loop |
| `tests/docs/about/` | About-docs contracts |
| `spec-kit-wave/tests/` | skw validators + sync contracts (`make spec-kit-wave-test` in `ci-docs`; `spec-check` / `prd-check` wired via `about-docs-check`) |
| `.github/workflows/*.yml` | CI orchestration smoke on every push |
