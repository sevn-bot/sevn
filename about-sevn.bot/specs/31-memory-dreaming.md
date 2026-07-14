---
id: spec-31-memory-dreaming
kind: spec
title: Memory — Dreaming — Spec
status: scaffold
owner: Alex
summary: Provide scored consolidation from short-term recall signals into curated
  long-term prose (MEMORY.md) on a daily (configurable) cadence, without mutating
  LCM tables or crossing into Second Brain (wiki/
last_updated: '2026-07-12'
fingerprint: sha256:c6e40f612e54a561b469d42b154b5c51b9e337c3b822c757343df49f56c60e75
related: []
sources:
- src/sevn/memory/dreaming/**
parent_prd: prd-02-personality-and-memory
depends_on:
- spec-02-config-and-workspace
- spec-03-storage
- spec-04-tracing
- spec-05-llm-transports
- spec-09-security-scanner
- spec-15-memory-lcm
- spec-23-cli
- spec-24-dashboard
- spec-30-non-interactive-triggers
build_phase: null
interfaces:
- name: format_ack_required_trace_attrs
  file: src/sevn/memory/dreaming/ack_policy.py
  symbol: format_ack_required_trace_attrs
- name: iter_backfill_dates
  file: src/sevn/memory/dreaming/backfill.py
  symbol: iter_backfill_dates
- name: DreamingEngine
  file: src/sevn/memory/dreaming/engine.py
  symbol: DreamingEngine
- name: content_has_llmignore_provenance
  file: src/sevn/memory/dreaming/filters.py
  symbol: content_has_llmignore_provenance
- name: lcm_channel_allows_dreaming
  file: src/sevn/memory/dreaming/filters.py
  symbol: lcm_channel_allows_dreaming
- name: session_allows_dreaming
  file: src/sevn/memory/dreaming/filters.py
  symbol: session_allows_dreaming
- name: DreamingCandidate
  file: src/sevn/memory/dreaming/models.py
  symbol: DreamingCandidate
- name: DreamingRunResult
  file: src/sevn/memory/dreaming/models.py
  symbol: DreamingRunResult
- name: MemoryMdAnchor
  file: src/sevn/memory/dreaming/models.py
  symbol: MemoryMdAnchor
- name: PromotedBatchManifest
  file: src/sevn/memory/dreaming/models.py
  symbol: PromotedBatchManifest
- name: PromotedManifestRow
  file: src/sevn/memory/dreaming/models.py
  symbol: PromotedManifestRow
- name: append_dreams_diary
  file: src/sevn/memory/dreaming/promoter.py
  symbol: append_dreams_diary
- name: build_run_result
  file: src/sevn/memory/dreaming/promoter.py
  symbol: build_run_result
- name: dreams_dir
  file: src/sevn/memory/dreaming/promoter.py
  symbol: dreams_dir
- name: ensure_tree
  file: src/sevn/memory/dreaming/promoter.py
  symbol: ensure_tree
- name: promote_auto_batch
  file: src/sevn/memory/dreaming/promoter.py
  symbol: promote_auto_batch
- name: render_memory_lines
  file: src/sevn/memory/dreaming/promoter.py
  symbol: render_memory_lines
- name: write_candidate_snapshot
  file: src/sevn/memory/dreaming/promoter.py
  symbol: write_candidate_snapshot
- name: write_pending_files
  file: src/sevn/memory/dreaming/promoter.py
  symbol: write_pending_files
- name: format_run_summary
  file: src/sevn/memory/dreaming/review.py
  symbol: format_run_summary
- name: latest_promoted_manifest
  file: src/sevn/memory/dreaming/rollback.py
  symbol: latest_promoted_manifest
- name: rollback_last_auto_batch
  file: src/sevn/memory/dreaming/rollback.py
  symbol: rollback_last_auto_batch
- name: rollback_manifest
  file: src/sevn/memory/dreaming/rollback.py
  symbol: rollback_manifest
- name: effective_dreaming
  file: src/sevn/memory/dreaming/scheduler.py
  symbol: effective_dreaming
- name: reconcile_dreaming_cron_job
  file: src/sevn/memory/dreaming/scheduler.py
  symbol: reconcile_dreaming_cron_job
- name: build_candidates
  file: src/sevn/memory/dreaming/scorer.py
  symbol: build_candidates
- name: maybe_llm_rerank
  file: src/sevn/memory/dreaming/scorer.py
  symbol: maybe_llm_rerank
- name: RawMemorySignal
  file: src/sevn/memory/dreaming/sources.py
  symbol: RawMemorySignal
- name: load_daily_log_signals
  file: src/sevn/memory/dreaming/sources.py
  symbol: load_daily_log_signals
- name: load_lcm_summary_signals
  file: src/sevn/memory/dreaming/sources.py
  symbol: load_lcm_summary_signals
- name: load_memory_signals
  file: src/sevn/memory/dreaming/sources.py
  symbol: load_memory_signals
specs: []
personas: []
prd_profile: null
---


## Purpose

Provide scored consolidation from short-term recall signals into curated long-term prose (MEMORY.md) on a daily (configurable) cadence, without mutating LCM tables or crossing into Second Brain (wiki/

Primary code trees: [`src/sevn/memory/dreaming`](src/sevn/memory/dreaming/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`format_ack_required_trace_attrs`](src/sevn/memory/dreaming/ack_policy.py) — `src/sevn/memory/dreaming/ack_policy.py`
- [`iter_backfill_dates`](src/sevn/memory/dreaming/backfill.py) — `src/sevn/memory/dreaming/backfill.py`
- [`DreamingEngine`](src/sevn/memory/dreaming/engine.py) — `src/sevn/memory/dreaming/engine.py`
- [`content_has_llmignore_provenance`](src/sevn/memory/dreaming/filters.py) — `src/sevn/memory/dreaming/filters.py`
- [`lcm_channel_allows_dreaming`](src/sevn/memory/dreaming/filters.py) — `src/sevn/memory/dreaming/filters.py`
- [`session_allows_dreaming`](src/sevn/memory/dreaming/filters.py) — `src/sevn/memory/dreaming/filters.py`
- [`DreamingCandidate`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`DreamingRunResult`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`MemoryMdAnchor`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`PromotedBatchManifest`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`PromotedManifestRow`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`append_dreams_diary`](src/sevn/memory/dreaming/promoter.py) — `src/sevn/memory/dreaming/promoter.py`
- _…and 19 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`format_ack_required_trace_attrs`](src/sevn/memory/dreaming/ack_policy.py) — `src/sevn/memory/dreaming/ack_policy.py`
- [`iter_backfill_dates`](src/sevn/memory/dreaming/backfill.py) — `src/sevn/memory/dreaming/backfill.py`
- [`DreamingEngine`](src/sevn/memory/dreaming/engine.py) — `src/sevn/memory/dreaming/engine.py`
- [`content_has_llmignore_provenance`](src/sevn/memory/dreaming/filters.py) — `src/sevn/memory/dreaming/filters.py`
- [`lcm_channel_allows_dreaming`](src/sevn/memory/dreaming/filters.py) — `src/sevn/memory/dreaming/filters.py`
- [`session_allows_dreaming`](src/sevn/memory/dreaming/filters.py) — `src/sevn/memory/dreaming/filters.py`
- [`DreamingCandidate`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`DreamingRunResult`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`MemoryMdAnchor`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`PromotedBatchManifest`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`PromotedManifestRow`](src/sevn/memory/dreaming/models.py) — `src/sevn/memory/dreaming/models.py`
- [`append_dreams_diary`](src/sevn/memory/dreaming/promoter.py) — `src/sevn/memory/dreaming/promoter.py`
- _…and 19 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/memory/dreaming`](src/sevn/memory/dreaming/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/memory/dreaming`](src/sevn/memory/dreaming/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
