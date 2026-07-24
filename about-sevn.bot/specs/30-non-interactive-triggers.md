---
id: spec-30-non-interactive-triggers
kind: spec
title: Non-interactive triggers — Spec
status: scaffold
owner: Alex
summary: 'Deliver non-interactive dispatch: external events (“something happened”)
  and schedules (“tick”) compile to DispatchRequest, optionally pass through notify_only
  (zero LLM, zero sandbox boot), otherwise'
last_updated: '2026-07-21'
fingerprint: sha256:cba9dff781c745b124968af4cd49ca19317fbd0d15090408648dccc08517e6b6
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
- name: register_cron_job_handler
  file: src/sevn/triggers/cron.py
  symbol: register_cron_job_handler
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
- name: ensure_issue_watch_cron_job
  file: src/sevn/triggers/issue_watch_cron.py
  symbol: ensure_issue_watch_cron_job
- name: notify_issue_watch_diff
  file: src/sevn/triggers/issue_watch_cron.py
  symbol: notify_issue_watch_diff
- name: register_issue_watch_cron_handler
  file: src/sevn/triggers/issue_watch_cron.py
  symbol: register_issue_watch_cron_handler
- name: run_issue_watch_cron
  file: src/sevn/triggers/issue_watch_cron.py
  symbol: run_issue_watch_cron
- name: deliver_operator_notify
  file: src/sevn/triggers/operator_notify.py
  symbol: deliver_operator_notify
- name: reset_operator_notify_for_tests
  file: src/sevn/triggers/operator_notify.py
  symbol: reset_operator_notify_for_tests
- name: set_operator_notify
  file: src/sevn/triggers/operator_notify.py
  symbol: set_operator_notify
- name: unwire_operator_notify
  file: src/sevn/triggers/operator_notify.py
  symbol: unwire_operator_notify
- name: wire_operator_notify
  file: src/sevn/triggers/operator_notify.py
  symbol: wire_operator_notify
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
---

## Purpose

Deliver non-interactive dispatch: external events (“something happened”) and schedules (“tick”) compile to DispatchRequest, optionally pass through notify_only (zero LLM, zero sandbox boot), otherwise

Primary code trees: [`src/sevn/triggers`](src/sevn/triggers/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`RunCreateBody`](src/sevn/triggers/api_router.py) — `src/sevn/triggers/api_router.py`
- [`build_api_router`](src/sevn/triggers/api_router.py) — `src/sevn/triggers/api_router.py`
- [`triggers_api_auth_required`](src/sevn/triggers/auth.py) — `src/sevn/triggers/auth.py`
- [`verify_triggers_api_bearer`](src/sevn/triggers/auth.py) — `src/sevn/triggers/auth.py`
- [`coding_agent_loop_trigger`](src/sevn/triggers/coding_agent_loop.py) — `src/sevn/triggers/coding_agent_loop.py`
- [`mine_session_trajectories`](src/sevn/triggers/coding_agent_loop.py) — `src/sevn/triggers/coding_agent_loop.py`
- [`CronJobDetail`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`CronJobRow`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`SqliteCronStore`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`add_cron_job`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`add_reminder`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`compute_next_fire_ns`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- _…and 33 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`RunCreateBody`](src/sevn/triggers/api_router.py) — `src/sevn/triggers/api_router.py`
- [`build_api_router`](src/sevn/triggers/api_router.py) — `src/sevn/triggers/api_router.py`
- [`triggers_api_auth_required`](src/sevn/triggers/auth.py) — `src/sevn/triggers/auth.py`
- [`verify_triggers_api_bearer`](src/sevn/triggers/auth.py) — `src/sevn/triggers/auth.py`
- [`coding_agent_loop_trigger`](src/sevn/triggers/coding_agent_loop.py) — `src/sevn/triggers/coding_agent_loop.py`
- [`mine_session_trajectories`](src/sevn/triggers/coding_agent_loop.py) — `src/sevn/triggers/coding_agent_loop.py`
- [`CronJobDetail`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`CronJobRow`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`SqliteCronStore`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`add_cron_job`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`add_reminder`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- [`compute_next_fire_ns`](src/sevn/triggers/cron.py) — `src/sevn/triggers/cron.py`
- _…and 33 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/triggers`](src/sevn/triggers/__init__.py).
## Behavior

Built-in **GitHub issue-watch** cron (`gh-issue-watch`, ~15 min) is registered at boot via
`register_issue_watch_cron_handler` → `_CRON_JOB_HANDLERS`. `cron_tick` dispatches that handler
(off the event loop) rather than falling through to LLM dispatch. Diffs notify via
`notify_issue_watch_diff` → `deliver_operator_notify` (Telegram owner sink when wired at gateway
boot; LOG artefact otherwise).

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/triggers`](src/sevn/triggers/__init__.py).

## Failure Modes

| Condition | Handling |
|-----------|----------|
| Issue-watch handler exception | `cron_handler_failed` log; schedule bumped with `error` status |
| Operator notify unwired / no owner | Persist LOG under `.sevn/trigger_runs/` (never fake success) |
| Per-issue `gh` failure | Logged; watch continues remaining tracked issues |

## Test Strategy

| Tests | Focus |
|-------|-------|
| `tests/skills/gh_issues/test_issue_watch.py` | Track/watch diffs + cron handler registration |
| `tests/gateway/test_lifecycle_w1_red.py` | `cron_tick` → `_CRON_JOB_HANDLERS` + operator-notify → `route_outgoing` |
Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
