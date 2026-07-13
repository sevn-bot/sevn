<!-- generated: do not edit by hand; run `sevn readme update code-understanding` -->
# Code understanding — MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation.

## Level 1 — Overview (non-technical)

**Code understanding** is a core part of sevn.bot — the personal AI assistant you run on your own machine. MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation.

In everyday use, code understanding helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/code_understanding/`. The package contains 19 Python module(s); primary entry points include `src/sevn/code_understanding/__init__.py`, `src/sevn/code_understanding/bootstrap.py`, `src/sevn/code_understanding/cgr_adapter.py`, `src/sevn/code_understanding/cgr_runner.py`, `src/sevn/code_understanding/code_index.py`, `src/sevn/code_understanding/code_review_graph_mcp.py`, and 13 more.

### Data and control flow

Code understanding is a supporting subsystem; see Level 3 for the module-level flow.

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/28-code-understanding.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/code_understanding/bootstrap.py` — `code_orientation_doctor_checks`, `refresh_mycode_scan_cache`, `mycode_needs_refresh`
- `src/sevn/code_understanding/cgr_adapter.py` — `build_cgr_argv`, `read_export_capped`
- `src/sevn/code_understanding/cgr_runner.py` — `run_cgr_subprocess`, `read_export_file`
- `src/sevn/code_understanding/code_index.py` — `collect_module_symbols`, `iter_python_files`, `audit_docstring_coverage`, `extract_listed_symbols`
- `src/sevn/code_understanding/code_review_graph_mcp.py` — `code_review_graph_mcp_enabled`, `code_review_graph_mcp_server_id`, `read_only_tool_names`, `resolve_repo_root`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/code_understanding/` (19 Python files). Normative design: `about-sevn.bot/specs/28-code-understanding.md`.

### Module inventory

- `src/sevn/code_understanding/__init__.py` — Code-understanding stack: MYCODE, CGR, roam-code, Graphify ('about-sevn.bot/specs/28-code-understanding.md').
- `src/sevn/code_understanding/bootstrap.py` — Operator bootstrap for code orientation (MYCODE scan, Graphify hints).
- `src/sevn/code_understanding/cgr_adapter.py` — Allowlisted CGR CLI argv builder + capped export reader.
- `src/sevn/code_understanding/cgr_runner.py` — Subprocess runner for allowlisted ''cgr'' CLI ('about-sevn.bot/specs/28-code-understanding.md' §2.2).
- `src/sevn/code_understanding/code_index.py` — Generate ''.index/code_index/INDEX.md'' from the sevn source tree.
- `src/sevn/code_understanding/code_review_graph_mcp.py` — code-review-graph MCP stdio registration ('about-sevn.bot/specs/28-code-understanding.md' §3.4, §4.5).
- `src/sevn/code_understanding/effective_settings.py` — Effective code-understanding settings when a sevn.bot checkout is available.
- `src/sevn/code_understanding/graphify.py` — Pure helpers for Graphify profile resolution and Triager prefix text.
- `src/sevn/code_understanding/graphify_mcp.py` — Graphify + code-understanding MCP gateway registration ('about-sevn.bot/specs/28-code-understanding.md' §4.4).
- `src/sevn/code_understanding/graphify_seed.py` — Deterministic Graphify index seeding for the ''source_code/'' mirror.
- `src/sevn/code_understanding/models.py` — Pydantic types for code-understanding settings and digest payloads.
- `src/sevn/code_understanding/mycode_cache.py` — MYCODE scan digest cache ('about-sevn.bot/specs/28-code-understanding.md' §11).
- … and 7 more Python modules

### Package init (`src/sevn/code_understanding/__init__.py`)

See `src/sevn/code_understanding/__init__.py` for implementation details.

### Bootstrap (`src/sevn/code_understanding/bootstrap.py`)

Public entry points:
- `code_orientation_doctor_checks`
- `refresh_mycode_scan_cache`
- `mycode_needs_refresh`

### Cgr Adapter (`src/sevn/code_understanding/cgr_adapter.py`)

Public entry points:
- `build_cgr_argv`
- `read_export_capped`

### Cgr Runner (`src/sevn/code_understanding/cgr_runner.py`)

Public entry points:
- `run_cgr_subprocess`
- `read_export_file`

### Code Index (`src/sevn/code_understanding/code_index.py`)

Public entry points:
- `collect_module_symbols`
- `iter_python_files`
- `audit_docstring_coverage`
- `extract_listed_symbols`
- `render_code_index_markdown`
- `generate_code_index`

### Code Review Graph Mcp (`src/sevn/code_understanding/code_review_graph_mcp.py`)

Public entry points:
- `code_review_graph_mcp_enabled`
- `code_review_graph_mcp_server_id`
- `read_only_tool_names`
- `resolve_repo_root`
- `validate_repo_root`
- `build_serve_argv`
- `resolve_command`
- `mcp_stdio_entry`

### Effective Settings (`src/sevn/code_understanding/effective_settings.py`)

Public entry points:
- `graphify_enabled_for_checkout`
- `effective_graphify_settings`
- `effective_code_understanding`

### Graphify (`src/sevn/code_understanding/graphify.py`)

Public entry points:
- `resolve_profiles`
- `graph_report_path`
- `graph_json_path`
- `profile_covers`
- `search_tool_prefix`
- `clear_resolve_active_profiles_cache`
- `resolve_active_profiles_cached`
- `active_profiles_with_report`

### Graphify Mcp (`src/sevn/code_understanding/graphify_mcp.py`)

Public entry points:
- `graphify_mcp_enabled`
- `graphify_mcp_server_ids`
- `merge_gateway_mcp_servers`
- `build_effective_mcp_servers`

### Graphify Seed (`src/sevn/code_understanding/graphify_seed.py`)

Public entry points:
- `graphify_report_mirror_path`
- `graphify_needs_refresh`
- `seed_graphify_mirror`
- `build_graphify_index`

### Models (`src/sevn/code_understanding/models.py`)

See `src/sevn/code_understanding/models.py` for implementation details.

### Mycode Cache (`src/sevn/code_understanding/mycode_cache.py`)

See `src/sevn/code_understanding/mycode_cache.py` for implementation details.

### Additional modules

7 more Python files under `src/sevn/code_understanding/` — including `src/sevn/code_understanding/mycode_generate.py`, `src/sevn/code_understanding/mycode_scan.py`, `src/sevn/code_understanding/openwiki_runner.py`, `src/sevn/code_understanding/roam_code_adapter.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/28-code-understanding.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/code_understanding/`, run `sevn readme update code-understanding` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/28-code-understanding.md](../../about-sevn.bot/specs/28-code-understanding.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/28-code-understanding.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/code_understanding/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
