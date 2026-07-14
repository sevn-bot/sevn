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

Code understanding is organized around `  init  `, `bootstrap`, `cgr adapter`, `cgr runner`, and 2 more under `src/sevn/code_understanding/` with 19 Python module(s) in the scanned tree. Primary entry points include bootstrap.py (code_orientation_doctor_checks), cgr_adapter.py (build_cgr_argv), cgr_runner.py (run_cgr_subprocess), code_index.py (collect_module_symbols).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/28-code-understanding.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/code_understanding/bootstrap.py` — `code_orientation_doctor_checks`, `refresh_mycode_scan_cache`, `mycode_needs_refresh`
- `src/sevn/code_understanding/cgr_adapter.py` — `build_cgr_argv`, `read_export_capped`
- `src/sevn/code_understanding/cgr_runner.py` — `run_cgr_subprocess`, `read_export_file`
- `src/sevn/code_understanding/code_index.py` — `collect_module_symbols`, `iter_python_files`, `audit_docstring_coverage`, `extract_listed_symbols`
- `src/sevn/code_understanding/code_review_graph_mcp.py` — `code_review_graph_mcp_enabled`, `code_review_graph_mcp_server_id`, `read_only_tool_names`, `resolve_repo_root`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/code_understanding`](../../src/sevn/code_understanding/) (19 Python files). Normative design: `about-sevn.bot/specs/28-code-understanding.md`.

### Module inventory

Code-understanding stack: MYCODE, CGR, roam-code, Graphify (about-sevn.bot/specs/28-code-understanding.md).

Working with [`__init__.py`](../../src/sevn/code_understanding/__init__.py): inspect the public entry points below.

Operator bootstrap for code orientation (MYCODE scan, Graphify hints).

