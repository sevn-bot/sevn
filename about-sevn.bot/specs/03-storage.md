---
id: spec-03-storage
kind: spec
title: Storage — Spec
status: scaffold
owner: Alex
summary: 'Own application persistence: connection setup (WAL, foreign keys), versioned
  migrations, canonical sevn.db path, optional traces.db path helper, and typed persistence
  contracts for crash-resume and (w'
last_updated: '2026-08-03'
fingerprint: sha256:e4c1e19e5779562faf21cb0b1fa3a1d6bc9f98faee19cff2b759bc0923e21842
related: []
sources:
- src/sevn/storage/**
parent_prd: prd-02-personality-and-memory
depends_on:
- spec-00-foundation
- spec-01-system-overview
- spec-02-config-and-workspace
build_phase: null
interfaces:
- name: backup_sevn_db
  file: src/sevn/storage/backup.py
  symbol: backup_sevn_db
- name: restore_sevn_db
  file: src/sevn/storage/backup.py
  symbol: restore_sevn_db
- name: D1Backend
  file: src/sevn/storage/d1.py
  symbol: D1Backend
- name: D1BackendConfig
  file: src/sevn/storage/d1_backend.py
  symbol: D1BackendConfig
- name: D1StorageBackend
  file: src/sevn/storage/d1_backend.py
  symbol: D1StorageBackend
- name: adapter_message_id_from_chunks
  file: src/sevn/storage/delivery.py
  symbol: adapter_message_id_from_chunks
- name: confirm_delivery_after_send
  file: src/sevn/storage/delivery.py
  symbol: confirm_delivery_after_send
- name: confirm_delivery_obligation
  file: src/sevn/storage/delivery.py
  symbol: confirm_delivery_obligation
- name: count_open_obligations
  file: src/sevn/storage/delivery.py
  symbol: count_open_obligations
- name: create_delivery_obligation
  file: src/sevn/storage/delivery.py
  symbol: create_delivery_obligation
- name: fail_delivery_obligation
  file: src/sevn/storage/delivery.py
  symbol: fail_delivery_obligation
- name: get_delivery_obligation
  file: src/sevn/storage/delivery.py
  symbol: get_delivery_obligation
- name: hash_delivery_payload
  file: src/sevn/storage/delivery.py
  symbol: hash_delivery_payload
- name: is_delivery_confirmed
  file: src/sevn/storage/delivery.py
  symbol: is_delivery_confirmed
- name: reconcile_confirmed_obligation
  file: src/sevn/storage/delivery.py
  symbol: reconcile_confirmed_obligation
- name: MigrationError
  file: src/sevn/storage/errors.py
  symbol: MigrationError
- name: StorageError
  file: src/sevn/storage/errors.py
  symbol: StorageError
- name: apply_migrations
  file: src/sevn/storage/migrate.py
  symbol: apply_migrations
- name: is_turn_bundle_day_slug
  file: src/sevn/storage/paths.py
  symbol: is_turn_bundle_day_slug
- name: sevn_db_path
  file: src/sevn/storage/paths.py
  symbol: sevn_db_path
- name: traces_sqlite_path
  file: src/sevn/storage/paths.py
  symbol: traces_sqlite_path
- name: turn_bundle_day_dir
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_day_dir
- name: turn_bundle_day_slug
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_day_slug
- name: turn_bundle_file_path
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_file_path
- name: turn_bundle_index_path
  file: src/sevn/storage/paths.py
  symbol: turn_bundle_index_path
- name: turn_bundles_dir
  file: src/sevn/storage/paths.py
  symbol: turn_bundles_dir
- name: connect_sqlite
  file: src/sevn/storage/sqlite.py
  symbol: connect_sqlite
- name: open_sevn_sqlite
  file: src/sevn/storage/sqlite.py
  symbol: open_sevn_sqlite
- name: run_sqlite_write
  file: src/sevn/storage/sqlite_write_lock.py
  symbol: run_sqlite_write
- name: sqlite_write_lock
  file: src/sevn/storage/sqlite_write_lock.py
  symbol: sqlite_write_lock
- name: get_telegram_chat_name
  file: src/sevn/storage/telegram_names.py
  symbol: get_telegram_chat_name
- name: get_telegram_topic_name
  file: src/sevn/storage/telegram_names.py
  symbol: get_telegram_topic_name
- name: get_trigger_run_status
  file: src/sevn/storage/trigger_runs.py
  symbol: get_trigger_run_status
- name: upsert_trigger_run_status
  file: src/sevn/storage/trigger_runs.py
  symbol: upsert_trigger_run_status
---

## Purpose

Own application persistence: connection setup (WAL, foreign keys), versioned migrations, canonical sevn.db path, optional traces.db path helper, and typed persistence contracts for crash-resume and (w

Primary code trees: [`src/sevn/storage`](src/sevn/storage/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`D1Backend`](src/sevn/storage/d1.py) — `src/sevn/storage/d1.py`
- [`D1BackendConfig`](src/sevn/storage/d1_backend.py) — `src/sevn/storage/d1_backend.py`
- [`D1StorageBackend`](src/sevn/storage/d1_backend.py) — `src/sevn/storage/d1_backend.py`
- [`MigrationError`](src/sevn/storage/errors.py) — `src/sevn/storage/errors.py`
- [`StorageError`](src/sevn/storage/errors.py) — `src/sevn/storage/errors.py`
- [`apply_migrations`](src/sevn/storage/migrate.py) — `src/sevn/storage/migrate.py`
- [`is_turn_bundle_day_slug`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`sevn_db_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`traces_sqlite_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_day_dir`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_day_slug`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_file_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- _…and 4 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`D1Backend`](src/sevn/storage/d1.py) — `src/sevn/storage/d1.py`
- [`D1BackendConfig`](src/sevn/storage/d1_backend.py) — `src/sevn/storage/d1_backend.py`
- [`D1StorageBackend`](src/sevn/storage/d1_backend.py) — `src/sevn/storage/d1_backend.py`
- [`MigrationError`](src/sevn/storage/errors.py) — `src/sevn/storage/errors.py`
- [`StorageError`](src/sevn/storage/errors.py) — `src/sevn/storage/errors.py`
- [`apply_migrations`](src/sevn/storage/migrate.py) — `src/sevn/storage/migrate.py`
- [`is_turn_bundle_day_slug`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`sevn_db_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`traces_sqlite_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_day_dir`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_day_slug`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_file_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- _…and 4 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/storage`](src/sevn/storage/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/storage`](src/sevn/storage/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Amendments (spec-36-sub-agents)

Adds `subagent_runs` table (migration 23) mirroring the in-memory registry for
restart reconciliation, Mission Control recent history, and
`sevn subagents list --all`. Boot orphan sweep marks stale `running` → `orphaned`.

## Amendments (open-issues-sweep W18, #75)

Adds `delivery_obligations` table (migration 25): a first-class delivery-obligation
ledger with adapter-confirmed platform message ids. `ChannelRouter.route_outgoing`
persists a pending obligation before `adapter.send` and confirms it on success;
`sweep_outbound_retries` reconciles confirmed obligations without double-send when
`gateway_messages.status` lags after a crash.

## Amendments (open-issues-sweep W19, #76)

Adds `subagent_runs.result_body` and `result_delivered_at_ns` (migration 26).
Level-2 completion text is persisted at finish, delivered through the W18
delivery-obligation ledger, and replayed on boot when a crash prevented announce-back.

## Amendments (open-issues-sweep W20, #77)

Adds `subagent_runs.transcript_path` (migration 27). Each run writes a tailable
redacted JSONL transcript under `subagents/transcripts/<run_id>.jsonl` in the
workspace content root; completion updates include the path for operators.

## Amendments (open-issues-sweep W21, #85)

Adds `cron_runs` table (migration 28): append-only audit rows at claim and
completion, stale in-flight claims reconciled at gateway boot, and `overlap_policy`
enforced in `cron_tick`. Recent history is exposed on Mission Control cron ops APIs.

## Amendments (open-issues-sweep W22, #83)

Adds `session_export_jobs` (migration 29) for optional offline export audit
metadata. `sevn sessions export` gathers redacted history from SQLite,
workspace session mirror JSONL, turn metadata, and turn bundles.

## Amendments (release-audit W9, #147)

SQLite connection setup (`connect_sqlite`) uses `timeout=30`, `busy_timeout=30000`,
`synchronous=NORMAL`, and autocommit isolation (`isolation_level=None`) on top of
WAL + foreign keys. The gateway serializes writes through a process-wide
`asyncio.Lock` (`sqlite_write_lock`) — **single-process only**; multi-replica
deployments must not share one writable `sevn.db` file.

Adds `trigger_runs` (migration 30) so `GET /api/v1/runs/{run_id}` resolves status
from SQLite instead of the process-local `trigger_run_status` dict.

Operator CLI: `sevn db backup` / `sevn db restore` snapshot `.sevn/sevn.db` via
SQLite online backup after WAL checkpoint. CI runs
`make storage-migration-rehearsal-check` to restore the golden `migration_29.sql`
fixture and migrate forward to the bundle head.

## Implemented by

- [`D1Backend`](src/sevn/storage/d1.py) — `src/sevn/storage/d1.py`
- [`D1BackendConfig`](src/sevn/storage/d1_backend.py) — `src/sevn/storage/d1_backend.py`
- [`D1StorageBackend`](src/sevn/storage/d1_backend.py) — `src/sevn/storage/d1_backend.py`
- [`MigrationError`](src/sevn/storage/errors.py) — `src/sevn/storage/errors.py`
- [`StorageError`](src/sevn/storage/errors.py) — `src/sevn/storage/errors.py`
- [`apply_migrations`](src/sevn/storage/migrate.py) — `src/sevn/storage/migrate.py`
- [`is_turn_bundle_day_slug`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`sevn_db_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`traces_sqlite_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_day_dir`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_day_slug`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_file_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundle_index_path`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`turn_bundles_dir`](src/sevn/storage/paths.py) — `src/sevn/storage/paths.py`
- [`connect_sqlite`](src/sevn/storage/sqlite.py) — `src/sevn/storage/sqlite.py`
- [`open_sevn_sqlite`](src/sevn/storage/sqlite.py) — `src/sevn/storage/sqlite.py`

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.

## Human-input needed

Prose body not yet authored (W9 scope). Normative contract requires operator or
follow-up wave authoring against verified code (`sevn about-docs extract` + graphify).
Do not mark `status: done` until `make -C spec-kit-wave spec-check` scores ≥ 80.
