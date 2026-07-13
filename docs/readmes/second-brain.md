<!-- generated: do not edit by hand; run `sevn readme update second-brain` -->
# Second brain — Wiki, Obsidian sync, ingest paths, and provenance for operator knowledge

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Wiki, Obsidian sync, ingest paths, and provenance for operator knowledge.

## Level 1 — Overview (non-technical)

**Second brain** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Wiki, Obsidian sync, ingest paths, and provenance for operator knowledge.

In everyday use, second brain helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/second_brain/`. The package contains 18 Python module(s); primary entry points include `src/sevn/second_brain/__init__.py`, `src/sevn/second_brain/bootstrap.py`, `src/sevn/second_brain/errors.py`, `src/sevn/second_brain/fetch.py`, `src/sevn/second_brain/folder_picker.py`, `src/sevn/second_brain/frontmatter.py`, and 12 more.

### Data and control flow

Second brain is a supporting subsystem; see Level 3 for the module-level flow.

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/27-second-brain.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/second_brain/__init__.py` — `wiki_search_tool`, `wiki_get_tool`, `wiki_apply_tool`, `wiki_lint_tool`
- `src/sevn/second_brain/bootstrap.py` — `ensure_second_brain_scope_layout`
- `src/sevn/second_brain/fetch.py` — `fetch_url_to_raw`
- `src/sevn/second_brain/folder_picker.py` — `normalise_browse_path`, `list_workspace_subdirs`
- `src/sevn/second_brain/frontmatter.py` — `split_frontmatter`, `dumps_frontmatter`, `normalise_agent_keys`, `okf_type_required`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/second_brain/` (18 Python files). Normative design: `about-sevn.bot/specs/27-second-brain.md`.

### Module inventory

- `src/sevn/second_brain/__init__.py` — Second Brain wiki engine + tool registration ('about-sevn.bot/specs/27-second-brain.md' section 2.1-2.2).
- `src/sevn/second_brain/bootstrap.py` — Idempotent Second Brain scope layout bootstrap ('about-sevn.bot/specs/27-second-brain.md' §3.2).
- `src/sevn/second_brain/errors.py` — Second Brain failure types ('about-sevn.bot/specs/27-second-brain.md' §6).
- `src/sevn/second_brain/fetch.py` — HTTPS URL → ''raw/'' fetch helper ('about-sevn.bot/specs/27-second-brain.md' §2.4, §5).
- `src/sevn/second_brain/folder_picker.py` — Workspace-relative folder browser helpers for Second Brain vault pickers.
- `src/sevn/second_brain/frontmatter.py` — YAML frontmatter parse/merge for wiki pages ('about-sevn.bot/specs/27-second-brain.md' §3.3).
- `src/sevn/second_brain/ingest.py` — Deterministic raw→wiki ingest pipeline ('about-sevn.bot/specs/27-second-brain.md' §2.2).
- `src/sevn/second_brain/ingest_stub.py` — Idempotent stub ingest ('about-sevn.bot/specs/27-second-brain.md' §2.2).
- `src/sevn/second_brain/layout_probe.py` — Second Brain vault layout checks for ''sevn doctor''.
- `src/sevn/second_brain/links.py` — Internal wiki link extraction and resolution (OKF + Obsidian wikilinks).
- `src/sevn/second_brain/lint_local.py` — Local wiki lint rules ('about-sevn.bot/specs/27-second-brain.md' §2.2).
- `src/sevn/second_brain/merge.py` — Optional git merge conflict path ('about-sevn.bot/specs/27-second-brain.md' §4, PRD §5.8).
- … and 6 more Python modules

### Package init (`src/sevn/second_brain/__init__.py`)

Public entry points:
- `wiki_search_tool`
- `wiki_get_tool`
- `wiki_apply_tool`
- `wiki_lint_tool`
- `second_brain_query_tool`
- `second_brain_ingest_stub_tool`
- `legacy_native_second_brain_ingest_stub_enabled`
- `register_second_brain_tools`

### Bootstrap (`src/sevn/second_brain/bootstrap.py`)

Public entry points:
- `ensure_second_brain_scope_layout`

### Errors (`src/sevn/second_brain/errors.py`)

See `src/sevn/second_brain/errors.py` for implementation details.

### Fetch (`src/sevn/second_brain/fetch.py`)

Public entry points:
- `fetch_url_to_raw`

### Folder Picker (`src/sevn/second_brain/folder_picker.py`)

Public entry points:
- `normalise_browse_path`
- `list_workspace_subdirs`

### Frontmatter (`src/sevn/second_brain/frontmatter.py`)

Public entry points:
- `split_frontmatter`
- `dumps_frontmatter`
- `normalise_agent_keys`
- `okf_type_required`
- `missing_okf_type`
- `compose_page`

### Ingest (`src/sevn/second_brain/ingest.py`)

Public entry points:
- `raw_content_hash`
- `run_ingest`

### Ingest Stub (`src/sevn/second_brain/ingest_stub.py`)

Public entry points:
- `run_ingest_stub`

### Layout Probe (`src/sevn/second_brain/layout_probe.py`)

Public entry points:
- `probe_second_brain_vault_layout`
- `fix_second_brain_layout`

### Links (`src/sevn/second_brain/links.py`)

Public entry points:
- `iter_internal_link_targets`
- `resolve_wiki_target`
- `index_line_targets`

### Lint Local (`src/sevn/second_brain/lint_local.py`)

See `src/sevn/second_brain/lint_local.py` for implementation details.

### Merge (`src/sevn/second_brain/merge.py`)

See `src/sevn/second_brain/merge.py` for implementation details.

### Additional modules

6 more Python files under `src/sevn/second_brain/` — including `src/sevn/second_brain/paths.py`, `src/sevn/second_brain/query.py`, `src/sevn/second_brain/search.py`, `src/sevn/second_brain/wiki_io.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/27-second-brain.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/second_brain/`, run `sevn readme update second-brain` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/27-second-brain.md](../../about-sevn.bot/specs/27-second-brain.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/27-second-brain.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/second_brain/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
