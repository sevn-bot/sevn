<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint second-brain` -->
# Second brain — Wiki vault layout, ingest paths, and wikilink-compatible provenance for operator knowledge

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Wiki vault layout, ingest paths, and wikilink-compatible provenance for operator knowledge.

## Level 1 — Overview (non-technical)

**Second brain** is sevn.bot's operator wiki vault: capture sources under `raw/`, curate pages under `wiki/`, and search/apply wikilinks compatible with Obsidian-style layouts. It is **not** a sync daemon — sevn provides wikilink/layout compatibility and ingest tooling, not bidirectional Obsidian sync.

Tools [`wiki_search`](../../src/sevn/second_brain/__init__.py), [`wiki_get`](../../src/sevn/second_brain/__init__.py), [`wiki_apply`](../../src/sevn/second_brain/__init__.py), and [`wiki_lint`](../../src/sevn/second_brain/__init__.py) expose the vault to the agent.

## Level 2 — How it works (technical)

Package [`src/sevn/second_brain/`](../../src/sevn/second_brain/). Vault paths resolve through [`paths.py`](../../src/sevn/second_brain/paths.py).

### Vault layout and Obsidian resolution

| Path (under scope) | Purpose |
| --- | --- |
| `raw/` | Captured sources (URL fetch, uploads) — [`fetch_url_to_raw`](../../src/sevn/second_brain/fetch.py#L100) |
| `wiki/` | Curated markdown pages + [`wiki/index.md`](../../src/sevn/second_brain/query.py) |
| `wiki/ingests/` | Ingested/stub pages from raw — [`run_ingest`](../../src/sevn/second_brain/ingest.py#L145) |
| `outputs/` | Generated artefacts |

**Custom vault root:** `sevn.json` → `second_brain.paths.vault` resolves via [`resolve_vault_base`](../../src/sevn/second_brain/paths.py#L108) (legacy default: [`vault_root`](../../src/sevn/second_brain/paths.py#L32) → `second_brain/` under content root). Obsidian operators set `paths.vault` to their vault directory; doctor probes layout with [`probe_second_brain_vault_layout`](../../src/sevn/second_brain/layout_probe.py#L71).

Wikilink resolution: [`resolve_wiki_target`](../../src/sevn/second_brain/links.py#L98). Scope bootstrap: [`ensure_second_brain_scope_layout`](../../src/sevn/second_brain/bootstrap.py#L49).

Gateway boot registers tools via [`register_second_brain_tools`](../../src/sevn/second_brain/__init__.py#L562).

### Key modules

- [`paths.py`](../../src/sevn/second_brain/paths.py) — [`resolve_vault_base`](../../src/sevn/second_brain/paths.py#L108), scope roots
- [`ingest.py`](../../src/sevn/second_brain/ingest.py) — raw → wiki ingest pipeline
- [`__init__.py`](../../src/sevn/second_brain/__init__.py) — wiki tool registration
- [`bootstrap.py`](../../src/sevn/second_brain/bootstrap.py) — idempotent layout creation
- [`layout_probe.py`](../../src/sevn/second_brain/layout_probe.py) — doctor vault layout checks

Normative spec: [`27-second-brain.md`](../../about-sevn.bot/specs/27-second-brain.md).


## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/second_brain`](../../src/sevn/second_brain/) (18 Python files). Normative design: `about-sevn.bot/specs/27-second-brain.md`.

### Module inventory

Second Brain wiki engine + tool registration (about-sevn.bot/specs/27-second-brain.md section 2.1-2.2).

