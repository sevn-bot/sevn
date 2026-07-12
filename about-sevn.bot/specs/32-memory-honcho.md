---
id: spec-32-memory-honcho
kind: spec
title: Memory — Honcho-style user model — Spec
status: done
owner: Alex
summary: Deliver an opt-in inferred profile that accumulates stable operator-facing
  facts (preferences, recurring context the operator states in chat) without requiring
  manual USER.md edits for every drift. Wh
last_updated: '2026-07-12'
fingerprint: sha256:3acf237a4bd55e13e11e5460ee9356083af5b7d550de051a2d63cde5681034b4
related: []
sources:
- src/sevn/memory/**
parent_prd: prd-02-personality-and-memory
depends_on:
- spec-05-llm-transports
- spec-15-memory-lcm
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
- name: load_recall_weights
  file: src/sevn/memory/search_telemetry.py
  symbol: load_recall_weights
- name: record_memory_recall_signal
  file: src/sevn/memory/search_telemetry.py
  symbol: record_memory_recall_signal
- name: record_memory_search_event
  file: src/sevn/memory/search_telemetry.py
  symbol: record_memory_search_event
- name: UserModelControl
  file: src/sevn/memory/user_model/control.py
  symbol: UserModelControl
- name: topic_denied
  file: src/sevn/memory/user_model/deny_topics.py
  symbol: topic_denied
- name: UserModelExtractor
  file: src/sevn/memory/user_model/extractor.py
  symbol: UserModelExtractor
- name: UserModelMerger
  file: src/sevn/memory/user_model/merger.py
  symbol: UserModelMerger
- name: InferredFact
  file: src/sevn/memory/user_model/models.py
  symbol: InferredFact
- name: UserProfile
  file: src/sevn/memory/user_model/models.py
  symbol: UserProfile
- name: UserModelExtractionQueue
  file: src/sevn/memory/user_model/queue.py
  symbol: UserModelExtractionQueue
- name: schedule_user_model_extraction
  file: src/sevn/memory/user_model/queue.py
  symbol: schedule_user_model_extraction
- name: render_profile_block
  file: src/sevn/memory/user_model/renderer.py
  symbol: render_profile_block
- name: UserModelStore
  file: src/sevn/memory/user_model/store.py
  symbol: UserModelStore
- name: personality_bump_allowed
  file: src/sevn/memory/user_model/throttle.py
  symbol: personality_bump_allowed
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Purpose.

## Public Interface

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Public Interface.

## Data Model

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Data Model.

## Internal Architecture

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Internal Architecture.

## Behavior

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Behavior.

## Failure Modes

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Failure Modes.

## Test Strategy

Offline scaffold for Memory — Honcho-style user model — Spec (spec-32-memory-honcho) — Test Strategy.
