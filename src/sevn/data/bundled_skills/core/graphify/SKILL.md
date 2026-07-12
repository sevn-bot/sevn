---
name: graphify
description: Knowledge-graph orientation for code (`specs/28-code-understanding.md` §2.4).
version: "0.1.0"
see_also:
  - mycode
scripts:
  - path: scripts/build.py
    description: Build a knowledge graph from a GraphifyProfile (live subprocess or dry-run argv plan).
    args_overview: "--profile-id ID --root PATH --output PATH [--flag FLAG ...] [--dry-run]"
---

# graphify skill

Use when the user's question is **architecture-level** over a path tree that a
Graphify profile already covers: read `GRAPH_REPORT.md` first to learn the
god-nodes and community structure, then drill down with raw search.

Prefer this layer over `roam_code` for "how do these modules fit together?"
questions, and over `code_graph_rag` when a precise symbol-level export is not
required.

## Status

`scripts/build.py` invokes `graphify build` when the optional `graphify` extra
is installed (`uv sync --extra graphify`). Pass `--dry-run` or set
`SEVN_GRAPHIFY_DRY_RUN=1` for argv planning only. Missing CLI returns a
`DEPENDENCY_MISSING` envelope (see `specs/28-code-understanding.md` §4.3).
