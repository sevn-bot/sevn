<!-- generated: do not edit by hand; run `sevn readme update memory-context` -->
# Memory & context — LCM store, compaction, user model, dreaming, and Honcho opt-ins

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** LCM store, compaction, user model, dreaming, and Honcho opt-ins.

## Level 1 — Overview (non-technical)

**Memory & context** is a core part of sevn.bot — the personal AI assistant you run on your own machine. LCM store, compaction, user model, dreaming, and Honcho opt-ins.

In everyday use, memory & context helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation spans `src/sevn/lcm/`, `src/sevn/memory/`. The package contains 34 Python module(s); primary entry points include `src/sevn/lcm/__init__.py`, `src/sevn/lcm/assembler.py`, `src/sevn/lcm/compaction.py`, `src/sevn/lcm/engine.py`, `src/sevn/lcm/flush.py`, `src/sevn/lcm/large_files.py`, and 28 more.

### Data and control flow

Memory & context is organized around `  init  `, `assembler`, `compaction`, `engine`, and 2 more under `src/sevn/memory/`; implementation spans `src/sevn/lcm/`, `src/sevn/memory/`. Primary entry points include assembler.py (LcmAssembler.assemble), compaction.py (completion_text), engine.py (LcmEngine.ingest), flush.py (is_allowlisted_relative_path).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/15-memory-lcm.md`, `about-sevn.bot/specs/31-memory-dreaming.md`, `about-sevn.bot/specs/32-memory-honcho.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/lcm/assembler.py` — `LcmAssembler.assemble`
- `src/sevn/lcm/compaction.py` — `completion_text`, `CompactionScheduler.run_incremental`
- `src/sevn/lcm/engine.py` — `LcmEngine.ingest`, `LcmEngine.assemble`, `LcmEngine.after_turn`, `LcmEngine (+4 methods)`
- `src/sevn/lcm/flush.py` — `is_allowlisted_relative_path`, `validate_memory_writes`, `run_flush_decode_with_retry_once`
- `src/sevn/lcm/large_files.py` — `maybe_spill_large_payload`

### Spec context

From about-sevn.bot/specs/15-memory-lcm.md:
LCM is the lossless conversation memory for a workspace (prd-02-personality-and-memory §5.2–§5.4): every qualifying message is stored; compaction summarises without deleting source rows; the assembler

From about-sevn.bot/specs/31-memory-dreaming.md:
Provide scored consolidation from short-term recall signals into curated long-term prose (MEMORY.md) on a daily (configurable) cadence, without mutating LCM tables or crossing into Second Brain (wiki/

From about-sevn.bot/specs/32-memory-honcho.md:
Deliver an opt-in inferred profile that accumulates stable operator-facing facts (preferences, recurring context the operator states in chat) without requiring manual USER.md edits for every drift.

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/memory`](../../src/sevn/memory/) (34 Python files). Normative design: `about-sevn.bot/specs/15-memory-lcm.md`, `about-sevn.bot/specs/31-memory-dreaming.md`, `about-sevn.bot/specs/32-memory-honcho.md`.

### Module inventory

Lossless context management (about-sevn.bot/specs/15-memory-lcm.md).

Working with [`__init__.py`](../../src/sevn/lcm/__init__.py): inspect the public entry points below.

Context assembly: fresh tail plus newest-first summaries (about-sevn.bot/specs/15-memory-lcm.md §4).

