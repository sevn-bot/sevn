---
name: second_brain
description: Layout-aware raw→vault ingest, lint, and file-back flows (`specs/27-second-brain.md`).
version: "1.1.0"
see_also:
  - wiki_search
  - second_brain_query
scripts:
  - path: scripts/ingest.py
    description: Live deterministic ingest for one raw path (layout-aware capture + index/log).
    args_overview: "--raw PATH [--scope owner]"
  - path: scripts/lint.py
    description: Run vault lint rules and write lint-report-YYYY-MM-DD.md under the curated root.
    args_overview: "[--scope owner]"
  - path: scripts/file_back.py
    description: File a markdown page into the curated role dir and update the index note.
    args_overview: "--slug STEM --title TEXT (--text STR | --body-file PATH) [--scope owner]"
---

# Second Brain skill

Use native tools `wiki_search`, `wiki_get`, `wiki_apply`, `wiki_lint`, and
`second_brain_query` for fine-grained steps. These scripts package common operator flows for
`run_skill_script`. Ingest is skill-owned — use `run_skill_script("second_brain", "ingest", …)`
instead of the deprecated native `second_brain_ingest_stub` (gated by
`tools.legacy_native.second_brain_ingest_stub.enabled`, default **false**).

## Vault layouts

`second_brain.layout` selects the path model (default **`legacy`**):

| Layout | Curated notes | Sources | Capture (ingest) | Index / log |
| --- | --- | --- | --- | --- |
| `legacy` | `wiki/` | `raw/` | `wiki/ingests/` | `wiki/index.md`, `wiki/log.md` |
| `para` | `30_Resources/` | `30_Resources/_sources/` | `00_Inbox/` | vault-root `index.md`, `log.md` |

Scripts and tools resolve paths through `VaultLayout` — no hardcoded `wiki/` assumptions.
Set PARA via `sevn second-brain setup --vault <path> --layout para` or `layout: "para"` in
`sevn.json`.

## Legacy OKF wiki conventions

When `layout="legacy"`, each scope's `wiki/` directory is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle:

- Concept pages require `type:` in YAML frontmatter (`Ingest`, `Stub`, and `Note` are set by writers).
- Internal links: `[[wikilinks]]` **or** OKF markdown links like `[Title](/path/page.md)`.
- Reserved files: `index.md` and `log.md` (no `type` required).
- Run `wiki_lint` or `scripts/lint.py` to catch missing `type` and orphan links.

## PARA Obsidian conventions

When `layout="para"`, notes follow Obsidian-native frontmatter (`tags`, `source`, `captured`, …).
`type:` is advisory (lint warning). Wikilinks resolve across PARA content roots (Inbox, Projects,
Areas, Resources). See bundled `para_MODEL.md` in the vault `MODEL.md`.
