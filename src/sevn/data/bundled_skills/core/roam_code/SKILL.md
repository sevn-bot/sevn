---
name: roam_code
description: Lightweight roam-code path Q&A (`specs/28-code-understanding.md` §2.2).
version: "0.1.0"
see_also:
  - mycode
  - code_graph_rag
  - graphify
scripts:
  - path: scripts/query.py
    description: Run allowlisted roam understand/retrieve against a repo root.
    args_overview: "[--path PATH] [--query STR]"
---

# roam_code skill

Wraps **`sevn.code_understanding.roam_runner`** and **`RoamCodeAdapter`**:

- **`query.py`** — runs ``roam understand`` when ``--query`` is omitted, otherwise
  ``roam retrieve "<query>"`` from ``--path`` or ``SEVN_WORKSPACE``.

Use native **`load_skill`** + **`run_skill_script`**. Native tool **`roam_code`**
registers only when ``tools.legacy_native.roam_code.enabled`` is true (default **false**).

Install upstream CLI: ``uv tool install roam-code`` or ``pip install roam-code``.
