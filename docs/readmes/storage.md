<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint storage` -->
# Storage — SQLite paths, connections, schema migrations, and D1 layout

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** SQLite paths, connections, schema migrations, and D1 layout.

## Level 1 — Overview (non-technical)

**Storage** is the SQLite layer for sevn's workspace databases — primarily `sevn.db` (sessions, LCM, jobs, triggers, …) and `traces.db` (trace query index). On gateway boot, [`open_sevn_sqlite`](../../src/sevn/storage/sqlite.py#L59) opens the DB and runs forward migrations to the current schema head.

This package owns **paths, connections, and DDL** — not active-run snapshot semantics. Persist/resume of in-flight agent runs lives in [`agent/harness/snapshots.py`](../../src/sevn/agent/harness/snapshots.py) (uses the `active_run_snapshots` table created here).

## Level 2 — How it works (technical)

Implementation lives under [`src/sevn/storage/`](../../src/sevn/storage/).

### Schema migrations

[`apply_migrations`](../../src/sevn/storage/migrate.py#L570) applies versioned DDL idempotently; progress tracked in `schema_migrations`. Current head: **`MIGRATION_HEAD_VERSION = 23`** ([`migrate.py`](../../src/sevn/storage/migrate.py#L567)).

[`open_sevn_sqlite`](../../src/sevn/storage/sqlite.py#L59) always migrates before returning a connection.

### Table inventory (major `sevn.db` tables)

| Domain | Tables |
| --- | --- |
| Harness / sessions | `active_run_snapshots`, `gateway_sessions`, `gateway_messages`, `gateway_turn_metadata`, `gateway_user_profile`, `pending_plans`, `turn_replay_dedupe` |
| LCM / memory | `lcm_conversations`, `lcm_messages`, `lcm_summaries`, `lcm_context_items`, `memory`, `memory_search_events` |
| Gateway ops | `dispatcher_state`, `dispatcher_callbacks`, `telegram_topic_names`, `gateway_media_tokens` |
| Triggers | `trigger_webhook_dedupe`, `trigger_cron_jobs` |
| Self-improve / evolution | `self_improve_jobs`, `trajectory_fact`, `structured_feedback`, `feedback_events`, `cursor_cloud_jobs` |
| Sub-agents | `subagent_runs` |
| Skills / OpenUI | `skills`, `openui_tokens` |
| Triage | `triage_decisions` |
| Meta | `schema_migrations` |

Trace events themselves live in `traces.db` ([`traces_sqlite_path`](../../src/sevn/storage/paths.py#L44)) — managed by the tracing subsystem, not this migration runner.

### Paths

- [`sevn_db_path`](../../src/sevn/storage/paths.py#L27) — workspace `sevn.db`
- [`traces_sqlite_path`](../../src/sevn/storage/paths.py#L44) — `.sevn/traces/traces.db`
- [`turn_bundles_dir`](../../src/sevn/storage/paths.py#L64) — JSONL turn bundle layout

### Active-run snapshots (cross-ref)

Row shape and GC/resume logic: [`persist_run_snapshot`](../../src/sevn/agent/harness/snapshots.py), [`sweep_active_run_snapshots`](../../src/sevn/agent/harness/snapshots.py) in [`snapshots.py`](../../src/sevn/agent/harness/snapshots.py). The **table** is created in migration 1 ([`migrate.py`](../../src/sevn/storage/migrate.py)); **behaviour** is harness-owned.

### Optional D1 backend

[`D1StorageBackend`](../../src/sevn/storage/d1_backend.py) sketches Cloudflare D1 remote persistence ([`03-storage.md`](../../about-sevn.bot/specs/03-storage.md) §3.3) — local SQLite remains the default path.

### Key modules

- [`migrate.py`](../../src/sevn/storage/migrate.py) — [`apply_migrations`](../../src/sevn/storage/migrate.py#L570), `MIGRATION_HEAD_VERSION`
- [`sqlite.py`](../../src/sevn/storage/sqlite.py) — [`open_sevn_sqlite`](../../src/sevn/storage/sqlite.py#L59), [`connect_sqlite`](../../src/sevn/storage/sqlite.py#L30)
- [`paths.py`](../../src/sevn/storage/paths.py) — canonical DB paths

Normative spec: [`about-sevn.bot/specs/03-storage.md`](../../about-sevn.bot/specs/03-storage.md).

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/storage`](../../src/sevn/storage/) (7 Python files). Normative design: `about-sevn.bot/specs/03-storage.md`.

### Module inventory

Workspace persistence — SQLite paths, connections, migrations.

Working with [`__init__.py`](../../src/sevn/storage/__init__.py): inspect the public entry points below.

Cloudflare D1 backend protocol sketch (about-sevn.bot/specs/03-storage.md §3.3).

Working with [`d1.py`](../../src/sevn/storage/d1.py): inspect the public entry points below.
Start with [`D1Backend.apply_migration`](../../src/sevn/storage/d1.py#L15), then [`D1Backend.query`](../../src/sevn/storage/d1.py#L33).

Cloudflare D1 optional backend (about-sevn.bot/specs/03-storage.md §3.3).

Working with [`d1_backend.py`](../../src/sevn/storage/d1_backend.py): inspect the public entry points below.
Start with [`D1StorageBackend.ping`](../../src/sevn/storage/d1_backend.py#L62), then [`D1StorageBackend.apply_migration`](../../src/sevn/storage/d1_backend.py#L123), [`D1StorageBackend.query`](../../src/sevn/storage/d1_backend.py#L140).

Storage layer exceptions.

Working with [`errors.py`](../../src/sevn/storage/errors.py): inspect the public entry points below.

Versioned SQLite migrations for sevn.db.

Working with [`migrate.py`](../../src/sevn/storage/migrate.py): inspect the public entry points below.
Start with [`apply_migrations`](../../src/sevn/storage/migrate.py#L570).

Canonical paths for workspace SQLite files.

Working with [`paths.py`](../../src/sevn/storage/paths.py): inspect the public entry points below.
Start with [`sevn_db_path`](../../src/sevn/storage/paths.py#L27), then [`traces_sqlite_path`](../../src/sevn/storage/paths.py#L44), [`turn_bundles_dir`](../../src/sevn/storage/paths.py#L64), [`turn_bundle_day_slug`](../../src/sevn/storage/paths.py#L82).

SQLite connection helpers for workspace databases.

Working with [`sqlite.py`](../../src/sevn/storage/sqlite.py): inspect the public entry points below.
Start with [`connect_sqlite`](../../src/sevn/storage/sqlite.py#L30), then [`open_sevn_sqlite`](../../src/sevn/storage/sqlite.py#L59).

### Extension and invariants

Follow [`03-storage.md`](../../about-sevn.bot/specs/03-storage.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/storage`](../../src/sevn/storage/), run `sevn readme update storage` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/03-storage.md](../../about-sevn.bot/specs/03-storage.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/03-storage.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/storage/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
