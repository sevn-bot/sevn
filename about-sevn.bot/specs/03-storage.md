---
id: spec-03-storage
kind: spec
title: Storage — Spec
status: done
owner: Alex
summary: 'Own application persistence: connection setup (WAL, foreign keys), versioned
  migrations, canonical sevn.db path, optional traces.db path helper, and typed persistence
  contracts for crash-resume and (w'
last_updated: '2026-07-12'
fingerprint: sha256:c8d8696bb48df26ee44ca00953ab251cbd6b6d6cfc93c2d07da470a38c46aa9c
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
- name: D1Backend
  file: src/sevn/storage/d1.py
  symbol: D1Backend
- name: D1BackendConfig
  file: src/sevn/storage/d1_backend.py
  symbol: D1BackendConfig
- name: D1StorageBackend
  file: src/sevn/storage/d1_backend.py
  symbol: D1StorageBackend
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
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Storage — Spec (spec-03-storage) — Purpose.

## Public Interface

Offline scaffold for Storage — Spec (spec-03-storage) — Public Interface.

## Data Model

Offline scaffold for Storage — Spec (spec-03-storage) — Data Model.

## Internal Architecture

Offline scaffold for Storage — Spec (spec-03-storage) — Internal Architecture.

## Behavior

Offline scaffold for Storage — Spec (spec-03-storage) — Behavior.

## Failure Modes

Offline scaffold for Storage — Spec (spec-03-storage) — Failure Modes.

## Amendments (spec-36-sub-agents)

Adds `subagent_runs` table (migration 23) mirroring the in-memory registry for
restart reconciliation, Mission Control recent history, and
`sevn subagents list --all`. Boot orphan sweep marks stale `running` → `orphaned`.

## Test Strategy

Offline scaffold for Storage — Spec (spec-03-storage) — Test Strategy.
