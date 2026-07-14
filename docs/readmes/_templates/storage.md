<!-- template: slug=storage profile=subsystem — see _templates/README.md for the markup contract -->

# <Title — "Storage — <one-line scope>">

<!-- fill: badge row (spec/source/index), left as the pipeline stamps them -->

> **Summary.** <one sentence; mirror the manifest summary>

## Level 1 — Overview (non-technical)

<!-- fill: 1–2 short paragraphs. SQLite paths, connections, forward migrations for
     sevn.db and traces.db. Not active-run snapshot persistence (that lives in harness).
     Operator terms in L1. -->

## Level 2 — How it works (technical)

<!-- fill: subsystem-specific subsections. Expected for storage:
       ### Schema migrations — MIGRATION_HEAD_VERSION, apply_migrations, schema_migrations table
       ### Table inventory — major sevn.db tables by domain
       ### Paths — sevn_db_path, traces_sqlite_path
       ### Active-run snapshots cross-ref — agent/harness/snapshots.py (not this package)
       ### Configuration — workspace layout, optional D1 backend sketch
     Cite real symbols. D21 links throughout. -->

### Key modules

<!-- fill: bullet list of load-bearing modules with a one-line role each -->

## Level 3 — Deep dive (low-level, technical)

<!-- generated: pipeline-owned below until References. Do not hand-author. -->

### Module inventory

### Extension and invariants

<!-- /generated -->

## References
