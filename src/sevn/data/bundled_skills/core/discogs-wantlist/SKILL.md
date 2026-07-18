---
name: discogs-wantlist
description: >-
  Discogs user wantlist — browse, search, and manage wants. Writes require
  --confirm unless confirm_writes is disabled.
version: "1.0.0"
see_also:
  - discogs-database
  - discogs-marketplace
  - discogs-collection
  - discogs-identity
scripts:
  - path: scripts/get_wantlist.py
    description: Fetch the authed user's wantlist.
    args_overview: "[--page N] [--per-page N]"
  - path: scripts/search_wantlist.py
    description: Search the wantlist by artist or title (domain search).
    args_overview: "[--artist NAME] [--title NAME] [--page N] [--per-page N]"
  - path: scripts/add_want.py
    description: Add a release to the wantlist (write; requires --confirm).
    args_overview: >-
      --release-id ID [--notes TEXT] [--notes-public true|false] [--rating 1-5]
      --confirm
  - path: scripts/remove_want.py
    description: Remove a release from the wantlist (write; requires --confirm).
    args_overview: "--release-id ID --confirm"
  - path: scripts/edit_want.py
    description: Edit wantlist notes or rating (write; requires --confirm).
    args_overview: >-
      --release-id ID [--notes TEXT] [--notes-public true|false] [--rating 1-5]
      --confirm
---

# discogs-wantlist

Browse, search, and manage the authenticated user's Discogs wantlist via
`python3-discogs-client`. Requires an authenticated Discogs identity (User-token
or OAuth).

**Auth:** required. Enable the skill group with `skills.discogs.enabled` and configure
credentials via Telegram **config → Skills → Discogs → Setup** or workspace secrets.

**Writes:** every mutating script requires `--confirm` unless
`skills.discogs.confirm_writes` is `false`. Without `--confirm`, the script returns
`{"ok": false, "error": {"code": "CONFIRM_REQUIRED", "would_do": {...}}}` and makes
no API call.

**Envelope:** each script prints one JSON object — success
`{"ok": true, "data": {...}, "paging"?: {...}}` or failure
`{"ok": false, "error": {"code", "message"}}`.

## Examples

List the wantlist:

```bash
python scripts/get_wantlist.py --page 1
```

Search by artist:

```bash
python scripts/search_wantlist.py --artist Kraftwerk
```

Add a want (dry-run preview without `--confirm`):

```bash
python scripts/add_want.py --release-id 249504 --notes "must have"
```

Apply the add:

```bash
python scripts/add_want.py --release-id 249504 --notes "must have" --confirm
```

Remove a want:

```bash
python scripts/remove_want.py --release-id 249504 --confirm
```

Edit rating:

```bash
python scripts/edit_want.py --release-id 249504 --rating 5 --confirm
```