Working with [`__init__.py`](../../src/sevn/second_brain/__init__.py): inspect the public entry points below.
Start with [`wiki_search_tool`](../../src/sevn/second_brain/__init__.py#L151), then [`wiki_get_tool`](../../src/sevn/second_brain/__init__.py#L210), [`wiki_apply_tool`](../../src/sevn/second_brain/__init__.py#L264), [`wiki_lint_tool`](../../src/sevn/second_brain/__init__.py#L349).

Idempotent Second Brain scope layout bootstrap (about-sevn.bot/specs/27-second-brain.md §3.2).

Working with [`bootstrap.py`](../../src/sevn/second_brain/bootstrap.py): inspect the public entry points below.
Start with [`ensure_second_brain_scope_layout`](../../src/sevn/second_brain/bootstrap.py#L49).

Second Brain failure types (about-sevn.bot/specs/27-second-brain.md §6).

Working with [`errors.py`](../../src/sevn/second_brain/errors.py): inspect the public entry points below.

HTTPS URL → raw/ fetch helper (about-sevn.bot/specs/27-second-brain.md §2.4, §5).

Invoked from the gateway with httpx; enforces allowlist, size, MIME, timeout. No partial
writes on rejection (about-sevn.bot/specs/27-second-brain.md §6).

Working with [`fetch.py`](../../src/sevn/second_brain/fetch.py): inspect the public entry points below.
Start with [`fetch_url_to_raw`](../../src/sevn/second_brain/fetch.py#L100).

Workspace-relative folder browser helpers for Second Brain vault pickers.

Working with [`folder_picker.py`](../../src/sevn/second_brain/folder_picker.py): inspect the public entry points below.
Start with [`normalise_browse_path`](../../src/sevn/second_brain/folder_picker.py#L28), then [`list_workspace_subdirs`](../../src/sevn/second_brain/folder_picker.py#L56).

YAML frontmatter parse/merge for wiki pages (about-sevn.bot/specs/27-second-brain.md §3.3).

Working with [`frontmatter.py`](../../src/sevn/second_brain/frontmatter.py): inspect the public entry points below.
Start with [`split_frontmatter`](../../src/sevn/second_brain/frontmatter.py#L31), then [`dumps_frontmatter`](../../src/sevn/second_brain/frontmatter.py#L62), [`normalise_agent_keys`](../../src/sevn/second_brain/frontmatter.py#L87), [`okf_type_required`](../../src/sevn/second_brain/frontmatter.py#L117).

Deterministic raw→wiki ingest pipeline (about-sevn.bot/specs/27-second-brain.md §2.2).

Working with [`ingest.py`](../../src/sevn/second_brain/ingest.py): inspect the public entry points below.
Start with [`raw_content_hash`](../../src/sevn/second_brain/ingest.py#L20), then [`run_ingest`](../../src/sevn/second_brain/ingest.py#L145).

Idempotent stub ingest (about-sevn.bot/specs/27-second-brain.md §2.2).

Working with [`ingest_stub.py`](../../src/sevn/second_brain/ingest_stub.py): inspect the public entry points below.
Start with [`run_ingest_stub`](../../src/sevn/second_brain/ingest_stub.py#L72).

Second Brain vault layout checks for sevn doctor.

Working with [`layout_probe.py`](../../src/sevn/second_brain/layout_probe.py): inspect the public entry points below.
Start with [`probe_second_brain_vault_layout`](../../src/sevn/second_brain/layout_probe.py#L71), then [`fix_second_brain_layout`](../../src/sevn/second_brain/layout_probe.py#L138).

Internal wiki link extraction and resolution (OKF + Obsidian wikilinks).

Working with [`links.py`](../../src/sevn/second_brain/links.py): inspect the public entry points below.
Start with [`iter_internal_link_targets`](../../src/sevn/second_brain/links.py#L72), then [`resolve_wiki_target`](../../src/sevn/second_brain/links.py#L98), [`index_line_targets`](../../src/sevn/second_brain/links.py#L131).

Local wiki lint rules (about-sevn.bot/specs/27-second-brain.md §2.2).

Working with [`lint_local.py`](../../src/sevn/second_brain/lint_local.py): inspect the public entry points below.
Start with [`lint_wiki_tree`](../../src/sevn/second_brain/lint_local.py#L54), then [`issues_to_json`](../../src/sevn/second_brain/lint_local.py#L148).

Optional git merge conflict path (about-sevn.bot/specs/27-second-brain.md §4, PRD §5.8).

Working with [`merge.py`](../../src/sevn/second_brain/merge.py): inspect the public entry points below.
Start with [`try_git_merge`](../../src/sevn/second_brain/merge.py#L18).

6 more Python files under [`src/sevn/second_brain`](../../src/sevn/second_brain/) — including `src/sevn/second_brain/paths.py`, `src/sevn/second_brain/query.py`, `src/sevn/second_brain/search.py`, `src/sevn/second_brain/wiki_io.py`.

### Extension and invariants

Follow [`27-second-brain.md`](../../about-sevn.bot/specs/27-second-brain.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/second_brain`](../../src/sevn/second_brain/), run `sevn readme update second-brain` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/27-second-brain.md](../../about-sevn.bot/specs/27-second-brain.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/27-second-brain.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/second_brain/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
