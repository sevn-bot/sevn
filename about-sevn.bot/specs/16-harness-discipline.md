---
id: spec-16-harness-discipline
kind: spec
title: Harness discipline — Spec
status: scaffold
owner: Alex
summary: 'Harness discipline: background task logging, operator PATH augmentation,
  and gateway/agent harness hooks under agent/harness/.'
last_updated: '2026-07-14'
fingerprint: sha256:3d1bd9050c4ccabc3c76b79dd616114e44c5ef0033271a6d372eb9a5b0741101
related: []
sources:
- src/sevn/agent/harness/**
- src/sevn/runtime/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-02-config-and-workspace
- spec-13-rlm-triager
- spec-14-executor-tier-b
build_phase: null
interfaces:
- name: ActiveRunSnapshotWrite
  file: src/sevn/agent/harness/snapshots.py
  symbol: ActiveRunSnapshotWrite
- name: BootResumeRunRef
  file: src/sevn/agent/harness/snapshots.py
  symbol: BootResumeRunRef
- name: HarnessBootSweepResult
  file: src/sevn/agent/harness/snapshots.py
  symbol: HarnessBootSweepResult
- name: HarnessSnapshotSanitisationError
  file: src/sevn/agent/harness/snapshots.py
  symbol: HarnessSnapshotSanitisationError
- name: ReplayTurnNotFoundError
  file: src/sevn/agent/harness/snapshots.py
  symbol: ReplayTurnNotFoundError
- name: ReplayTurnNotReplayableError
  file: src/sevn/agent/harness/snapshots.py
  symbol: ReplayTurnNotReplayableError
- name: delete_active_run_snapshot
  file: src/sevn/agent/harness/snapshots.py
  symbol: delete_active_run_snapshot
- name: format_upgrade_paused_notification
  file: src/sevn/agent/harness/snapshots.py
  symbol: format_upgrade_paused_notification
- name: get_or_create_turn_replay_job_id
  file: src/sevn/agent/harness/snapshots.py
  symbol: get_or_create_turn_replay_job_id
- name: pause_active_snapshots_for_upgrade
  file: src/sevn/agent/harness/snapshots.py
  symbol: pause_active_snapshots_for_upgrade
- name: pending_resume_group_count
  file: src/sevn/agent/harness/snapshots.py
  symbol: pending_resume_group_count
- name: persist_run_snapshot
  file: src/sevn/agent/harness/snapshots.py
  symbol: persist_run_snapshot
- name: queue_dashboard_turn_replay
  file: src/sevn/agent/harness/snapshots.py
  symbol: queue_dashboard_turn_replay
- name: redacted_inspect_summary
  file: src/sevn/agent/harness/snapshots.py
  symbol: redacted_inspect_summary
- name: replay_requests_in_window
  file: src/sevn/agent/harness/snapshots.py
  symbol: replay_requests_in_window
- name: sanitize_in_flight_tools
  file: src/sevn/agent/harness/snapshots.py
  symbol: sanitize_in_flight_tools
- name: sanitize_plan_state
  file: src/sevn/agent/harness/snapshots.py
  symbol: sanitize_plan_state
- name: session_has_active_run_for_replay
  file: src/sevn/agent/harness/snapshots.py
  symbol: session_has_active_run_for_replay
- name: sweep_active_run_snapshots
  file: src/sevn/agent/harness/snapshots.py
  symbol: sweep_active_run_snapshots
- name: turn_has_replay_trace
  file: src/sevn/agent/harness/snapshots.py
  symbol: turn_has_replay_trace
- name: ZombieTask
  file: src/sevn/agent/harness/zombie.py
  symbol: ZombieTask
- name: ZombieWatchQueue
  file: src/sevn/agent/harness/zombie.py
  symbol: ZombieWatchQueue
- name: spawn_logged
  file: src/sevn/runtime/background_tasks.py
  symbol: spawn_logged
- name: augment_macos_dyld_library_path
  file: src/sevn/runtime/operator_path.py
  symbol: augment_macos_dyld_library_path
- name: augment_operator_path
  file: src/sevn/runtime/operator_path.py
  symbol: augment_operator_path
- name: operator_path_prefixes
  file: src/sevn/runtime/operator_path.py
  symbol: operator_path_prefixes
---

## Purpose

Harness discipline: background task logging, operator PATH augmentation, and gateway/agent harness hooks under [`agent/harness/`](src/sevn/agent/harness/__init__.py).

Primary code trees: [`src/sevn/agent/harness`](src/sevn/agent/harness/__init__.py), [`src/sevn/runtime/background_tasks.py`](src/sevn/runtime/background_tasks.py).

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->

## Implemented by

- [`spawn_logged`](src/sevn/runtime/background_tasks.py) — `src/sevn/runtime/background_tasks.py`
- [`augment_macos_dyld_library_path`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
- [`augment_operator_path`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
- [`operator_path_prefixes`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`

## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`spawn_logged`](src/sevn/runtime/background_tasks.py) — `src/sevn/runtime/background_tasks.py`
- [`augment_macos_dyld_library_path`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
- [`augment_operator_path`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
- [`operator_path_prefixes`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`spawn_logged`](src/sevn/runtime/background_tasks.py) — `src/sevn/runtime/background_tasks.py`
- [`augment_macos_dyld_library_path`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
- [`augment_operator_path`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
- [`operator_path_prefixes`](src/sevn/runtime/operator_path.py) — `src/sevn/runtime/operator_path.py`
## Internal Architecture

See **Implemented by** and [`src/sevn/agent/harness`](src/sevn/agent/harness/__init__.py), [`src/sevn/runtime/background_tasks.py`](src/sevn/runtime/background_tasks.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/agent/harness`](src/sevn/agent/harness/__init__.py) and [`src/sevn/runtime/background_tasks.py`](src/sevn/runtime/background_tasks.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
