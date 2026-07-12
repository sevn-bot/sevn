---
id: spec-33-self-improvement
kind: spec
title: Self-improvement — Spec
status: done
owner: Alex
summary: 'Deliver src/sevn/self_improve/: ingest traces + session artefacts + explicit
  user feedback into trajectory_fact rows, deterministically shortlist turns for review
  or patching, optionally run an in-pro'
last_updated: '2026-06-19'
fingerprint: sha256:710137dcdc0d946a20ddea47e0f2fbe5ccf0db00201db95e1396925e927a0964
related: []
sources:
- src/sevn/self_improve/**
parent_prd: prd-12-self-improvement
depends_on: []
build_phase: null
interfaces:
- name: effective_self_improve_enabled
  file: src/sevn/self_improve/effective.py
  symbol: effective_self_improve_enabled
- name: ImproveJobResult
  file: src/sevn/self_improve/eval/__init__.py
  symbol: ImproveJobResult
- name: eval_docker_required
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_docker_required
- name: eval_in_process_override
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_in_process_override
- name: eval_report_passed
  file: src/sevn/self_improve/eval/__init__.py
  symbol: eval_report_passed
- name: golden_routing_fixture_path
  file: src/sevn/self_improve/eval/__init__.py
  symbol: golden_routing_fixture_path
- name: resolve_repo_root
  file: src/sevn/self_improve/eval/__init__.py
  symbol: resolve_repo_root
- name: run_docker_eval_graph
  file: src/sevn/self_improve/eval/__init__.py
  symbol: run_docker_eval_graph
- name: run_eval_graph
  file: src/sevn/self_improve/eval/__init__.py
  symbol: run_eval_graph
- name: LastKnownGoodRecord
  file: src/sevn/self_improve/eval/baseline.py
  symbol: LastKnownGoodRecord
- name: baseline_path_for_job_bundle
  file: src/sevn/self_improve/eval/baseline.py
  symbol: baseline_path_for_job_bundle
- name: baseline_section_for_report
  file: src/sevn/self_improve/eval/baseline.py
  symbol: baseline_section_for_report
- name: compute_metric_deltas
  file: src/sevn/self_improve/eval/baseline.py
  symbol: compute_metric_deltas
- name: load_last_known_good
  file: src/sevn/self_improve/eval/baseline.py
  symbol: load_last_known_good
- name: parse_token_budget_daily
  file: src/sevn/self_improve/eval/baseline.py
  symbol: parse_token_budget_daily
- name: save_last_known_good
  file: src/sevn/self_improve/eval/baseline.py
  symbol: save_last_known_good
- name: run_eval_in_docker
  file: src/sevn/self_improve/eval/docker.py
  symbol: run_eval_in_docker
- name: main
  file: src/sevn/self_improve/eval/launcher.py
  symbol: main
- name: EvalSegmentResult
  file: src/sevn/self_improve/eval/replay.py
  symbol: EvalSegmentResult
- name: GoldenRoutingMetrics
  file: src/sevn/self_improve/eval/replay.py
  symbol: GoldenRoutingMetrics
- name: GoldenRoutingReplayResult
  file: src/sevn/self_improve/eval/replay.py
  symbol: GoldenRoutingReplayResult
- name: LiveReplaySmokeResult
  file: src/sevn/self_improve/eval/replay.py
  symbol: LiveReplaySmokeResult
- name: golden_routing_fixture_path
  file: src/sevn/self_improve/eval/replay.py
  symbol: golden_routing_fixture_path
- name: run_golden_routing_replay
  file: src/sevn/self_improve/eval/replay.py
  symbol: run_golden_routing_replay
- name: run_live_replay_smoke
  file: src/sevn/self_improve/eval/replay.py
  symbol: run_live_replay_smoke
- name: strip_corpus_locale_prefix
  file: src/sevn/self_improve/eval/replay.py
  symbol: strip_corpus_locale_prefix
- name: improve_export_dir
  file: src/sevn/self_improve/export.py
  symbol: improve_export_dir
- name: prune_stale_export_bundles
  file: src/sevn/self_improve/export.py
  symbol: prune_stale_export_bundles
- name: scaffold_improve_export_bundle
  file: src/sevn/self_improve/export.py
  symbol: scaffold_improve_export_bundle
- name: abort_improve_job
  file: src/sevn/self_improve/facade.py
  symbol: abort_improve_job
- name: enqueue_improve_job
  file: src/sevn/self_improve/facade.py
  symbol: enqueue_improve_job
- name: ensure_preset_c_auto_merge_allowed
  file: src/sevn/self_improve/facade.py
  symbol: ensure_preset_c_auto_merge_allowed
- name: run_improve_job_eval
  file: src/sevn/self_improve/facade.py
  symbol: run_improve_job_eval
- name: insert_feedback_event
  file: src/sevn/self_improve/feedback/__init__.py
  symbol: insert_feedback_event
- name: mirror_structured_feedback_to_events
  file: src/sevn/self_improve/feedback/__init__.py
  symbol: mirror_structured_feedback_to_events
- name: forge_api_base
  file: src/sevn/self_improve/forge_providers.py
  symbol: forge_api_base
- name: ImproveJobEventFanoutFn
  file: src/sevn/self_improve/jobs/events.py
  symbol: ImproveJobEventFanoutFn
- name: ImproveJobEventPayload
  file: src/sevn/self_improve/jobs/events.py
  symbol: ImproveJobEventPayload
- name: improve_job_ws_topic
  file: src/sevn/self_improve/jobs/events.py
  symbol: improve_job_ws_topic
- name: maybe_publish_job_event
  file: src/sevn/self_improve/jobs/events.py
  symbol: maybe_publish_job_event
- name: ImproveJobRow
  file: src/sevn/self_improve/jobs/store.py
  symbol: ImproveJobRow
- name: abort_job_row
  file: src/sevn/self_improve/jobs/store.py
  symbol: abort_job_row
- name: claim_next_queued_job
  file: src/sevn/self_improve/jobs/store.py
  symbol: claim_next_queued_job
- name: enqueue_job_row
  file: src/sevn/self_improve/jobs/store.py
  symbol: enqueue_job_row
- name: fetch_job_row
  file: src/sevn/self_improve/jobs/store.py
  symbol: fetch_job_row
- name: list_recent_job_rows
  file: src/sevn/self_improve/jobs/store.py
  symbol: list_recent_job_rows
- name: requeue_after_plan_approval
  file: src/sevn/self_improve/jobs/store.py
  symbol: requeue_after_plan_approval
- name: update_job_state
  file: src/sevn/self_improve/jobs/store.py
  symbol: update_job_state
- name: EvalGraphRunner
  file: src/sevn/self_improve/jobs/worker.py
  symbol: EvalGraphRunner
- name: ImproveJobWorker
  file: src/sevn/self_improve/jobs/worker.py
  symbol: ImproveJobWorker
- name: Lesson
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: Lesson
- name: emit_recall_audit
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: emit_recall_audit
- name: recall_lessons
  file: src/sevn/self_improve/lessons/__init__.py
  symbol: recall_lessons
- name: append_jsonl_locked
  file: src/sevn/self_improve/lessons/io.py
  symbol: append_jsonl_locked
- name: record_openui_render_error
  file: src/sevn/self_improve/openui_telemetry.py
  symbol: record_openui_render_error
- name: snapshot_openui_buckets
  file: src/sevn/self_improve/openui_telemetry.py
  symbol: snapshot_openui_buckets
- name: improve_root
  file: src/sevn/self_improve/paths.py
  symbol: improve_root
- name: job_bundle_dir
  file: src/sevn/self_improve/paths.py
  symbol: job_bundle_dir
- name: self_improve_audit_path
  file: src/sevn/self_improve/paths.py
  symbol: self_improve_audit_path
- name: reject_patch_diff
  file: src/sevn/self_improve/proposer/__init__.py
  symbol: reject_patch_diff
- name: PatchProposal
  file: src/sevn/self_improve/proposer/agent.py
  symbol: PatchProposal
- name: run_patch_proposal_agent
  file: src/sevn/self_improve/proposer/agent.py
  symbol: run_patch_proposal_agent
- name: build_context_pack_payload
  file: src/sevn/self_improve/proposer/context_loader.py
  symbol: build_context_pack_payload
- name: load_context_pack
  file: src/sevn/self_improve/proposer/context_loader.py
  symbol: load_context_pack
- name: write_context_pack
  file: src/sevn/self_improve/proposer/context_loader.py
  symbol: write_context_pack
- name: PatchAuthorResult
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: PatchAuthorResult
- name: author_patch_from_shortlist
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: author_patch_from_shortlist
- name: paths_in_unified_diff
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: paths_in_unified_diff
- name: preset_requires_proposer
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: preset_requires_proposer
- name: proposer_budget_exhausted
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: proposer_budget_exhausted
- name: reject_patch_glob_scope
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: reject_patch_glob_scope
- name: reject_patch_policy
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: reject_patch_policy
- name: resolve_patch_author_mode
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: resolve_patch_author_mode
- name: write_patch_artefacts
  file: src/sevn/self_improve/proposer/patch_author.py
  symbol: write_patch_artefacts
- name: stub_author_patch_from_shortlist
  file: src/sevn/self_improve/proposer/patch_author_stub.py
  symbol: stub_author_patch_from_shortlist
- name: build_patch_author_prompt
  file: src/sevn/self_improve/proposer/prompt.py
  symbol: build_patch_author_prompt
- name: prune_stale_job_bundles
  file: src/sevn/self_improve/retention.py
  symbol: prune_stale_job_bundles
- name: ShortlistCandidate
  file: src/sevn/self_improve/sampler/__init__.py
  symbol: ShortlistCandidate
- name: allocate_shortlist
  file: src/sevn/self_improve/sampler/__init__.py
  symbol: allocate_shortlist
- name: load_sampler_candidates
  file: src/sevn/self_improve/sampler/sources.py
  symbol: load_sampler_candidates
- name: improve_spec_kit_dir
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: improve_spec_kit_dir
- name: mark_plan_approved
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: mark_plan_approved
- name: plan_hitl_blocks_patch
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: plan_hitl_blocks_patch
- name: run_improve_spec_kit_plan
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: run_improve_spec_kit_plan
- name: spec_kit_plan_stage_enabled
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: spec_kit_plan_stage_enabled
- name: write_context_pack
  file: src/sevn/self_improve/spec_kit_stage.py
  symbol: write_context_pack
- name: emit_self_improve_trace
  file: src/sevn/self_improve/trace_events.py
  symbol: emit_self_improve_trace
- name: TrajectoryTurn
  file: src/sevn/self_improve/trajectories/__init__.py
  symbol: TrajectoryTurn
- name: stable_turn_id
  file: src/sevn/self_improve/trajectories/__init__.py
  symbol: stable_turn_id
- name: TrajectoryIngestResult
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: TrajectoryIngestResult
- name: ingest_trajectory_fact_for_turn
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: ingest_trajectory_fact_for_turn
- name: ingest_trajectory_facts_from_traces
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: ingest_trajectory_facts_from_traces
- name: trajectory_reconciliation_rate
  file: src/sevn/self_improve/trajectories/ingest.py
  symbol: trajectory_reconciliation_rate
- name: schedule_trajectory_ingest
  file: src/sevn/self_improve/trajectories/queue.py
  symbol: schedule_trajectory_ingest
- name: run_trajectory_ingest
  file: src/sevn/self_improve/trajectories/runner.py
  symbol: run_trajectory_ingest
- name: effective_trajectories
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: effective_trajectories
- name: read_last_trajectory_ingest_ts_ns
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: read_last_trajectory_ingest_ts_ns
- name: reconcile_trajectory_ingest_cron_job
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: reconcile_trajectory_ingest_cron_job
- name: run_scheduled_trajectory_ingest
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: run_scheduled_trajectory_ingest
- name: write_last_trajectory_ingest_ts_ns
  file: src/sevn/self_improve/trajectories/scheduler.py
  symbol: write_last_trajectory_ingest_ts_ns
- name: OwnerPrincipal
  file: src/sevn/self_improve/types.py
  symbol: OwnerPrincipal
specs: []
personas: []
---

## Purpose

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Purpose.

## Public Interface

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Public Interface.

## Data Model

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Data Model.

## Internal Architecture

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Internal Architecture.

## Behavior

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Behavior.

## Failure Modes

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Failure Modes.

## Test Strategy

Offline scaffold for Self-improvement — Spec (spec-33-self-improvement) — Test Strategy.
