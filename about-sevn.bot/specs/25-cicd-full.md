---
id: spec-25-cicd-full
kind: spec
title: CI/CD (mature pipeline) — Spec
status: done
owner: Alex
summary: 'Grow spec-00-foundation’s minimal verify loop into a phase-strict delivery
  pipeline: broader CI matrices, checked-in Dockerfile validation for spec-08-sandbox
  (and any ASGI image built for spec-07-egr'
last_updated: '2026-08-06'
fingerprint: sha256:71318ef4d8122c7057522c531120a93963397894ada16777edc60d34e864fb64
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
- name: Document
  file: src/sevn/docs/faq.py
  symbol: Document
- name: Question
  file: src/sevn/docs/faq.py
  symbol: Question
- name: Reference
  file: src/sevn/docs/faq.py
  symbol: Reference
- name: Section
  file: src/sevn/docs/faq.py
  symbol: Section
- name: load_document
  file: src/sevn/docs/faq.py
  symbol: load_document
- name: render_markdown
  file: src/sevn/docs/faq.py
  symbol: render_markdown
- name: slugify
  file: src/sevn/docs/faq.py
  symbol: slugify
- name: validate_document
  file: src/sevn/docs/faq.py
  symbol: validate_document
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
| `make ci-infra` | config-schema, onboarding schemas, git guards, pipe-to-shell installer gate, manifests |
| `make ci-docs` | about-site, readme, changelog, FAQ, skw spec/prd gates, telegram menu docs |
| `make ci-skills` | skillspector + skill inventory checks |
| `make ci-parity` | code-index, deploy report parity, mergecraft pin gate |
| `make ci-affected` / `make ci-changed` | Path-aware partial gates |
| `make ci-quality` | Advisory (ruff ratchet, vulture, codespell — not in `make ci`; daily cron in `ci-supplementary.yml`) |
| `make ci-quality-coverage` | Advisory (`coverage`, `diff-cover`, `coverage-ratchet`; sibling job in `ci-supplementary.yml`) |
| `.github/workflows/ci.yml` | Primary CI workflow |
| `.github/workflows/ci-cd.yml` | Container artifact publication + draft release on `v*` tags |
| `.craft.yml` | Sentry Craft config scaffold (evaluation-only; #110 / W15 — not wired to CI) |
| `about-sevn.bot/decisions/0003-craft-release-management-runbook.md` | Maintainer release runbook + Craft evaluation |
| `scripts/ci_resume.sh` | Ordered `CI_STEPS` driver |

Docs tooling in scope: `src/sevn/docs/about/check.py` (`check_about_docs`),
`make about-docs-check` (chains `make spec-check` + `make prd-check`),
`make changelog-check` (Keep a Changelog + Unreleased datestamp via `skw.changelog_validate`).

## Data Model

### `CI_STEPS` (39 ordered steps)

Defined in root `Makefile` — consumed by `make ci-resume` via `scripts/ci_resume.sh`.
First infra step includes `make config-schema` against `infra/sevn.schema.json` goldens.
Tier↔resume parity is enforced by `tests/infra/test_ci_steps_tier_parity.py` (flattened
`ci-*` tier prerequisites must equal `make ci-steps` output); a tier addition that omits
`CI_STEPS` fails CI instead of relying on a Makefile comment.

### Workflow matrix (`.github/workflows/`)

| Workflow | Purpose |
|----------|---------|
| `ci.yml` | Main CI (invokes make targets) |
| `ci-supplementary.yml` | Supplementary checks (daily security audit, advisory `ci-quality` / `ci-quality-coverage`, weekly image rebuild) |
| `ci-cd.yml` | Container artifact publication + draft release on `v*` tags. Dev deploy/smoke jobs are **absent** (deleted with the `failure`-as-OK escape hatch). Production deploy/test (`phase4`/`phase5`) remain documented stubs that block tag releases. Images push a quarantine tag first; SHA/version tags are promoted **by digest** only after Trivy→cosign (no `:latest` from `main` while stubs remain). Release tooling (cosign / syft / trivy) installs via SHA-pinned Actions; `make ensure-uv` installs a version-pinned, checksum-verified GitHub release (no downloader-piped-to-shell). |
| `docker.yml` | Container build validation |
| `style-guide-pages.yml` | Style guide site |

`ci-cd.yml` trigger matrix:

| Trigger | Jobs that run | Required gate (`delivery-chain` → **Artifact publication gate (required)**) |
|---------|---------------|-----------------------------------------------------------------------------|
| `push` to `main` | phase1 → publish-ghcr (quarantine tags) → container-supply-chain (scan→sign→promote SHA by digest); phase4/5/6 **skipped** | Green when publication + supply-chain succeed; skipped deploy/release jobs are OK; **no `:latest`** |
| `push` tag `v*` | same, then promote version tag by digest → phase4 → phase5 → phase6 | phase4/5 must succeed (stubs currently fail → gate red); draft release only when they succeed |
| `workflow_dispatch` | Same as tag path for phase4/5 when exercised; phase6 only on a `v*` ref | Stub `failure` fails the gate — no path classifies `failure` as OK |

### Artefacts (GHCR tag lifecycle)

| Artefact | Producer | Notes |
|----------|----------|-------|
| `:quarantine-<sha>` | `publish-ghcr` | Pre-scan only; not an operator pin target. Deleted on supply-chain failure/cancel when the version carries only quarantine tags. |
| `:<sha>` / `:v*` | `container-supply-chain` promote-by-digest step | Written **after** Trivy (`--exit-code 1`) and `cosign sign`. |
| `:latest` | *(none while phase4/5 stubs)* | Pre-existing registry `:latest` tags are **unverified**. Operator default is a digest pin (Batch B `DEFAULT_SANDBOX_IMAGE` / `rlm.docker_image` — single source of truth; see `docker/README.md`). |
| `sboms/` artifact | `container-supply-chain` | Trivy JSON/SARIF + SPDX; also attached to draft releases on `v*`. |

**Branch-protection expectation:** require the GitHub check named **Artifact publication gate (required)** (workflow job id `delivery-chain`). The previous display name was `Delivery chain gate (required)` — update any branch-protection / ruleset required-check list when this rename lands so the gate is not silently dropped.

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
8. **`ci-cd.yml` on `main`** — builds images to quarantine tags, scans/signs, then promotes SHA tags **by digest**. Does **not** write `:latest`, and does **not** deploy to Dev or Production; Dev deploy/smoke is unimplemented and no longer pretended via tolerated failing jobs.
9. **`ci-cd.yml` on `v*` tags** — same quarantine→scan→sign→promote path (SHA + version tags), then production deploy/test stubs (`phase4`/`phase5`). A draft GitHub Release (`phase6`, `draft: true`) is created only when those stubs succeed; today they fail closed, so tag builds stay red until real deploy exists.
10. **Required aggregator** — check name **Artifact publication gate (required)** accepts only `success` or `skipped` from its `needs`. A green check means artifact publication (and supply-chain) succeeded — not that production was deployed.

## Failure Modes

| Failure | Signal |
|---------|--------|
| Any CI step non-zero | `make ci` / Actions job red |
| Checkpoint stale after early-step regression | Operator runs `make ci-reset` then full gate |
| Schema drift | `make config-schema` fails |
| Doc regression | `make about-docs-check`, `make spec-check`, `make prd-check`, or `make readme-check` fails |
| Git guard missing | `make check-git-guards` fails (blocks destructive clean) |
| Tag build with deploy stubs failing | **Artifact publication gate (required)** (`delivery-chain`) red; phase6 does not run; no published release |
| Tag build while deploy phases succeed | Draft GitHub Release only (`draft: true`); no production deploy until phases 4–5 ship |
| `main` push with publish or supply-chain failure | **Artifact publication gate (required)** red; no consumable claim of readiness; quarantine tags cleaned when the package version carries only quarantine tags |
| Failing Trivy scan | Job red before `cosign sign` and before digest promote — no SHA/version/`latest` tag is written |
| Advisory quality tier member fails | `make ci-quality` runs every member target (non-short-circuit via `scripts/ci_quality.py`); job red on first failure but log shows all member results |
| Coverage gate after install-action sync | `make ci-quality-coverage` requires W12 dev-extra preservation; `make coverage` exits 2 when optional `dev` is pruned mid-suite |

## Amendments (telegram-menu-redesign W9)

``make ci-docs`` includes ``telegram-menu-docs-check`` (structural sync of
``about-sevn.bot/Telegram Menu.html`` vs live keyboards),
``telegram-menu-docs-scaffold`` (WIP stub insertion), and ``cli-help-docs-check``
(root CLI panels vs ``PANEL_ORDER``). ``make telegram-menu-e2e`` is live-gated
(``SEVN_TELEGRAM_MENU_E2E=1``) and is not part of ``make ci``.

## Test Strategy

| Gate | Validates |
|------|-----------|
| `make ci` | Entire pipeline (~12–15 min) |
| `make ci-resume` | Iterative final-wave fix loop |
| `tests/docs/about/` | About-docs contracts |
| `spec-kit-wave/tests/` | skw validators + sync contracts (`make spec-kit-wave-test` in `ci-docs`; `spec-check` / `prd-check` wired via `about-docs-check`) |
| `.github/workflows/*.yml` | CI orchestration smoke on every push |

## Amendments (open-issues-sweep-aug-2026 W15 — append-only)

Craft evaluation for [#110](https://github.com/sevn-bot/sevn/issues/110) — plan **D10**
(evaluate-then-adopt). Scaffold and docs land in W15; wiring Craft into `make release` or
`.github/workflows/` requires **operator sign-off** at the W15 gate.

- [x] **W15.1** Current release flow vs Craft capabilities documented in
  `about-sevn.bot/decisions/0003-craft-release-management-runbook.md` § Current release flow + § Craft evaluation.
  (2026-08-01 ✅: runbook)
- [x] **W15.2** Evaluation-only `.craft.yml` scaffold (`github` + `pypi` targets,
  `changelog.policy: simple`) plus dry-run instructions (`craft prepare|publish --dry-run`,
  `CRAFT_DRY_RUN`) in runbook § Dry-run instructions. Not referenced by Makefile or Actions.
  (2026-08-01 ✅: `.craft.yml` + runbook)
- [x] **W15.3** Maintainer release checklist (manual flow today + future Craft path) in runbook
  § Maintainer checklist. (2026-08-01 ✅: `about-sevn.bot/decisions/0003-craft-release-management-runbook.md`)
- [ ] **W15-adopt (operator gate)** Add `getsentry/craft@v2` workflow and/or `make release-*`
  wrappers; resolve duplicate GitHub Release ownership with `ci-cd.yml` phase6 before live
  `craft publish`. (2026-08-01 deferred: D10 — operator sign-off required)

## Amendments (post-audit-0.0.1 W2 — append-only)

Operator gateway variants (**#164**, **#165**, plan **D9** / **D10**) use Compose override
files instead of profiles. Each documented invocation must resolve to exactly
`{sevn-operator-perms, sevn-proxy, sevn-gateway}` with a single publisher of
``${SEVN_GATEWAY_PORT}``.

| Invocation | `-f` set | Gateway image |
|------------|----------|---------------|
| Default | `docker/docker-compose.yml` | `Dockerfile.gateway` |
| Browser CDP | base + `docker/docker-compose.browser.yml` | `Dockerfile.gateway.browser` |
| Headed GUI + noVNC | base + `docker/docker-compose.gui.yml` | `Dockerfile.gateway.gui` |

``make check-compose-default`` (in ``ci-infra``) validates all three file sets via
``scripts/check-compose-default.sh``. Makefile targets ``compose-up``,
``compose-browser-up``, and ``compose-gui-up`` route through the matching `-f` set;
``COMPOSE_PROFILES`` browser+gui mutual exclusion remains a regression net for legacy callers.

## Amendments (post-audit-0.0.1 W10 — append-only)

Release gate honesty (**#172**, plan **D21** / **D22**). Phases 2–5 remain
``needs-implementation`` stubs; the workflow publishes container images to GHCR
and signs/scans them, but does **not** deploy to Dev or Production.

| Trigger | What runs today | Release outcome |
|---------|-----------------|-----------------|
| `push` to `main` | phase1 → publish-ghcr → supply-chain; phase2/3 stubs fail (tolerated on main path) | No GitHub Release |
| `push` tag `v*` | phase1 → publish-ghcr → supply-chain → phase4/5 stubs **must succeed** for phase6 | Draft release only (`draft: true`); body states no production deploy |
| `workflow_dispatch` | Full chain rehearsal; stub phase failures tolerated via `needs_impl_ok` | Draft release on tag ref only |

``delivery-chain`` (required): on tag builds, phase4/phase5 ``failure`` fails the gate;
``needs_impl_ok`` tolerance applies **only** on ``workflow_dispatch``. Phase6
``needs`` phase4 and phase5 so a failing deploy stub blocks release creation.

## Amendments (post-audit-0.0.1 W11 — append-only)

Container CVE baseline (**#173**, plan **D23**). ``container-supply-chain`` scans
each published GHCR image with Trivy **before** ``cosign sign``; CRITICAL/HIGH
findings fail the job unless listed in ``security/trivy-allowlist.toml`` with a
future ``review_by`` date.

| Control | Location | Behaviour |
|---------|----------|-----------|
| Allowlist file | ``security/trivy-allowlist.toml`` | Time-boxed ``[[ignore]]`` rows: ``vuln_id``, ``image``, ``reason``, ``ticket``, ``review_by`` |
| Expiry gate | ``scripts/trivy_ignore_args.py`` + ``make trivy-allowlist-check`` (``ci-core`` via ``make security``) | Fails closed on expired rows; emits ``--ignorefile`` for Actions |
| Blocking scan | ``scan_image()`` in ``ci-cd.yml`` | ``trivy image --exit-code 1 --severity CRITICAL,HIGH --ignore-unfixed`` then cosign + syft |
| Reports | ``sboms/`` artifact + phase6 release attachments | Trivy JSON/SARIF + SPDX SBOM per image |

## Amendments (post-audit-0.0.1 W13 — append-only)

Advisory quality tier revival (**#178**, plan **D33**). ``make ci-quality`` and
``make ci-quality-coverage`` are **not** in ``make ci`` or sharded ``ci.yml`` —
they run on the daily ``ci-supplementary.yml`` cron (``17 5 * * *``) and
``workflow_dispatch``.

| Target | Members / steps | Runner behaviour |
|--------|-----------------|------------------|
| ``make ci-quality`` | ``ruff-extra``, ``typecheck-strict``, ``deadcode``, ``complexity``, ``complexity-ratchet``, ``spell``, ``deps-check``, ``docstring-coverage``, ``stale-xfail-check``, ``md-links-check`` | Non-short-circuit: ``scripts/ci_quality.py`` invokes every member via ``run_make_targets()`` and returns the first non-zero exit while printing all failures |
| ``make ci-quality-coverage`` | ``coverage``, ``diff-cover``, ``coverage-ratchet`` | Separate supplementary job on an unsharded runner; depends on W12 preserving optional ``dev`` during in-test ``uv sync`` (**D32**) |

``scripts/quality/ruff_advisory_baseline.json`` is refreshed with
``uv run python scripts/quality/ruff_advisory_gate.py --write-baseline``;
the ``generated`` date is emitted dynamically at write time.

## Amendments (prod-readiness-0.0.1 W10 — append-only)

Aggregator honesty (**C2.1**, **C2.2**, plan **D44**). Dev deploy/smoke jobs
(``phase2``/``phase3``) and the ``needs_impl_ok`` / ``require_needs_impl`` escape
hatch are **deleted**. The required check display name is
**Artifact publication gate (required)** (job id ``delivery-chain``). Production
stubs ``phase4``/``phase5`` remain; a ``main`` push skips them so the gate stays
green when publication succeeds. No required-check path classifies ``failure`` as OK.

## Amendments (prod-readiness-0.0.1 W11 — append-only)

Quarantine → scan → sign → promote by digest (**C12.3**, **C13.1**, **C13.2**, plan
**D45**). ``publish-ghcr`` pushes only ``:quarantine-<sha>-<run_id>`` (run-scoped so
overlapping ``main`` / ``v*`` publishes for the same commit cannot delete each
other's versions). Workflow concurrency is keyed on ``github.sha``.
``container-supply-chain`` keeps Trivy ``--exit-code 1`` before ``cosign sign``,
then promotes SHA (and ``:v*`` on tag builds) with ``docker buildx imagetools create``
**by digest**. ``:latest`` is not written from ``main`` while phase4/5 are stubs;
pre-existing ``:latest`` is unverified. Operator default is a digest pin — Batch B
owns ``DEFAULT_SANDBOX_IMAGE`` (D42); this batch documents the coupling in
``docker/README.md`` rather than adding a second constant. Failed/cancelled
``publish-ghcr`` and ``container-supply-chain`` runs delete that run's
quarantine-only package versions via ``scripts/ghcr_quarantine_cleanup.sh``.

## Amendments (prod-readiness-0.0.1 W12 — append-only)

Verified release-tooling installers (**C11.1**, **C11.2**, **C11.3**, plan **D46**,
**D47**). ``container-supply-chain`` installs syft via
``anchore/sbom-action/download-syft`` and trivy via ``aquasecurity/setup-trivy``,
both SHA-pinned like cosign. CLI versions remain ``syft v1.18.1`` and
``trivy v0.58.1`` so ``scripts/trivy_ignore_args.py`` /
``security/trivy-allowlist.toml`` keep working. ``make ensure-uv`` pins
``UV_VERSION`` and checksum-verifies the GitHub release archive through
``scripts/install_uv_verified.sh``. ``make check-no-curl-pipe-sh``
(``ci-infra`` / ``CI_STEPS``) rejects new downloader-piped-to-shell patterns under
``.github/`` and the ``Makefile``.

## Amendments (prod-readiness-0.0.1 C-Thermos — append-only)

Hardened W12 installers after review: ``install_uv_verified.sh`` compares the
archive to **in-repo** ``UV_SHA256_*`` pins (release ``sha256.sum`` alone is TOFU);
``check_no_curl_pipe_sh.sh`` joins backslash-newline continuations and uses the
W9.5 ``[^|]*`` charset so quoted URLs, ``$()`` forms, and
``curl … \\`` / ``| sh`` cannot bypass the gate; quarantine cleanup captures
``gh api`` output before the delete loop so a failed list call fails closed.
