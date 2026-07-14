<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint code-understanding` -->
# Code understanding — MYCODE, Graphify, code-review-graph, roam-code, openwiki, and CGR

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation.

## Level 1 — Overview (non-technical)

**Code understanding** orients the agent inside your codebase: **MYCODE** scans produce a module map, **Graphify** builds AST knowledge graphs, **code-review-graph** adds MCP semantic search, **roam-code** answers path-local questions, and **openwiki** maintains a headless wiki under `source_code/openwiki/`. **CGR** (code-graph-rag) integrates optionally for Memgraph-oriented exports.

## Level 2 — How it works (technical)

Package [`src/sevn/code_understanding/`](../../src/sevn/code_understanding/). Gateway boot seeds MYCODE/Graphify mirrors via [`bootstrap.py`](../../src/sevn/code_understanding/bootstrap.py).

### MYCODE, Graphify, roam-code, openwiki

| Capability | Module | Operator surface |
| --- | --- | --- |
| MYCODE scan cache | [`mycode_scan.py`](../../src/sevn/code_understanding/mycode_scan.py), [`mycode_cache.py`](../../src/sevn/code_understanding/mycode_cache.py) | `.index/mycode/` digest; doctor via [`code_orientation_doctor_checks`](../../src/sevn/code_understanding/bootstrap.py#L26) |
| Graphify seed | [`graphify_seed.py`](../../src/sevn/code_understanding/graphify_seed.py) | [`seed_graphify_mirror`](../../src/sevn/code_understanding/graphify_seed.py#L205) → `source_code/.index/graphify/` |
| Graphify MCP | [`graphify_mcp.py`](../../src/sevn/code_understanding/graphify_mcp.py) | [`merge_gateway_mcp_servers`](../../src/sevn/code_understanding/graphify_mcp.py#L87) |
| code-review-graph MCP | [`code_review_graph_mcp.py`](../../src/sevn/code_understanding/code_review_graph_mcp.py) | Read-only review tools when enabled |
| **roam-code** | [`roam_code_adapter.py`](../../src/sevn/code_understanding/roam_code_adapter.py), [`roam_runner.py`](../../src/sevn/code_understanding/roam_runner.py) | Native [`roam_code_tool`](../../src/sevn/code_understanding/tools_register.py#L228) (legacy flag) or bundled `roam_code` skill |
| **openwiki** | [`openwiki_runner.py`](../../src/sevn/code_understanding/openwiki_runner.py) | [`build_openwiki_argv`](../../src/sevn/code_understanding/openwiki_runner.py#L100), [`run_openwiki_subprocess`](../../src/sevn/code_understanding/openwiki_runner.py#L184) |
| CGR export | [`cgr_adapter.py`](../../src/sevn/code_understanding/cgr_adapter.py), [`cgr_runner.py`](../../src/sevn/code_understanding/cgr_runner.py) | Allowlisted [`build_cgr_argv`](../../src/sevn/code_understanding/cgr_adapter.py#L20) subprocess |

Tools outside `tools/**` globs register via [`register_code_understanding_tools`](../../src/sevn/code_understanding/tools_register.py) at session boot ([`registry.py`](../../src/sevn/tools/registry.py#L1634)).

### Key modules

- [`bootstrap.py`](../../src/sevn/code_understanding/bootstrap.py) — MYCODE/Graphify doctor + cache refresh
- [`graphify_seed.py`](../../src/sevn/code_understanding/graphify_seed.py) — AST graph seeding in workspace mirror
- [`tools_register.py`](../../src/sevn/code_understanding/tools_register.py) — roam-code + orientation tool registration
- [`openwiki_runner.py`](../../src/sevn/code_understanding/openwiki_runner.py) — openwiki CLI subprocess helpers
- [`code_index.py`](../../src/sevn/code_understanding/code_index.py) — deterministic `.index/code_index/INDEX.md` generator

Normative spec: [`28-code-understanding.md`](../../about-sevn.bot/specs/28-code-understanding.md).


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
