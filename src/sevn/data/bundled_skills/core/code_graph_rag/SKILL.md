---
name: code_graph_rag
description: CGR export reader + allowlisted cgr CLI (`specs/28-code-understanding.md` §2.2).
version: "0.1.0"
see_also:
  - mycode
  - graphify
scripts:
  - path: scripts/read_export.py
    description: Read a capped slice of the CGR export JSON (replaces code_graph_rag_read_export).
    args_overview: "[--query STR] [--max-bytes N]"
  - path: scripts/cgr_cli.py
    description: Invoke allowlisted cgr subcommands only (replaces code_graph_rag_cli).
    args_overview: "SUBCOMMAND (export|stats|doctor|graph-loader)"
---

# code_graph_rag skill

Wraps **`sevn.code_understanding.cgr_adapter`** and **`cgr_runner`**:

- **`read_export.py`** — reads ``<workspace>/.index/code_graph_rag/export.json`` when present, otherwise
  runs allowlisted ``cgr export`` and caches the result.
- **`cgr_cli.py`** — runs exactly one allowlisted ``cgr`` subcommand; free-form argv is rejected.

Use native **`load_skill`** + **`run_skill_script`**. Native tools
**`code_graph_rag_read_export`** / **`code_graph_rag_cli`** register only when
``tools.legacy_native.code_graph_rag.enabled`` is true (default **false**).
