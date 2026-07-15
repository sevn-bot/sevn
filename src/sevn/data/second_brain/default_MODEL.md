# MODEL — Second Brain schema (legacy layout)

> **PARA layout?** When `second_brain.layout` is `"para"`, see bundled
> [`para_MODEL.md`](para_MODEL.md) (copied to vault `MODEL.md` on PARA bootstrap).

## Identity

Describe the topic domain this vault covers.

## Architecture

- `raw/` — source material (immutable; bot reads only).
- `wiki/` — curated markdown the bot maintains (OKF knowledge bundle root).
- `outputs/` — analyses and drafts.

## Wiki conventions (OKF + sevn)

Each `wiki/` tree follows [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) v0.1 with sevn provenance extensions.

### Frontmatter

Every concept page (any `.md` except reserved `index.md` / `log.md`) MUST include:

- `type:` — OKF concept kind (e.g. `Note`, `Ingest`, `Playbook`, `Reference`)
- `title:` — display name (recommended)

Sevn-specific fields (keep using these for provenance):

- `sevn_source`, `sevn_evidence`, optional `sevn_freshness`
- `stub:` — ingest pipeline flag (`true` stub, `false` live/promoted)

Optional OKF fields: `description`, `resource`, `tags`, `timestamp`.

### Internal links

Both forms are supported:

- **Obsidian wikilinks:** `[[ingests/foo]]` or `[[ingests/foo.md]]`
- **OKF bundle-relative links:** `[customers table](/tables/customers.md)` (leading `/` is relative to `wiki/` root)
- **Relative OKF links:** `[neighbor](./other.md)` from the source page's directory

Use OKF links when you want stable paths; wikilinks remain fine for operator-authored pages.

### Citations and contradictions

- Factual claims cite `[Source: path-or-page.md]` (sevn convention).
- OKF `# Citations` sections with numbered external links are also welcome.
- Flag contradictions with `> CONTRADICTION:` when sources disagree.

## Index and log

- `wiki/index.md` — progressive-disclosure catalog (OKF index; no `type` required).
- `wiki/log.md` — append-only ingest and maintenance notes (OKF log; no `type` required).

Index bullets may use wikilinks (`- [[slug]] — summary`) or OKF form (`- [Title](/path.md) — summary`).

## Focus areas

List 3–5 topics you want this knowledge base to emphasise.
