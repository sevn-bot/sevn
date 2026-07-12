---
name: second_brain
description: Karpathy-style raw→wiki ingest, lint, and file-back flows (`specs/27-second-brain.md`).
version: "1.0.0"
see_also:
  - wiki_search
  - second_brain_query
scripts:
  - path: scripts/ingest.py
    description: Live deterministic ingest for one raw path (raw→wiki/ingests, index, log).
    args_overview: "--raw PATH [--scope owner]"
  - path: scripts/lint.py
    description: Run wiki_lint rules and write wiki/lint-report-YYYY-MM-DD.md.
    args_overview: "[--scope owner]"
  - path: scripts/file_back.py
    description: File a markdown page into wiki/ and update index stub line.
    args_overview: "--slug STEM --title TEXT (--text STR | --body-file PATH) [--scope owner]"
---

# Second Brain skill

Use native tools `wiki_search`, `wiki_get`, `wiki_apply`, `wiki_lint`, and
`second_brain_query` for fine-grained steps. These scripts package common operator flows for
`run_skill_script`. Ingest is skill-owned — use `run_skill_script("second_brain", "ingest", …)`
instead of the deprecated native `second_brain_ingest_stub` (gated by
`tools.legacy_native.second_brain_ingest_stub.enabled`, default **false**).

## OKF wiki conventions

Each scope's `wiki/` directory is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle:

- Concept pages require `type:` in YAML frontmatter (`Ingest`, `Stub`, and `Note` are set by writers).
- Internal links: `[[wikilinks]]` **or** OKF markdown links like `[Title](/path/page.md)`.
- Reserved files: `index.md` and `log.md` (no `type` required).
- Run `wiki_lint` or `scripts/lint.py` to catch missing `type` and orphan links.
