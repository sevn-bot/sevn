---
id: spec-27-second-brain
kind: spec
title: Second Brain — Spec
status: scaffold
owner: Alex
summary: 'Deliver the Second Brain subsystem: filesystem wiki engine + agent surface
  so operators curate sources in raw/ and maintain a structured wiki/ with index.md,
  log.md, lint reports, and provenance-beari'
last_updated: '2026-07-15'
fingerprint: sha256:1d0efdd7856ce0cba6b5ed3cafc9d0c03065244ef6f327a554b4bd76add14113
related: []
sources:
- src/sevn/second_brain/**
parent_prd: prd-09-knowledge-base
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
- spec-04-tracing
- spec-07-egress-proxy
- spec-09-security-scanner
- spec-11-tools-registry
- spec-12-skills-system
- spec-15-memory-lcm
- spec-17-gateway
- spec-18-channel-telegram
- spec-24-dashboard
build_phase: null
interfaces:
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
- name: detect_layout
  file: src/sevn/second_brain/bootstrap.py
  symbol: detect_layout
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
- name: reserved_basenames_for_layout
  file: src/sevn/second_brain/frontmatter.py
  symbol: reserved_basenames_for_layout
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
- name: collect_vault_md_by_rel
  file: src/sevn/second_brain/links.py
  symbol: collect_vault_md_by_rel
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
- name: lint_vault_tree
  file: src/sevn/second_brain/lint_local.py
  symbol: lint_vault_tree
- name: lint_wiki_tree
  file: src/sevn/second_brain/lint_local.py
  symbol: lint_wiki_tree
- name: SecondBrainMergeToolError
  file: src/sevn/second_brain/merge.py
  symbol: SecondBrainMergeToolError
- name: try_git_merge
  file: src/sevn/second_brain/merge.py
  symbol: try_git_merge
- name: VaultLayout
  file: src/sevn/second_brain/paths.py
  symbol: VaultLayout
- name: assert_wiki_relative_safe
  file: src/sevn/second_brain/paths.py
  symbol: assert_wiki_relative_safe
- name: content_roots_for
  file: src/sevn/second_brain/paths.py
  symbol: content_roots_for
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
- name: resolve_vault_note_file
  file: src/sevn/second_brain/paths.py
  symbol: resolve_vault_note_file
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
---

## Purpose

Deliver the Second Brain subsystem: filesystem wiki engine + agent surface so operators curate sources and maintain structured vault notes with index/log, lint reports, and provenance-bearing frontmatter. Supports **legacy** OKF layout (`raw/`, `wiki/`, `outputs/`) and **PARA** Obsidian-native layout (`00_Inbox`…`40_Archive`) via `second_brain.layout`.

Primary code trees: [`src/sevn/second_brain`](src/sevn/second_brain/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`legacy_native_second_brain_ingest_stub_enabled`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`register_second_brain_tools`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`second_brain_ingest_stub_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`second_brain_query_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_apply_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_get_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_lint_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_search_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`ensure_second_brain_scope_layout`](src/sevn/second_brain/bootstrap.py) — `src/sevn/second_brain/bootstrap.py`
- [`SecondBrainError`](src/sevn/second_brain/errors.py) — `src/sevn/second_brain/errors.py`
- [`SecondBrainMergeNeededError`](src/sevn/second_brain/errors.py) — `src/sevn/second_brain/errors.py`
- [`SecondBrainPathError`](src/sevn/second_brain/errors.py) — `src/sevn/second_brain/errors.py`
- _…and 56 more in frontmatter `interfaces:`._
## Data Model

### §5 Configuration

| Key | Role |
|-----|------|
| `second_brain.enabled` | Master toggle |
| `second_brain.layout` | Vault layout: `"legacy"` (default) or `"para"`. Legacy reproduces the OKF `wiki/raw/outputs` tree byte-for-byte; PARA maps semantic roles onto a PARA Obsidian folder profile. |
| `second_brain.para` | PARA folder profile (used only when `layout="para"`). All keys optional with PARA defaults; each value is a single safe path segment. Unknown keys rejected (`extra="forbid"`). |
| `second_brain.para.inbox` | Capture role folder (default `00_Inbox`) |
| `second_brain.para.projects` | Projects role folder (default `10_Projects`) |
| `second_brain.para.areas` | Areas role folder (default `20_Areas`) |
| `second_brain.para.resources` | Curated/reference role folder (default `30_Resources`) |
| `second_brain.para.archive` | Archive role folder (default `40_Archive`) |
| `second_brain.para.templates` | Templates role folder (default `90_Templates`) |
| `second_brain.para.sources_subdir` | Immutable sources under resources (default `_sources`) |
| `second_brain.para.outputs_subdir` | Bot outputs under resources (default `_outputs`) |
| `second_brain.para.index_note` | Vault home note basename (default `index.md` at vault root) |
| `second_brain.para.log_note` | Vault log note basename (default `log.md` at vault root) |
| `second_brain.paths.vault` | Workspace-relative Obsidian vault folder (e.g. `obsidian/alex_AI`); unset → legacy `second_brain/users/<scope>/` |
| `second_brain.paths.wiki` | **Read alias only** for `vault`; doctor warns; writes normalize to `vault` |

CLI `sevn second-brain setup --layout {auto,legacy,para}` writes `layout` and, when needed, a default `para` block. `--layout auto` (default) calls `detect_layout` on the target vault and falls back to `legacy` when inconclusive.

## Implemented by

- [`legacy_native_second_brain_ingest_stub_enabled`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`register_second_brain_tools`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`second_brain_ingest_stub_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`second_brain_query_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_apply_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_get_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_lint_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`wiki_search_tool`](src/sevn/second_brain/__init__.py) — `src/sevn/second_brain/__init__.py`
- [`ensure_second_brain_scope_layout`](src/sevn/second_brain/bootstrap.py) — `src/sevn/second_brain/bootstrap.py`
- [`SecondBrainError`](src/sevn/second_brain/errors.py) — `src/sevn/second_brain/errors.py`
- [`SecondBrainMergeNeededError`](src/sevn/second_brain/errors.py) — `src/sevn/second_brain/errors.py`
- [`SecondBrainPathError`](src/sevn/second_brain/errors.py) — `src/sevn/second_brain/errors.py`
- [`SecondBrainFetchError`](src/sevn/second_brain/fetch.py) — `src/sevn/second_brain/fetch.py`
- [`fetch_url_to_raw`](src/sevn/second_brain/fetch.py) — `src/sevn/second_brain/fetch.py`
- [`list_workspace_subdirs`](src/sevn/second_brain/folder_picker.py) — `src/sevn/second_brain/folder_picker.py`
- [`normalise_browse_path`](src/sevn/second_brain/folder_picker.py) — `src/sevn/second_brain/folder_picker.py`
- [`compose_page`](src/sevn/second_brain/frontmatter.py) — `src/sevn/second_brain/frontmatter.py`
- [`dumps_frontmatter`](src/sevn/second_brain/frontmatter.py) — `src/sevn/second_brain/frontmatter.py`
- [`missing_okf_type`](src/sevn/second_brain/frontmatter.py) — `src/sevn/second_brain/frontmatter.py`
- [`normalise_agent_keys`](src/sevn/second_brain/frontmatter.py) — `src/sevn/second_brain/frontmatter.py`
- _…and 48 more in frontmatter `interfaces:`._

## Internal Architecture

### §3.2 Vault layout

Second Brain resolves vault paths through a **`VaultLayout`** resolver (`paths.py`) that maps semantic **layout roles** to concrete directories. The active layout comes from `second_brain.layout` (`"legacy"` default | `"para"`).

**Scope root:** Paths resolve under the workspace content root. When `second_brain.paths.vault` is **unset**, the legacy layout applies: `second_brain/users/<scope>/{raw,wiki,outputs}`. When set, `default_scope` uses `<workspace>/<paths.vault>/` directly (no `users/<scope>/` segment). Non-default scopes keep the legacy path. `shared/wiki` remains at `second_brain/shared/wiki` (legacy overlay only).

#### Layout roles

| Role | Legacy path | PARA path (defaults) |
|------|-------------|----------------------|
| `capture` | aliases `curated` → `wiki/` | `00_Inbox/` |
| `projects` | aliases `curated` | `10_Projects/` |
| `areas` | aliases `curated` | `20_Areas/` |
| `curated` | `wiki/` | `30_Resources/` |
| `archive` | aliases `curated` | `40_Archive/` |
| `templates` | aliases `curated` | `90_Templates/` |
| `sources` | `raw/` | `30_Resources/_sources/` |
| `outputs` | `outputs/` | `30_Resources/_outputs/` |
| `index_note` | `wiki/index.md` | vault-root `index.md` |
| `log_note` | `wiki/log.md` | vault-root `log.md` |

**Content roots** (search, semantic index, lint scan): legacy → `(wiki,)`; PARA → `(inbox, projects, areas, resources)` — excludes templates, archive, and machinery subdirs.

Legacy shims `wiki_dir_for_scope`, `raw_dir_for_scope`, and `outputs_dir_for_scope` delegate to `VaultLayout.role_dir(...)` for back-compat.

#### Legacy layout (default)

When `layout="legacy"` (the default), behavior is **byte-for-byte unchanged** from pre-PARA installs: OKF `type:` is required on concept pages; ingest lands curated pages under `wiki/ingests/`; sources under `raw/`; bot outputs under `outputs/`.

Bootstrap (`ensure_second_brain_scope_layout`) idempotently creates `raw/`, `wiki/`, `wiki/ingests/`, `outputs/`, stub `wiki/index.md`, `wiki/log.md`, and optional `MODEL.md` (from `default_MODEL.md`).

#### PARA layout

When `layout="para"`, the scope root is the PARA Obsidian vault (typically via `paths.vault`). Bootstrap creates the role tree from `second_brain.para`, vault-root `index.md`/`log.md`, bundled folder READMEs, `90_Templates/*`, minimal `.obsidian/`, and `MODEL.md` (from `para_MODEL.md`) — **only where missing**.

**Adoption / no-clobber:** `detect_layout(vault_root)` returns `"para"` when ≥2 PARA folders (or `.obsidian/` + ≥1 PARA folder) exist, `"legacy"` when both `wiki/` and `raw/` exist, else `None`. Bootstrap and adoption are **additive-only**: never overwrite existing notes, `MODEL.md`, or an existing `.obsidian/`. No auto-migration from legacy to PARA.

**Frontmatter:** PARA uses Obsidian-native keys (`tags`, `aliases`, `created`, `updated`, `source`, `source_hash`, `captured`); `type:` is **advisory** (lint warning, not error). Legacy OKF `type:` enforcement is unchanged.

**Lint:** `lint_vault_tree(layout)` scans `content_roots()`; `lint_wiki_tree` remains a legacy shim. Templates and archive are excluded from orphan/staleness checks in both layouts.

**Ingest:** Sources land under `role_dir("sources")`; curated ingest pages under `role_dir("capture")` (PARA inbox); outputs under `role_dir("outputs")`; log lines append to `log_note()`.

## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/second_brain`](src/sevn/second_brain/__init__.py).

**Bundled Obsidian CLI skill:** The `obsidian-cli` core skill (vault CLI via a running Obsidian app) is **opt-in**. Onboarding capability `skill.obsidian_cli` writes `skills.obsidian_cli.enabled` with `default: false`. `SkillsManager` consults `gate_obsidian_cli_core_skill` during scan so the skill is absent from discovery/`load_skill` unless the operator enables it (mirrors `openwiki`). Other Obsidian-flavored bundled skills (`obsidian-markdown`, `obsidian-bases`, …) are independent of this gate.

## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Unit tests under `tests/second_brain/` cover path resolution, bootstrap idempotency, config validation, CLI setup, Telegram menu captions, and onboarding capability manifest rows.

## 10. Build Checklist

### 10.1 Custom vault paths — append-only

- [x] Config model `SecondBrainPathsConfig` + schema `second_brain.paths.vault` (2026-07-11 ✅: `src/sevn/config/sections/features.py`, `infra/sevn.schema.json`)
- [x] Path resolution `resolve_scope_root` + caller migration (2026-07-11 ✅: `src/sevn/second_brain/paths.py`, gateway/dashboard/skills)
- [x] Bootstrap `ensure_second_brain_scope_layout` + gateway boot hook (2026-07-11 ✅: `src/sevn/second_brain/bootstrap.py`, `layout_validate.py`)
- [x] Doctor probe `second_brain_vault_layout` + fix (2026-07-11 ✅: `layout_probe.py`, `cli/doctor/probes.py`)
- [x] CLI `sevn second-brain setup` + `sevn config second-brain` (2026-07-11 ✅: `cli/commands/second_brain_cmd.py`)
- [x] Telegram `/config` vault path + browse forms (2026-07-11 ✅: `menu.py`, `menu_form_handler.py`)
- [x] Onboarding text + folder_picker controls (2026-07-11 ✅: `onboarding_capabilities.json`, web wizard)

## Human-input needed

§3.2 and §5 normative bodies authored in W9 (PARA/legacy layout model). Remaining sections (Behavior, Failure Modes) still scaffold — confirm via `make -C spec-kit-wave spec-check` before `status: done`.