Working with [`bootstrap.py`](../../src/sevn/code_understanding/bootstrap.py): inspect the public entry points below.
Start with [`code_orientation_doctor_checks`](../../src/sevn/code_understanding/bootstrap.py#L26), then [`refresh_mycode_scan_cache`](../../src/sevn/code_understanding/bootstrap.py#L68), [`mycode_needs_refresh`](../../src/sevn/code_understanding/bootstrap.py#L93).

Allowlisted CGR CLI argv builder + capped export reader.

Working with [`cgr_adapter.py`](../../src/sevn/code_understanding/cgr_adapter.py): inspect the public entry points below.
Start with [`build_cgr_argv`](../../src/sevn/code_understanding/cgr_adapter.py#L20), then [`read_export_capped`](../../src/sevn/code_understanding/cgr_adapter.py#L59).

Subprocess runner for allowlisted cgr CLI (about-sevn.bot/specs/28-code-understanding.md §2.2).

Working with [`cgr_runner.py`](../../src/sevn/code_understanding/cgr_runner.py): inspect the public entry points below.
Start with [`run_cgr_subprocess`](../../src/sevn/code_understanding/cgr_runner.py#L17), then [`read_export_file`](../../src/sevn/code_understanding/cgr_runner.py#L58).

Generate .index/code_index/INDEX.md from the sevn source tree.

The tier-B executor needs a stable, in-workspace map of the codebase so it
doesn't have to glob-and-guess to answer questions like "where is the triager
prompt?" or "list folders at code root". The index is deterministic: a folder
tree plus, for every public Python module, the first docstring line plus a
signature-level entry for each public function/class with its docstring head.

Working with [`code_index.py`](../../src/sevn/code_understanding/code_index.py): inspect the public entry points below.
Start with [`collect_module_symbols`](../../src/sevn/code_understanding/code_index.py#L187), then [`iter_python_files`](../../src/sevn/code_understanding/code_index.py#L275), [`audit_docstring_coverage`](../../src/sevn/code_understanding/code_index.py#L311), [`extract_listed_symbols`](../../src/sevn/code_understanding/code_index.py#L358).

code-review-graph MCP stdio registration (about-sevn.bot/specs/28-code-understanding.md §3.4, §4.5).

Working with [`code_review_graph_mcp.py`](../../src/sevn/code_understanding/code_review_graph_mcp.py): inspect the public entry points below.
Start with [`code_review_graph_mcp_enabled`](../../src/sevn/code_understanding/code_review_graph_mcp.py#L33), then [`code_review_graph_mcp_server_id`](../../src/sevn/code_understanding/code_review_graph_mcp.py#L62), [`read_only_tool_names`](../../src/sevn/code_understanding/code_review_graph_mcp.py#L75), [`resolve_repo_root`](../../src/sevn/code_understanding/code_review_graph_mcp.py#L90).

Effective code-understanding settings when a sevn.bot checkout is available.

Working with [`effective_settings.py`](../../src/sevn/code_understanding/effective_settings.py): inspect the public entry points below.
Start with [`graphify_enabled_for_checkout`](../../src/sevn/code_understanding/effective_settings.py#L20), then [`effective_graphify_settings`](../../src/sevn/code_understanding/effective_settings.py#L47), [`effective_code_understanding`](../../src/sevn/code_understanding/effective_settings.py#L79).

Pure helpers for Graphify profile resolution and Triager prefix text.

Working with [`graphify.py`](../../src/sevn/code_understanding/graphify.py): inspect the public entry points below.
Start with [`resolve_profiles`](../../src/sevn/code_understanding/graphify.py#L42), then [`graph_report_path`](../../src/sevn/code_understanding/graphify.py#L99), [`graph_json_path`](../../src/sevn/code_understanding/graphify.py#L118), [`profile_covers`](../../src/sevn/code_understanding/graphify.py#L137).

Graphify + code-understanding MCP gateway registration (about-sevn.bot/specs/28-code-understanding.md §4.4).

Working with [`graphify_mcp.py`](../../src/sevn/code_understanding/graphify_mcp.py): inspect the public entry points below.
Start with [`graphify_mcp_enabled`](../../src/sevn/code_understanding/graphify_mcp.py#L20), then [`graphify_mcp_server_ids`](../../src/sevn/code_understanding/graphify_mcp.py#L43), [`merge_gateway_mcp_servers`](../../src/sevn/code_understanding/graphify_mcp.py#L87), [`build_effective_mcp_servers`](../../src/sevn/code_understanding/graphify_mcp.py#L125).

Deterministic Graphify index seeding for the source_code/ mirror.

The tier-B agent is told (in AGENTS-detail.md/sevn.bot.md) to read
source_code/.index/graphify/GRAPH_REPORT.md for architecture orientation.
That file only exists if something builds the Graphify graph, so a fresh gateway
boot leaves the agent issuing repeated read "not found" errors on a path that
is never populated.

This module builds the graph directly inside the workspace source_code/
mirror (where the agent's read actually resolves — the mirror is a physical
copy, not a redirect to the checkout) by shelling out to the standalone
graphify CLI (graphify update <mirror>). graphify is not importable in
the gateway venv, so everything is a subprocess call guarded by
shutil.which and degrades to a single actionable log line when the CLI is
absent. The build is AST-only (no LLM) and fast, mirroring _boot_seed_mycode.

The sync_source_copy mirror skips .index/graphify-out and prunes any
mirror file that is not a tracked source file, so the seeded graph is rebuilt on
each boot after the mirror refresh — the staleness gate keeps that cheap by only
rebuilding when the report is missing or older than the newest .py source.

Working with [`graphify_seed.py`](../../src/sevn/code_understanding/graphify_seed.py): inspect the public entry points below.
Start with [`graphify_report_mirror_path`](../../src/sevn/code_understanding/graphify_seed.py#L56), then [`graphify_needs_refresh`](../../src/sevn/code_understanding/graphify_seed.py#L102), [`seed_graphify_mirror`](../../src/sevn/code_understanding/graphify_seed.py#L205), [`build_graphify_index`](../../src/sevn/code_understanding/graphify_seed.py#L250).

Pydantic types for code-understanding settings and digest payloads.

Working with [`models.py`](../../src/sevn/code_understanding/models.py): inspect the public entry points below.
Start with [`GraphifyProfile.validated_cli_flags`](../../src/sevn/code_understanding/models.py#L176).

MYCODE scan digest cache (about-sevn.bot/specs/28-code-understanding.md §11).

Working with [`mycode_cache.py`](../../src/sevn/code_understanding/mycode_cache.py): inspect the public entry points below.
Start with [`cache_path_for_root`](../../src/sevn/code_understanding/mycode_cache.py#L26), then [`scan_repo_cached`](../../src/sevn/code_understanding/mycode_cache.py#L110), [`save_scan_cache`](../../src/sevn/code_understanding/mycode_cache.py#L153).

7 more Python files under [`src/sevn/code_understanding`](../../src/sevn/code_understanding/) — including `src/sevn/code_understanding/mycode_generate.py`, `src/sevn/code_understanding/mycode_scan.py`, `src/sevn/code_understanding/openwiki_runner.py`, `src/sevn/code_understanding/roam_code_adapter.py`.

### Extension and invariants

Follow [`28-code-understanding.md`](../../about-sevn.bot/specs/28-code-understanding.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/code_understanding`](../../src/sevn/code_understanding/), run `sevn readme update code-understanding` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/28-code-understanding.md](../../about-sevn.bot/specs/28-code-understanding.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/28-code-understanding.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/code_understanding/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
