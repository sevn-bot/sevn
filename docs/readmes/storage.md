<!-- generated: do not edit by hand; run `sevn readme update storage` -->
# Storage — SQLite schema, migrations, D1 paths, and ActiveRunSnapshot persistence

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** SQLite schema, migrations, D1 paths, and ActiveRunSnapshot persistence.

## Level 1 — Overview (non-technical)

**Storage** is a core part of sevn.bot — the personal AI assistant you run on your own machine. SQLite schema, migrations, D1 paths, and ActiveRunSnapshot persistence.

In everyday use, storage helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Own application persistence: connection setup (WAL, foreign keys), versioned migrations, canonical sevn.db path, optional traces.db path helper, and typed persistence contracts for crash-resume and (w

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/storage/`. The package contains 7 Python module(s); primary entry points include `src/sevn/storage/__init__.py`, `src/sevn/storage/d1.py`, `src/sevn/storage/d1_backend.py`, `src/sevn/storage/errors.py`, and 2 more.

### Data and control flow

Storage sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/03-storage.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/storage/d1.py` — `D1Backend.apply_migration`, `D1Backend.query`
- `src/sevn/storage/d1_backend.py` — `D1StorageBackend.ping`, `D1StorageBackend.apply_migration`, `D1StorageBackend.query`
- `src/sevn/storage/migrate.py` — `apply_migrations`
- `src/sevn/storage/paths.py` — `sevn_db_path`, `traces_sqlite_path`, `turn_bundles_dir`, `turn_bundle_day_slug`
- `src/sevn/storage/sqlite.py` — `connect_sqlite`, `open_sevn_sqlite`

### Spec context

From specs/03-storage.md:
Own application persistence: connection setup (WAL, foreign keys), versioned migrations, canonical sevn.db path, optional traces.db path helper, and typed persistence contracts for crash-resume and (w

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/storage/` (7 Python files). Normative design: `specs/03-storage.md`.

### Module inventory

- `src/sevn/storage/__init__.py` — """Workspace persistence — SQLite paths, connections, migrations.
- `src/sevn/storage/d1.py` — """Cloudflare D1 backend protocol sketch ('specs/03-storage.md' §3.3).
- `src/sevn/storage/d1_backend.py` — """Cloudflare D1 optional backend ('specs/03-storage.md' §3.3).
- `src/sevn/storage/errors.py` — """Storage layer exceptions.
- `src/sevn/storage/migrate.py` — """Versioned SQLite migrations for ''sevn.db''.
- `src/sevn/storage/paths.py` — """Canonical paths for workspace SQLite files.
- `src/sevn/storage/sqlite.py` — """SQLite connection helpers for workspace databases.

### D1 (`src/sevn/storage/d1.py`)

Public entry points:
- `D1Backend.apply_migration` — see `src/sevn/storage/d1.py`
- `D1Backend.query` — see `src/sevn/storage/d1.py`

### D1 Backend (`src/sevn/storage/d1_backend.py`)

Public entry points:
- `D1StorageBackend.ping` — see `src/sevn/storage/d1_backend.py`
- `D1StorageBackend.apply_migration` — see `src/sevn/storage/d1_backend.py`
- `D1StorageBackend.query` — see `src/sevn/storage/d1_backend.py`

### Migrate (`src/sevn/storage/migrate.py`)

Public entry points:
- `apply_migrations` — see `src/sevn/storage/migrate.py`

### Paths (`src/sevn/storage/paths.py`)

Public entry points:
- `sevn_db_path` — see `src/sevn/storage/paths.py`
- `traces_sqlite_path` — see `src/sevn/storage/paths.py`
- `turn_bundles_dir` — see `src/sevn/storage/paths.py`
- `turn_bundle_day_slug` — see `src/sevn/storage/paths.py`
- `is_turn_bundle_day_slug` — see `src/sevn/storage/paths.py`
- `turn_bundle_day_dir` — see `src/sevn/storage/paths.py`
- `turn_bundle_index_path` — see `src/sevn/storage/paths.py`
- `turn_bundle_file_path` — see `src/sevn/storage/paths.py`

### Sqlite (`src/sevn/storage/sqlite.py`)

Public entry points:
- `connect_sqlite` — see `src/sevn/storage/sqlite.py`
- `open_sevn_sqlite` — see `src/sevn/storage/sqlite.py`

### Extension and invariants

Follow `specs/03-storage.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/storage/`, run `sevn readme update storage` and `make readme-check`.

## References

- [specs/03-storage.md](specs/03-storage.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/03-storage.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/storage/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
