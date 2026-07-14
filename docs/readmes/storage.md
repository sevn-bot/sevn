<!-- generated: do not edit by hand; run `sevn readme update storage` -->
# Storage — SQLite paths, connections, schema migrations, and D1 layout

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** SQLite paths, connections, schema migrations, and D1 layout.

## Level 1 — Overview (non-technical)

**Storage** is a core part of sevn.bot — the personal AI assistant you run on your own machine. SQLite paths, connections, schema migrations, and D1 layout.

In everyday use, storage helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/storage/`. The package contains 7 Python module(s); primary entry points include `src/sevn/storage/__init__.py`, `src/sevn/storage/d1.py`, `src/sevn/storage/d1_backend.py`, `src/sevn/storage/errors.py`, `src/sevn/storage/migrate.py`, `src/sevn/storage/paths.py`, and 1 more.

### Data and control flow

Storage is organized around `  init  `, `d1`, `d1 backend`, `errors`, and 2 more under `src/sevn/storage/` with 7 Python module(s) in the scanned tree. Primary entry points include d1.py (D1Backend.apply_migration), d1_backend.py (D1StorageBackend.ping), migrate.py (apply_migrations), paths.py (sevn_db_path).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/03-storage.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/storage/d1.py` — `D1Backend.apply_migration`, `D1Backend.query`
- `src/sevn/storage/d1_backend.py` — `D1StorageBackend.ping`, `D1StorageBackend.apply_migration`, `D1StorageBackend.query`
- `src/sevn/storage/migrate.py` — `apply_migrations`
- `src/sevn/storage/paths.py` — `sevn_db_path`, `traces_sqlite_path`, `turn_bundles_dir`, `turn_bundle_day_slug`
- `src/sevn/storage/sqlite.py` — `connect_sqlite`, `open_sevn_sqlite`

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
