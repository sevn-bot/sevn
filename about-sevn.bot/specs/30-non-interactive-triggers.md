---
id: spec-30-non-interactive-triggers
kind: spec
title: Non-interactive triggers — Spec
status: done
owner: Alex
summary: 'Deliver non-interactive dispatch: external events (“something happened”)
  and schedules (“tick”) compile to DispatchRequest, optionally pass through notify_only
  (zero LLM, zero sandbox boot), otherwise'
last_updated: '2026-06-19'
fingerprint: sha256:3ba449957038898a3f00cba876819d2398f3dfd4e02ca942fbeb846280cdcd61
related: []
sources:
- src/sevn/triggers/**
parent_prd: prd-11-automation-and-triggers
depends_on:
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-03-storage
- spec-04-tracing
- spec-05-llm-transports
- spec-06-secrets
- spec-07-egress-proxy
- spec-08-sandbox
- spec-09-security-scanner
- spec-10-schema-ontology
- spec-11-tools-registry
- spec-12-skills-system
- spec-13-rlm-triager
- spec-14-executor-tier-b
- spec-15-memory-lcm
- spec-16-harness-discipline
- spec-17-gateway
- spec-18-channel-telegram
- spec-19-channel-webui
- spec-21-executor-tier-cd
- spec-22-onboarding
- spec-23-cli
- spec-24-dashboard
- spec-34-plugin-hooks
build_phase: null
interfaces:
- name: RunCreateBody
  file: src/sevn/triggers/api_router.py
  symbol: RunCreateBody
- name: build_api_router
  file: src/sevn/triggers/api_router.py
  symbol: build_api_router
- name: triggers_api_auth_required
  file: src/sevn/triggers/auth.py
  symbol: triggers_api_auth_required
- name: verify_triggers_api_bearer
  file: src/sevn/triggers/auth.py
  symbol: verify_triggers_api_bearer
- name: coding_agent_loop_trigger
  file: src/sevn/triggers/coding_agent_loop.py
  symbol: coding_agent_loop_trigger
- name: mine_session_trajectories
  file: src/sevn/triggers/coding_agent_loop.py
  symbol: mine_session_trajectories
- name: CronJobDetail
  file: src/sevn/triggers/cron.py
  symbol: CronJobDetail
- name: CronJobRow
  file: src/sevn/triggers/cron.py
  symbol: CronJobRow
- name: SqliteCronStore
  file: src/sevn/triggers/cron.py
  symbol: SqliteCronStore
- name: add_cron_job
  file: src/sevn/triggers/cron.py
  symbol: add_cron_job
- name: add_reminder
  file: src/sevn/triggers/cron.py
  symbol: add_reminder
- name: compute_next_fire_ns
  file: src/sevn/triggers/cron.py
  symbol: compute_next_fire_ns
- name: cron_job_to_dict
  file: src/sevn/triggers/cron.py
  symbol: cron_job_to_dict
- name: cron_job_to_list_dict
  file: src/sevn/triggers/cron.py
  symbol: cron_job_to_list_dict
- name: cron_tick
  file: src/sevn/triggers/cron.py
  symbol: cron_tick
- name: delete_cron_job
  file: src/sevn/triggers/cron.py
  symbol: delete_cron_job
- name: edit_cron_job
  file: src/sevn/triggers/cron.py
  symbol: edit_cron_job
- name: format_next_fire_at_iso
  file: src/sevn/triggers/cron.py
  symbol: format_next_fire_at_iso
- name: list_cron_jobs
  file: src/sevn/triggers/cron.py
  symbol: list_cron_jobs
- name: prune_webhook_dedupe_expired
  file: src/sevn/triggers/dedupe.py
  symbol: prune_webhook_dedupe_expired
- name: try_insert_webhook_dedupe
  file: src/sevn/triggers/dedupe.py
  symbol: try_insert_webhook_dedupe
- name: trigger_runs_dir
  file: src/sevn/triggers/delivery.py
  symbol: trigger_runs_dir
- name: write_log_result
  file: src/sevn/triggers/delivery.py
  symbol: write_log_result
- name: TriggerDispatchGate
  file: src/sevn/triggers/dispatcher.py
  symbol: TriggerDispatchGate
- name: agent_dispatch_kwargs
  file: src/sevn/triggers/dispatcher.py
  symbol: agent_dispatch_kwargs
- name: dispatch_notify_only
  file: src/sevn/triggers/dispatcher.py
  symbol: dispatch_notify_only
- name: dispatch_run
  file: src/sevn/triggers/dispatcher.py
  symbol: dispatch_run
- name: TriggerPluginHookSurface
  file: src/sevn/triggers/hooks_protocol.py
  symbol: TriggerPluginHookSurface
- name: inbox_dir
  file: src/sevn/triggers/inbox.py
  symbol: inbox_dir
- name: maybe_spill_prompt_to_inbox
  file: src/sevn/triggers/inbox.py
  symbol: maybe_spill_prompt_to_inbox
- name: prune_inbox_spill
  file: src/sevn/triggers/inbox.py
  symbol: prune_inbox_spill
- name: DispatchRequest
  file: src/sevn/triggers/request.py
  symbol: DispatchRequest
- name: NotifyHandle
  file: src/sevn/triggers/request.py
  symbol: NotifyHandle
- name: ResultChannel
  file: src/sevn/triggers/request.py
  symbol: ResultChannel
- name: RunHandle
  file: src/sevn/triggers/request.py
  symbol: RunHandle
- name: effective_max_concurrent
  file: src/sevn/triggers/settings.py
  symbol: effective_max_concurrent
- name: effective_max_inline_bytes
  file: src/sevn/triggers/settings.py
  symbol: effective_max_inline_bytes
- name: GitHubPayload
  file: src/sevn/triggers/sources/github.py
  symbol: GitHubPayload
- name: compose_github_prompt
  file: src/sevn/triggers/sources/github.py
  symbol: compose_github_prompt
- name: compose_prompt
  file: src/sevn/triggers/sources/github.py
  symbol: compose_prompt
- name: verify_github_payload
  file: src/sevn/triggers/sources/github.py
  symbol: verify_github_payload
- name: build_webhook_router
  file: src/sevn/triggers/webhook_router.py
  symbol: build_webhook_router
- name: maybe_import_github_issue_event
  file: src/sevn/triggers/webhook_router.py
  symbol: maybe_import_github_issue_event
- name: resolve_webhook_signing_secret
  file: src/sevn/triggers/webhook_secret.py
  symbol: resolve_webhook_signing_secret
- name: trigger_run_ws_topic
  file: src/sevn/triggers/ws_topics.py
  symbol: trigger_run_ws_topic
specs: []
personas: []
---

## Purpose

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Purpose.

## Public Interface

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Public Interface.

## Data Model

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Data Model.

## Internal Architecture

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Internal Architecture.

## Behavior

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Behavior.

## Failure Modes

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Failure Modes.

## Test Strategy

Offline scaffold for Non-interactive triggers — Spec (spec-30-non-interactive-triggers) — Test Strategy.
