<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint memory-context` -->
# Memory & context — LCM store, compaction, user model, dreaming, and Honcho opt-ins

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** LCM store, compaction, user model, dreaming, and Honcho opt-ins.

## Level 1 — Overview (non-technical)

**Memory & context** keeps conversations usable without losing history. **LCM** (Lossless Conversation Memory) stores every qualifying message, compacts it into summaries, and assembles context for each turn. **Dreaming** promotes scored recall signals into long-term `MEMORY.md` prose at the workspace root. **Honcho-style user model** (opt-in) accumulates inferred operator facts in `.sevn/user_model.json`.

Second Brain wiki vault is a separate subsystem — see [`second-brain.md`](second-brain.md).

## Level 2 — How it works (technical)

Implementation spans [`src/sevn/lcm/`](../../src/sevn/lcm/) (lossless store + assembly) and [`src/sevn/memory/`](../../src/sevn/memory/) (dreaming, user model, search telemetry).

### LCM and dreaming split

| Concern | Package | Key entry points |
| --- | --- | --- |
| Ingest | [`lcm/engine.py`](../../src/sevn/lcm/engine.py) | [`LcmEngine.ingest`](../../src/sevn/lcm/engine.py#L242) |
| Assemble context | [`lcm/assembler.py`](../../src/sevn/lcm/assembler.py) | [`LcmAssembler.assemble`](../../src/sevn/lcm/assembler.py#L69) |
| Compaction | [`lcm/compaction.py`](../../src/sevn/lcm/compaction.py) | [`CompactionScheduler.run_incremental`](../../src/sevn/lcm/compaction.py#L100) |
| Post-turn hooks | [`lcm/engine.py`](../../src/sevn/lcm/engine.py) | [`LcmEngine.after_turn`](../../src/sevn/lcm/engine.py#L446) |
| Dreaming → MEMORY.md | [`memory/dreaming/engine.py`](../../src/sevn/memory/dreaming/engine.py) | [`DreamingEngine.run_scheduled`](../../src/sevn/memory/dreaming/engine.py#L110) promotes via [`promoter.py`](../../src/sevn/memory/dreaming/promoter.py) |
| Honcho user model | [`memory/user_model/`](../../src/sevn/memory/user_model/) | [`UserModelExtractor`](../../src/sevn/memory/user_model/extractor.py#L52), [`schedule_user_model_extraction`](../../src/sevn/memory/user_model/queue.py#L84) |

Dreaming reads recall signals ([`memory/dreaming/sources.py`](../../src/sevn/memory/dreaming/sources.py)), scores candidates ([`scorer.py`](../../src/sevn/memory/dreaming/scorer.py)), and appends bullets to workspace `MEMORY.md` — it does **not** mutate LCM tables.

User-model extraction is gated by [`user_model_extraction_enabled`](../../src/sevn/config/model_resolution.py#L827); persistence via [`UserModelStore`](../../src/sevn/memory/user_model/store.py#L146) under `.sevn/user_model.json`.

### Key modules

- [`lcm/engine.py`](../../src/sevn/lcm/engine.py) — ingest/assemble/after_turn façade
- [`lcm/compaction.py`](../../src/sevn/lcm/compaction.py) — incremental compaction scheduler
- [`memory/dreaming/engine.py`](../../src/sevn/memory/dreaming/engine.py) — cron-invoked dreaming pipeline
- [`memory/user_model/extractor.py`](../../src/sevn/memory/user_model/extractor.py) — structured LLM profile extraction
- [`memory/search_telemetry.py`](../../src/sevn/memory/search_telemetry.py) — recall signals for dreaming

Normative specs: [`15-memory-lcm.md`](../../about-sevn.bot/specs/15-memory-lcm.md), [`31-memory-dreaming.md`](../../about-sevn.bot/specs/31-memory-dreaming.md), [`32-memory-honcho.md`](../../about-sevn.bot/specs/32-memory-honcho.md).


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
