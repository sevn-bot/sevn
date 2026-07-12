<!-- generated: do not edit by hand; run `sevn readme update memory-context` -->
# Memory & context — LCM store, compaction, user model, dreaming, and Honcho opt-ins

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** LCM store, compaction, user model, dreaming, and Honcho opt-ins.

## Level 1 — Overview (non-technical)

**Memory & context** is a core part of sevn.bot — the personal AI assistant you run on your own machine. LCM store, compaction, user model, dreaming, and Honcho opt-ins.

In everyday use, memory & context helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

LCM is the lossless conversation memory for a workspace (prd-02-personality-and-memory §5.2–§5.4): every qualifying message is stored; compaction summarises without deleting source rows; the assembler

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/memory/`. The package contains 34 Python module(s); primary entry points include `src/sevn/lcm/__init__.py`, `src/sevn/lcm/assembler.py`, `src/sevn/lcm/compaction.py`, `src/sevn/lcm/engine.py`, and 2 more.

### Data and control flow

Memory & context sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/15-memory-lcm.md`, `specs/31-memory-dreaming.md`, `specs/32-memory-honcho.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/lcm/assembler.py` — `LcmAssembler.assemble`
- `src/sevn/lcm/compaction.py` — `completion_text`, `CompactionScheduler.run_incremental`
- `src/sevn/lcm/engine.py` — `LcmEngine.ingest`, `LcmEngine.assemble`, `LcmEngine.after_turn`, `LcmEngine (+4 methods)`
- `src/sevn/lcm/flush.py` — `is_allowlisted_relative_path`, `validate_memory_writes`, `run_flush_decode_with_retry_once`
- `src/sevn/lcm/large_files.py` — `maybe_spill_large_payload`

### Spec context

From specs/15-memory-lcm.md:
LCM is the lossless conversation memory for a workspace (prd-02-personality-and-memory §5.2–§5.4): every qualifying message is stored; compaction summarises without deleting source rows; the assembler

From specs/31-memory-dreaming.md:
Provide scored consolidation from short-term recall signals into curated long-term prose (MEMORY.md) on a daily (configurable) cadence, without mutating LCM tables or crossing into Second Brain (wiki/

From specs/32-memory-honcho.md:
Deliver an opt-in inferred profile that accumulates stable operator-facing facts (preferences, recurring context the operator states in chat) without requiring manual USER.md edits for every drift. Wh

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/memory/` (34 Python files). Normative design: `specs/15-memory-lcm.md`, `specs/31-memory-dreaming.md`, `specs/32-memory-honcho.md`.

### Module inventory

- `src/sevn/lcm/__init__.py` — """Lossless context management ('specs/15-memory-lcm.md').
- `src/sevn/lcm/assembler.py` — """Context assembly: fresh tail plus newest-first summaries ('specs/15-memory-lcm.md' §4).
- `src/sevn/lcm/compaction.py` — """Compaction scheduler — leaf summaries + optional condensation ('specs/15-memory-lcm.md' §2.5, §4).
- `src/sevn/lcm/engine.py` — """LCM engine façade — ingest, assemble, compaction, search ('specs/15-memory-lcm.md' §2).
- `src/sevn/lcm/flush.py` — """Pre-compaction flush: ''MemoryWrites'' validation and retry-once policy.
- `src/sevn/lcm/large_files.py` — """Oversized inbound payloads spill into ''lcm_large_files'' ('specs/15-memory-lcm.md' §3).
- `src/sevn/lcm/query.py` — """Read-only LCM query helpers for bundled skill scripts ('specs/15-memory-lcm.md' §3).
- `src/sevn/lcm/script_cli.py` — """Shared CLI helpers for bundled ''lcm'' skill scripts.
- `src/sevn/lcm/search.py` — """Session-summary keyword search over ''lcm_summaries''.
- `src/sevn/memory/__init__.py` — """Workspace memory helpers (LCM-adjacent; optional subsystems).
- `src/sevn/memory/dreaming/__init__.py` — """Optional Dreaming consolidation ('specs/31-memory-dreaming.md')."""
- `src/sevn/memory/dreaming/ack_policy.py` — """Dreaming ''ack_required'' operator surface ('specs/31-memory-dreaming.md' §2, §11).
- … and 22 more Python modules

### Assembler (`src/sevn/lcm/assembler.py`)

Public entry points:
- `LcmAssembler.assemble` — see `src/sevn/lcm/assembler.py`

### Compaction (`src/sevn/lcm/compaction.py`)

Public entry points:
- `completion_text` — see `src/sevn/lcm/compaction.py`
- `CompactionScheduler.run_incremental` — see `src/sevn/lcm/compaction.py`

### Engine (`src/sevn/lcm/engine.py`)

Public entry points:
- `LcmEngine.ingest` — see `src/sevn/lcm/engine.py`
- `LcmEngine.assemble` — see `src/sevn/lcm/engine.py`
- `LcmEngine.after_turn` — see `src/sevn/lcm/engine.py`
- `LcmEngine (+4 methods)` — see `src/sevn/lcm/engine.py`

### Flush (`src/sevn/lcm/flush.py`)

Public entry points:
- `is_allowlisted_relative_path` — see `src/sevn/lcm/flush.py`
- `validate_memory_writes` — see `src/sevn/lcm/flush.py`
- `run_flush_decode_with_retry_once` — see `src/sevn/lcm/flush.py`

### Large Files (`src/sevn/lcm/large_files.py`)

Public entry points:
- `maybe_spill_large_payload` — see `src/sevn/lcm/large_files.py`

### Query (`src/sevn/lcm/query.py`)

Public entry points:
- `resolve_conversation_id` — see `src/sevn/lcm/query.py`
- `conversation_ids_for_scope` — see `src/sevn/lcm/query.py`
- `grep_messages` — see `src/sevn/lcm/query.py`
- `describe_item` — see `src/sevn/lcm/query.py`
- `fetch_message` — see `src/sevn/lcm/query.py`
- `fetch_recent_messages` — see `src/sevn/lcm/query.py`
- `expand_summary` — see `src/sevn/lcm/query.py`
- `expand_query` — see `src/sevn/lcm/query.py`

### Script Cli (`src/sevn/lcm/script_cli.py`)

Public entry points:
- `cap_script_row_limit` — see `src/sevn/lcm/script_cli.py`
- `workspace_from_env` — see `src/sevn/lcm/script_cli.py`
- `open_workspace_db` — see `src/sevn/lcm/script_cli.py`
- `session_key_from` — see `src/sevn/lcm/script_cli.py`
- `write_ok` — see `src/sevn/lcm/script_cli.py`
- `write_error` — see `src/sevn/lcm/script_cli.py`

### Search (`src/sevn/lcm/search.py`)

Public entry points:
- `search_session_summaries` — see `src/sevn/lcm/search.py`

### Additional modules

22 more Python files under `src/sevn/memory/` — including `src/sevn/memory/dreaming/backfill.py`, `src/sevn/memory/dreaming/defaults.py`, `src/sevn/memory/dreaming/engine.py`, `src/sevn/memory/dreaming/filters.py`.

### Extension and invariants

Follow `specs/15-memory-lcm.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/memory/`, run `sevn readme update memory-context` and `make readme-check`.

## References

- [specs/15-memory-lcm.md](specs/15-memory-lcm.md)
- [specs/31-memory-dreaming.md](specs/31-memory-dreaming.md)
- [specs/32-memory-honcho.md](specs/32-memory-honcho.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/15-memory-lcm.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/memory/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