Working with [`assembler.py`](../../src/sevn/lcm/assembler.py): inspect the public entry points below.
Start with [`LcmAssembler.assemble`](../../src/sevn/lcm/assembler.py#L69).

Compaction scheduler — leaf summaries + optional condensation (about-sevn.bot/specs/15-memory-lcm.md §2.5, §4).

Working with [`compaction.py`](../../src/sevn/lcm/compaction.py): inspect the public entry points below.
Start with [`completion_text`](../../src/sevn/lcm/compaction.py#L37), then [`CompactionScheduler.run_incremental`](../../src/sevn/lcm/compaction.py#L100).

LCM engine façade — ingest, assemble, compaction, search (about-sevn.bot/specs/15-memory-lcm.md §2).

Working with [`engine.py`](../../src/sevn/lcm/engine.py): inspect the public entry points below.
Start with [`LcmEngine.ingest`](../../src/sevn/lcm/engine.py#L242), then [`LcmEngine.assemble`](../../src/sevn/lcm/engine.py#L402), [`LcmEngine.after_turn`](../../src/sevn/lcm/engine.py#L446).

Pre-compaction flush: MemoryWrites validation and retry-once policy.

Working with [`flush.py`](../../src/sevn/lcm/flush.py): inspect the public entry points below.
Start with [`is_allowlisted_relative_path`](../../src/sevn/lcm/flush.py#L78), then [`validate_memory_writes`](../../src/sevn/lcm/flush.py#L108), [`run_flush_decode_with_retry_once`](../../src/sevn/lcm/flush.py#L137).

Oversized inbound payloads spill into lcm_large_files (about-sevn.bot/specs/15-memory-lcm.md §3).

v1 stores **full text in SQLite** on the content column and leaves storage_path null
until a future slice optionally relocates bytes under workspace-relative paths (never under
.llmignore/). byte_size records UTF-8 length for operator dashboards.

Working with [`large_files.py`](../../src/sevn/lcm/large_files.py): inspect the public entry points below.
Start with [`maybe_spill_large_payload`](../../src/sevn/lcm/large_files.py#L41).

Read-only LCM query helpers for bundled skill scripts (about-sevn.bot/specs/15-memory-lcm.md §3).

Working with [`query.py`](../../src/sevn/lcm/query.py): inspect the public entry points below.
Start with [`resolve_conversation_id`](../../src/sevn/lcm/query.py#L79), then [`conversation_ids_for_scope`](../../src/sevn/lcm/query.py#L104), [`grep_messages`](../../src/sevn/lcm/query.py#L166), [`describe_item`](../../src/sevn/lcm/query.py#L278).

Shared CLI helpers for bundled lcm skill scripts.

Working with [`script_cli.py`](../../src/sevn/lcm/script_cli.py): inspect the public entry points below.
Start with [`cap_script_row_limit`](../../src/sevn/lcm/script_cli.py#L41), then [`workspace_from_env`](../../src/sevn/lcm/script_cli.py#L59), [`open_workspace_db`](../../src/sevn/lcm/script_cli.py#L72), [`session_key_from`](../../src/sevn/lcm/script_cli.py#L96).

Session-summary keyword search over lcm_summaries.

Working with [`search.py`](../../src/sevn/lcm/search.py): inspect the public entry points below.
Start with [`search_session_summaries`](../../src/sevn/lcm/search.py#L44).

Workspace memory helpers (LCM-adjacent; optional subsystems).

Working with [`__init__.py`](../../src/sevn/memory/__init__.py): inspect the public entry points below.

Optional Dreaming consolidation (about-sevn.bot/specs/31-memory-dreaming.md).

Working with [`__init__.py`](../../src/sevn/memory/dreaming/__init__.py): inspect the public entry points below.

Dreaming ack_required operator surface (about-sevn.bot/specs/31-memory-dreaming.md §2, §11).

Working with [`ack_policy.py`](../../src/sevn/memory/dreaming/ack_policy.py): inspect the public entry points below.
Start with [`format_ack_required_trace_attrs`](../../src/sevn/memory/dreaming/ack_policy.py#L23).

22 more Python files under [`src/sevn/memory`](../../src/sevn/memory/) — including `src/sevn/memory/dreaming/backfill.py`, `src/sevn/memory/dreaming/defaults.py`, `src/sevn/memory/dreaming/engine.py`, `src/sevn/memory/dreaming/filters.py`.

### Extension and invariants

Follow [`15-memory-lcm.md`](../../about-sevn.bot/specs/15-memory-lcm.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/memory`](../../src/sevn/memory/), run `sevn readme update memory-context` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/15-memory-lcm.md](../../about-sevn.bot/specs/15-memory-lcm.md)
- [../../about-sevn.bot/specs/31-memory-dreaming.md](../../about-sevn.bot/specs/31-memory-dreaming.md)
- [../../about-sevn.bot/specs/32-memory-honcho.md](../../about-sevn.bot/specs/32-memory-honcho.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/15-memory-lcm.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/memory/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
