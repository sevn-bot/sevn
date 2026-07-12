---
id: spec-35-bot-evolution
kind: spec
title: Bot evolution — Spec
status: draft
owner: Alex
summary: Deliver src/sevn/evolution/ and the operator-facing Evolution surface so
  sevn.bot can evolve its own codebase as a first-class product pillar — not an optional
  add-on — spanning understand → file work
last_updated: '2026-07-12'
fingerprint: sha256:9b3c337dbc7b272dfeeed4530df44d6f79fb344bec56c314fff513a5a80b8bd5
related: []
sources:
- src/sevn/evolution/**
parent_prd: prd-07-mission-control
depends_on:
- spec-28-code-understanding
- spec-33-self-improvement
- spec-24-dashboard
- spec-22-onboarding
- spec-21-executor-tier-cd
- spec-02-config-and-workspace
build_phase: null
interfaces:
- name: EvolutionApproval
  file: src/sevn/evolution/approvals.py
  symbol: EvolutionApproval
- name: approval_to_api_dict
  file: src/sevn/evolution/approvals.py
  symbol: approval_to_api_dict
- name: approvals_dir
  file: src/sevn/evolution/approvals.py
  symbol: approvals_dir
- name: create_approval
  file: src/sevn/evolution/approvals.py
  symbol: create_approval
- name: ensure_issue_approval
  file: src/sevn/evolution/approvals.py
  symbol: ensure_issue_approval
- name: get_approval
  file: src/sevn/evolution/approvals.py
  symbol: get_approval
- name: list_approvals
  file: src/sevn/evolution/approvals.py
  symbol: list_approvals
- name: resolve_approval
  file: src/sevn/evolution/approvals.py
  symbol: resolve_approval
- name: save_approval
  file: src/sevn/evolution/approvals.py
  symbol: save_approval
- name: run_bug_pipeline
  file: src/sevn/evolution/bug_pipeline.py
  symbol: run_bug_pipeline
- name: CursorPollScheduler
  file: src/sevn/evolution/cursor_poll_scheduler.py
  symbol: CursorPollScheduler
- name: EvolutionIssueEventFanoutFn
  file: src/sevn/evolution/events.py
  symbol: EvolutionIssueEventFanoutFn
- name: EvolutionIssueEventPayload
  file: src/sevn/evolution/events.py
  symbol: EvolutionIssueEventPayload
- name: evolution_issue_ws_topic
  file: src/sevn/evolution/events.py
  symbol: evolution_issue_ws_topic
- name: maybe_publish_issue_event
  file: src/sevn/evolution/events.py
  symbol: maybe_publish_issue_event
- name: dispatch_local_implement
  file: src/sevn/evolution/executors/local.py
  symbol: dispatch_local_implement
- name: FeaturePipelineBlockedError
  file: src/sevn/evolution/feature_pipeline.py
  symbol: FeaturePipelineBlockedError
- name: feature_artefacts_dir
  file: src/sevn/evolution/feature_pipeline.py
  symbol: feature_artefacts_dir
- name: record_pipeline_approval
  file: src/sevn/evolution/feature_pipeline.py
  symbol: record_pipeline_approval
- name: run_feature_pipeline
  file: src/sevn/evolution/feature_pipeline.py
  symbol: run_feature_pipeline
- name: SyncResult
  file: src/sevn/evolution/github_sync.py
  symbol: SyncResult
- name: import_github_issue
  file: src/sevn/evolution/github_sync.py
  symbol: import_github_issue
- name: import_github_issue_with_created
  file: src/sevn/evolution/github_sync.py
  symbol: import_github_issue_with_created
- name: sync_github_issues
  file: src/sevn/evolution/github_sync.py
  symbol: sync_github_issues
- name: EvolutionIssue
  file: src/sevn/evolution/issues.py
  symbol: EvolutionIssue
- name: create_issue
  file: src/sevn/evolution/issues.py
  symbol: create_issue
- name: get_issue
  file: src/sevn/evolution/issues.py
  symbol: get_issue
- name: issue_to_api_dict
  file: src/sevn/evolution/issues.py
  symbol: issue_to_api_dict
- name: issues_dir
  file: src/sevn/evolution/issues.py
  symbol: issues_dir
- name: list_issues
  file: src/sevn/evolution/issues.py
  symbol: list_issues
- name: maybe_mirror_issue_to_github
  file: src/sevn/evolution/issues.py
  symbol: maybe_mirror_issue_to_github
- name: my_sevn_repo_slug
  file: src/sevn/evolution/issues.py
  symbol: my_sevn_repo_slug
- name: save_issue
  file: src/sevn/evolution/issues.py
  symbol: save_issue
- name: utc_now_iso
  file: src/sevn/evolution/issues.py
  symbol: utc_now_iso
- name: maybe_auto_run_pipeline_after_import
  file: src/sevn/evolution/pipeline_autostart.py
  symbol: maybe_auto_run_pipeline_after_import
- name: PipelineBlockedError
  file: src/sevn/evolution/pipeline_common.py
  symbol: PipelineBlockedError
- name: publish_transition
  file: src/sevn/evolution/pipeline_common.py
  symbol: publish_transition
- name: set_issue_stage
  file: src/sevn/evolution/pipeline_common.py
  symbol: set_issue_stage
- name: run_pipeline
  file: src/sevn/evolution/pipeline_runner.py
  symbol: run_pipeline
- name: PipelineStageRow
  file: src/sevn/evolution/pipelines.py
  symbol: PipelineStageRow
- name: append_pipeline_log
  file: src/sevn/evolution/pipelines.py
  symbol: append_pipeline_log
- name: get_pipeline_detail
  file: src/sevn/evolution/pipelines.py
  symbol: get_pipeline_detail
- name: issue_to_pipeline_dict
  file: src/sevn/evolution/pipelines.py
  symbol: issue_to_pipeline_dict
- name: kill_pipeline
  file: src/sevn/evolution/pipelines.py
  symbol: kill_pipeline
- name: list_active_pipelines
  file: src/sevn/evolution/pipelines.py
  symbol: list_active_pipelines
- name: pipeline_logs_path
  file: src/sevn/evolution/pipelines.py
  symbol: pipeline_logs_path
- name: PromotionError
  file: src/sevn/evolution/promotion.py
  symbol: PromotionError
- name: promote_issue
  file: src/sevn/evolution/promotion.py
  symbol: promote_issue
- name: reconcile_my_sevn_issues_sync_cron_job
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: reconcile_my_sevn_issues_sync_cron_job
- name: reconcile_my_sevn_sync_cron_job
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: reconcile_my_sevn_sync_cron_job
- name: run_scheduled_issues_sync
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: run_scheduled_issues_sync
- name: run_scheduled_repo_sync
  file: src/sevn/evolution/repo_sync_scheduler.py
  symbol: run_scheduled_repo_sync
- name: ExecutorBlockedError
  file: src/sevn/evolution/router.py
  symbol: ExecutorBlockedError
- name: build_cursor_cloud_prompt
  file: src/sevn/evolution/router.py
  symbol: build_cursor_cloud_prompt
- name: dispatch_cursor_cloud_implement
  file: src/sevn/evolution/router.py
  symbol: dispatch_cursor_cloud_implement
- name: launch_cursor_cloud_for_issue
  file: src/sevn/evolution/router.py
  symbol: launch_cursor_cloud_for_issue
- name: poll_cursor_cloud_for_issue
  file: src/sevn/evolution/router.py
  symbol: poll_cursor_cloud_for_issue
- name: resolve_executor
  file: src/sevn/evolution/router.py
  symbol: resolve_executor
- name: resolve_target_repo_url
  file: src/sevn/evolution/router.py
  symbol: resolve_target_repo_url
- name: ConstitutionPayload
  file: src/sevn/evolution/spec_kit.py
  symbol: ConstitutionPayload
- name: SpecKitRunResult
  file: src/sevn/evolution/spec_kit.py
  symbol: SpecKitRunResult
- name: constitution_template_text
  file: src/sevn/evolution/spec_kit.py
  symbol: constitution_template_text
- name: load_constitution
  file: src/sevn/evolution/spec_kit.py
  symbol: load_constitution
- name: load_spec_kit_options
  file: src/sevn/evolution/spec_kit.py
  symbol: load_spec_kit_options
- name: run_specify_allowlisted
  file: src/sevn/evolution/spec_kit.py
  symbol: run_specify_allowlisted
- name: save_constitution
  file: src/sevn/evolution/spec_kit.py
  symbol: save_constitution
- name: save_spec_kit_options
  file: src/sevn/evolution/spec_kit.py
  symbol: save_spec_kit_options
- name: SpecKitRunRecord
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: SpecKitRunRecord
- name: append_spec_kit_run
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: append_spec_kit_run
- name: list_spec_kit_runs
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: list_spec_kit_runs
- name: new_run_id
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: new_run_id
- name: utc_now_iso
  file: src/sevn/evolution/spec_kit_runs.py
  symbol: utc_now_iso
- name: compute_evolution_stats
  file: src/sevn/evolution/stats.py
  symbol: compute_evolution_stats
- name: last_sync_path
  file: src/sevn/evolution/stats.py
  symbol: last_sync_path
- name: load_last_sync_record
  file: src/sevn/evolution/stats.py
  symbol: load_last_sync_record
- name: record_last_sync
  file: src/sevn/evolution/stats.py
  symbol: record_last_sync
- name: CiSmokeResult
  file: src/sevn/evolution/worktree.py
  symbol: CiSmokeResult
- name: WorktreeError
  file: src/sevn/evolution/worktree.py
  symbol: WorktreeError
- name: WorktreeLease
  file: src/sevn/evolution/worktree.py
  symbol: WorktreeLease
- name: allocate_worktree
  file: src/sevn/evolution/worktree.py
  symbol: allocate_worktree
- name: code_worktrees_dir
  file: src/sevn/evolution/worktree.py
  symbol: code_worktrees_dir
- name: load_worktree_lease
  file: src/sevn/evolution/worktree.py
  symbol: load_worktree_lease
- name: promote_worktree
  file: src/sevn/evolution/worktree.py
  symbol: promote_worktree
- name: release_worktree
  file: src/sevn/evolution/worktree.py
  symbol: release_worktree
- name: run_ci_smoke
  file: src/sevn/evolution/worktree.py
  symbol: run_ci_smoke
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Purpose.

## Public Interface

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Public Interface.

## Data Model

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Data Model.

## Internal Architecture

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Internal Architecture.

## Behavior

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Behavior.

## Failure Modes

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Failure Modes.

## Test Strategy

Offline scaffold for Bot evolution — Spec (spec-35-bot-evolution) — Test Strategy.
