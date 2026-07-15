# MODEL — PARA Obsidian vault

> **Legacy layout?** When `second_brain.layout` is `"legacy"` (the default), see
> [`default_MODEL.md`](../default_MODEL.md) for the OKF `wiki/raw/outputs` conventions.

## Identity

Describe the topic domain this vault covers.

## PARA layout

- `00_Inbox/` — capture and triage (bot ingests land here).
- `10_Projects/` — active outcomes with deadlines.
- `20_Areas/` — ongoing responsibilities.
- `30_Resources/` — curated reference notes.
  - `30_Resources/_sources/` — immutable fetched sources (hashed).
  - `30_Resources/_outputs/` — bot analyses and drafts.
- `40_Archive/` — inactive work.
- `90_Templates/` — note templates.

Folder names are configurable via `second_brain.para` in `sevn.json`.

## Obsidian conventions

### Frontmatter (advisory)

Obsidian-native keys: `tags`, `aliases`, `created`, `updated`, `source`, `source_hash`, `captured`.

`type:` is optional in PARA — use when helpful, not required.

Sevn provenance keys remain accepted: `sevn_source`, `sevn_evidence`, `sevn_freshness`, `stub`.

### Internal links

Use wikilinks across PARA folders: `[[10_Projects/my-project]]`, `[[30_Resources/topic]]`.

### Home and log

- `index.md` — vault home note (no `type` required).
- `log.md` — append-only maintenance and ingest log (no `type` required).

## Focus areas

List 3–5 topics you want this knowledge base to emphasise.
