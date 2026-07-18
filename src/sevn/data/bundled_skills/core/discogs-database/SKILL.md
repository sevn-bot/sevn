---
name: discogs-database
description: >-
  Discogs public catalog — search artists/releases/masters/labels and read
  release price suggestions and marketplace stats. Works without auth (rate-limited).
version: "1.0.0"
see_also:
  - discogs-marketplace
  - discogs-collection
  - discogs-wantlist
  - discogs-identity
scripts:
  - path: scripts/search.py
    description: Search the Discogs database (domain search).
    args_overview: >-
      --query Q [--type artist|release|master|label] [--genre G] [--style S]
      [--year Y] [--country C] [--format F] [--label L] [--artist A]
      [--page N] [--per-page N]
  - path: scripts/get_artist.py
    description: Fetch one artist by id.
    args_overview: "--id ID"
  - path: scripts/get_release.py
    description: Fetch one release by id (tracklist, credits, formats, etc.).
    args_overview: "--id ID"
  - path: scripts/get_master.py
    description: Fetch one master release by id.
    args_overview: "--id ID"
  - path: scripts/get_label.py
    description: Fetch one label by id.
    args_overview: "--id ID"
  - path: scripts/price_suggestions.py
    description: Fetch marketplace price suggestions for a release.
    args_overview: "--id RELEASE_ID"
  - path: scripts/marketplace_stats.py
    description: Fetch marketplace stats (for sale count, lowest price) for a release.
    args_overview: "--id RELEASE_ID"
---

# discogs-database

Read-only access to the public Discogs catalog via `python3-discogs-client`.
Enable the skill group with `skills.discogs.enabled` (Telegram: **config → Skills → Discogs**).

**Auth:** optional. Unauthenticated requests work but are rate-limited by Discogs; a
User-token or OAuth identity raises rate limits. Credentials are injected from workspace
secrets — never pass tokens on the CLI.

**Envelope:** every script prints one JSON object — success
`{"ok": true, "data": {...}, "paging"?: {...}}` or failure
`{"ok": false, "error": {"code", "message"}}`.

## Examples

Search releases:

```bash
python scripts/search.py --query "kraftwerk" --type release --genre Electronic --page 1
```

Lookup a release:

```bash
python scripts/get_release.py --id 249504
```

Price suggestions:

```bash
python scripts/price_suggestions.py --id 249504
```
