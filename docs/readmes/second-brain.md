<!-- generated: do not edit by hand; run `sevn readme update second-brain` -->
# Second brain — Wiki, Obsidian sync, ingest paths, and provenance for operator knowledge

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Wiki, Obsidian sync, ingest paths, and provenance for operator knowledge.

## Level 1 — Overview (non-technical)

**Second brain** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Wiki, Obsidian sync, ingest paths, and provenance for operator knowledge.

In everyday use, second brain helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver the Second Brain subsystem: filesystem wiki engine + agent surface so operators curate sources in raw/ and maintain a structured wiki/ with index.md, log.md, lint reports, and provenance-beari

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/second_brain/`. The package contains 18 Python module(s); primary entry points include `src/sevn/second_brain/__init__.py`, `src/sevn/second_brain/bootstrap.py`, `src/sevn/second_brain/errors.py`, `src/sevn/second_brain/fetch.py`, and 2 more.

### Data and control flow

Second brain sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/27-second-brain.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/second_brain/__init__.py` — `wiki_search_tool`, `wiki_get_tool`, `wiki_apply_tool`, `wiki_lint_tool`
- `src/sevn/second_brain/bootstrap.py` — `ensure_second_brain_scope_layout`
- `src/sevn/second_brain/fetch.py` — `fetch_url_to_raw`
- `src/sevn/second_brain/folder_picker.py` — `normalise_browse_path`, `list_workspace_subdirs`
- `src/sevn/second_brain/frontmatter.py` — `split_frontmatter`, `dumps_frontmatter`, `normalise_agent_keys`, `okf_type_required`

### Spec context

From about-sevn.bot/specs/27-second-brain.md:
Deliver the Second Brain subsystem: filesystem wiki engine + agent surface so operators curate sources in raw/ and maintain a structured wiki/ with index.md, log.md, lint reports, and provenance-beari

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/second_brain/` (18 Python files). Normative design: `about-sevn.bot/specs/27-second-brain.md`.

### Module inventory

- `src/sevn/second_brain/__init__.py` — """Second Brain wiki engine + tool registration ('about-sevn.bot/specs/27-second-brain.md' section 2.1-2.2).
- `src/sevn/second_brain/bootstrap.py` — """Idempotent Second Brain scope layout bootstrap ('about-sevn.bot/specs/27-second-brain.md' §3.2).
- `src/sevn/second_brain/errors.py` — """Second Brain failure types ('about-sevn.bot/specs/27-second-brain.md' §6).
- `src/sevn/second_brain/fetch.py` — """HTTPS URL → ''raw/'' fetch helper ('about-sevn.bot/specs/27-second-brain.md' §2.4, §5).
- `src/sevn/second_brain/folder_picker.py` — """Workspace-relative folder browser helpers for Second Brain vault pickers.
- `src/sevn/second_brain/frontmatter.py` — """YAML frontmatter parse/merge for wiki pages ('about-sevn.bot/specs/27-second-brain.md' §3.3).
- `src/sevn/second_brain/ingest.py` — """Deterministic raw→wiki ingest pipeline ('about-sevn.bot/specs/27-second-brain.md' §2.2).
- `src/sevn/second_brain/ingest_stub.py` — """Idempotent stub ingest ('about-sevn.bot/specs/27-second-brain.md' §2.2).
- `src/sevn/second_brain/layout_probe.py` — """Second Brain vault layout checks for ''sevn doctor''.
- `src/sevn/second_brain/links.py` — """Internal wiki link extraction and resolution (OKF + Obsidian wikilinks).
- `src/sevn/second_brain/lint_local.py` — """Local wiki lint rules ('about-sevn.bot/specs/27-second-brain.md' §2.2).
- `src/sevn/second_brain/merge.py` — """Optional git merge conflict path ('about-sevn.bot/specs/27-second-brain.md' §4, PRD §5.8).
- … and 6 more Python modules

###   Init   (`src/sevn/second_brain/__init__.py`)

Public entry points:
- `wiki_search_tool` — see `src/sevn/second_brain/__init__.py`
- `wiki_get_tool` — see `src/sevn/second_brain/__init__.py`
- `wiki_apply_tool` — see `src/sevn/second_brain/__init__.py`
- `wiki_lint_tool` — see `src/sevn/second_brain/__init__.py`
- `second_brain_query_tool` — see `src/sevn/second_brain/__init__.py`
- `second_brain_ingest_stub_tool` — see `src/sevn/second_brain/__init__.py`
- `legacy_native_second_brain_ingest_stub_enabled` — see `src/sevn/second_brain/__init__.py`
- `register_second_brain_tools` — see `src/sevn/second_brain/__init__.py`

### Bootstrap (`src/sevn/second_brain/bootstrap.py`)

Public entry points:
- `ensure_second_brain_scope_layout` — see `src/sevn/second_brain/bootstrap.py`

### Fetch (`src/sevn/second_brain/fetch.py`)

Public entry points:
- `fetch_url_to_raw` — see `src/sevn/second_brain/fetch.py`

### Folder Picker (`src/sevn/second_brain/folder_picker.py`)

Public entry points:
- `normalise_browse_path` — see `src/sevn/second_brain/folder_picker.py`
- `list_workspace_subdirs` — see `src/sevn/second_brain/folder_picker.py`

### Frontmatter (`src/sevn/second_brain/frontmatter.py`)

Public entry points:
- `split_frontmatter` — see `src/sevn/second_brain/frontmatter.py`
- `dumps_frontmatter` — see `src/sevn/second_brain/frontmatter.py`
- `normalise_agent_keys` — see `src/sevn/second_brain/frontmatter.py`
- `okf_type_required` — see `src/sevn/second_brain/frontmatter.py`
- `missing_okf_type` — see `src/sevn/second_brain/frontmatter.py`
- `compose_page` — see `src/sevn/second_brain/frontmatter.py`

### Ingest (`src/sevn/second_brain/ingest.py`)

Public entry points:
- `raw_content_hash` — see `src/sevn/second_brain/ingest.py`
- `run_ingest` — see `src/sevn/second_brain/ingest.py`

### Ingest Stub (`src/sevn/second_brain/ingest_stub.py`)

Public entry points:
- `run_ingest_stub` — see `src/sevn/second_brain/ingest_stub.py`

### Layout Probe (`src/sevn/second_brain/layout_probe.py`)

Public entry points:
- `probe_second_brain_vault_layout` — see `src/sevn/second_brain/layout_probe.py`
- `fix_second_brain_layout` — see `src/sevn/second_brain/layout_probe.py`

### Links (`src/sevn/second_brain/links.py`)

Public entry points:
- `iter_internal_link_targets` — see `src/sevn/second_brain/links.py`
- `resolve_wiki_target` — see `src/sevn/second_brain/links.py`
- `index_line_targets` — see `src/sevn/second_brain/links.py`

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
