<!-- generated: do not edit by hand; run `sevn readme update code-understanding` -->
# Code understanding — MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation.

## Level 1 — Overview (non-technical)

**Code understanding** is a core part of sevn.bot — the personal AI assistant you run on your own machine. MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation.

In everyday use, code understanding helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver the code-orientation stack the coding companion PRD names: five orthogonal capabilities (MYCODE, Memgraph CGR, code-review-graph (SQLite MCP), roam-code, Graphify) that Triager and executors c

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/code_understanding/`. The package contains 19 Python module(s); primary entry points include `src/sevn/code_understanding/__init__.py`, `src/sevn/code_understanding/bootstrap.py`, `src/sevn/code_understanding/cgr_adapter.py`, `src/sevn/code_understanding/cgr_runner.py`, and 2 more.

### Data and control flow

Code understanding sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/28-code-understanding.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/code_understanding/bootstrap.py` — `code_orientation_doctor_checks`, `refresh_mycode_scan_cache`, `mycode_needs_refresh`
- `src/sevn/code_understanding/cgr_adapter.py` — `build_cgr_argv`, `read_export_capped`
- `src/sevn/code_understanding/cgr_runner.py` — `run_cgr_subprocess`, `read_export_file`
- `src/sevn/code_understanding/code_index.py` — `collect_module_symbols`, `iter_python_files`, `audit_docstring_coverage`, `extract_listed_symbols`
- `src/sevn/code_understanding/code_review_graph_mcp.py` — `code_review_graph_mcp_enabled`, `code_review_graph_mcp_server_id`, `read_only_tool_names`, `resolve_repo_root`

### Spec context

From specs/28-code-understanding.md:
Deliver the code-orientation stack the coding companion PRD names: five orthogonal capabilities (MYCODE, Memgraph CGR, code-review-graph (SQLite MCP), roam-code, Graphify) that Triager and executors c

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/code_understanding/` (19 Python files). Normative design: `specs/28-code-understanding.md`.

### Module inventory

- `src/sevn/code_understanding/__init__.py` — """Code-understanding stack: MYCODE, CGR, roam-code, Graphify ('specs/28-code-understanding.md').
- `src/sevn/code_understanding/bootstrap.py` — """Operator bootstrap for code orientation (MYCODE scan, Graphify hints).
- `src/sevn/code_understanding/cgr_adapter.py` — """Allowlisted CGR CLI argv builder + capped export reader.
- `src/sevn/code_understanding/cgr_runner.py` — """Subprocess runner for allowlisted ''cgr'' CLI ('specs/28-code-understanding.md' §2.2).
- `src/sevn/code_understanding/code_index.py` — """Generate ''.index/code_index/INDEX.md'' from the sevn source tree.
- `src/sevn/code_understanding/code_review_graph_mcp.py` — """code-review-graph MCP stdio registration ('specs/28-code-understanding.md' §3.4, §4.5).
- `src/sevn/code_understanding/effective_settings.py` — """Effective code-understanding settings when a sevn.bot checkout is available.
- `src/sevn/code_understanding/graphify.py` — """Pure helpers for Graphify profile resolution and Triager prefix text.
- `src/sevn/code_understanding/graphify_mcp.py` — """Graphify + code-understanding MCP gateway registration ('specs/28-code-understanding.md' §4.4).
- `src/sevn/code_understanding/graphify_seed.py` — """Deterministic Graphify index seeding for the ''source_code/'' mirror.
- `src/sevn/code_understanding/models.py` — """Pydantic types for code-understanding settings and digest payloads.
- `src/sevn/code_understanding/mycode_cache.py` — """MYCODE scan digest cache ('specs/28-code-understanding.md' §11).
- … and 7 more Python modules

### Bootstrap (`src/sevn/code_understanding/bootstrap.py`)

Public entry points:
- `code_orientation_doctor_checks` — see `src/sevn/code_understanding/bootstrap.py`
- `refresh_mycode_scan_cache` — see `src/sevn/code_understanding/bootstrap.py`
- `mycode_needs_refresh` — see `src/sevn/code_understanding/bootstrap.py`

### Cgr Adapter (`src/sevn/code_understanding/cgr_adapter.py`)

Public entry points:
- `build_cgr_argv` — see `src/sevn/code_understanding/cgr_adapter.py`
- `read_export_capped` — see `src/sevn/code_understanding/cgr_adapter.py`

### Cgr Runner (`src/sevn/code_understanding/cgr_runner.py`)

Public entry points:
- `run_cgr_subprocess` — see `src/sevn/code_understanding/cgr_runner.py`
- `read_export_file` — see `src/sevn/code_understanding/cgr_runner.py`

### Code Index (`src/sevn/code_understanding/code_index.py`)

Public entry points:
- `collect_module_symbols` — see `src/sevn/code_understanding/code_index.py`
- `iter_python_files` — see `src/sevn/code_understanding/code_index.py`
- `audit_docstring_coverage` — see `src/sevn/code_understanding/code_index.py`
- `extract_listed_symbols` — see `src/sevn/code_understanding/code_index.py`
- `render_code_index_markdown` — see `src/sevn/code_understanding/code_index.py`
- `generate_code_index` — see `src/sevn/code_understanding/code_index.py`

### Code Review Graph Mcp (`src/sevn/code_understanding/code_review_graph_mcp.py`)

Public entry points:
- `code_review_graph_mcp_enabled` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `code_review_graph_mcp_server_id` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `read_only_tool_names` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `resolve_repo_root` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `validate_repo_root` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `build_serve_argv` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `resolve_command` — see `src/sevn/code_understanding/code_review_graph_mcp.py`
- `mcp_stdio_entry` — see `src/sevn/code_understanding/code_review_graph_mcp.py`

### Effective Settings (`src/sevn/code_understanding/effective_settings.py`)

Public entry points:
- `graphify_enabled_for_checkout` — see `src/sevn/code_understanding/effective_settings.py`
- `effective_graphify_settings` — see `src/sevn/code_understanding/effective_settings.py`
- `effective_code_understanding` — see `src/sevn/code_understanding/effective_settings.py`

### Graphify (`src/sevn/code_understanding/graphify.py`)

Public entry points:
- `resolve_profiles` — see `src/sevn/code_understanding/graphify.py`
- `graph_report_path` — see `src/sevn/code_understanding/graphify.py`
- `graph_json_path` — see `src/sevn/code_understanding/graphify.py`
- `profile_covers` — see `src/sevn/code_understanding/graphify.py`
- `search_tool_prefix` — see `src/sevn/code_understanding/graphify.py`
- `clear_resolve_active_profiles_cache` — see `src/sevn/code_understanding/graphify.py`
- `resolve_active_profiles_cached` — see `src/sevn/code_understanding/graphify.py`
- `active_profiles_with_report` — see `src/sevn/code_understanding/graphify.py`

### Graphify Mcp (`src/sevn/code_understanding/graphify_mcp.py`)

Public entry points:
- `graphify_mcp_enabled` — see `src/sevn/code_understanding/graphify_mcp.py`
- `graphify_mcp_server_ids` — see `src/sevn/code_understanding/graphify_mcp.py`
- `merge_gateway_mcp_servers` — see `src/sevn/code_understanding/graphify_mcp.py`
- `build_effective_mcp_servers` — see `src/sevn/code_understanding/graphify_mcp.py`

### Graphify Seed (`src/sevn/code_understanding/graphify_seed.py`)

Public entry points:
- `graphify_report_mirror_path` — see `src/sevn/code_understanding/graphify_seed.py`
- `graphify_needs_refresh` — see `src/sevn/code_understanding/graphify_seed.py`
- `seed_graphify_mirror` — see `src/sevn/code_understanding/graphify_seed.py`
- `build_graphify_index` — see `src/sevn/code_understanding/graphify_seed.py`

### Additional modules

7 more Python files under `src/sevn/code_understanding/` — including `src/sevn/code_understanding/mycode_generate.py`, `src/sevn/code_understanding/mycode_scan.py`, `src/sevn/code_understanding/openwiki_runner.py`, `src/sevn/code_understanding/roam_code_adapter.py`.

### Extension and invariants

Follow `specs/28-code-understanding.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/code_understanding/`, run `sevn readme update code-understanding` and `make readme-check`.

## References

- [specs/28-code-understanding.md](specs/28-code-understanding.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/28-code-understanding.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/code_understanding/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
