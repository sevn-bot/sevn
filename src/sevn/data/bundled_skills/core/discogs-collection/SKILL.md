---
name: discogs-collection
description: >-
  Discogs user collection — folders, items, value, and collection search.
  Writes require --confirm unless confirm_writes is disabled.
version: "1.0.0"
see_also:
  - discogs-database
  - discogs-marketplace
  - discogs-wantlist
  - discogs-identity
scripts:
  - path: scripts/_discogs_common.py
    description: Shared Discogs client, JSON envelope, and error-mapping helpers.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/_helpers.py
    description: Shared serialization and CLI runner helpers for this skill's scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/list_folders.py
    description: List the authed user's collection folders.
    args_overview: ""
  - path: scripts/get_folder.py
    description: List releases in one collection folder.
    args_overview: "--folder-id ID [--page N] [--per-page N]"
  - path: scripts/search_collection.py
    description: Search the user's collection (domain search).
    args_overview: >-
      --folder-id ID [--release-id ID] [--query Q] [--page N] [--per-page N]
  - path: scripts/collection_value.py
    description: Fetch min/median/max collection value stats.
    args_overview: ""
  - path: scripts/add_release.py
    description: Add a release to a folder (write; requires --confirm).
    args_overview: "--folder-id ID --release-id ID --confirm"
  - path: scripts/remove_release.py
    description: Remove a collection item (write; requires --confirm).
    args_overview: "--folder-id ID --instance-id ID [--release-id ID] --confirm"
  - path: scripts/move_release.py
    description: Move a collection item to another folder (write; requires --confirm).
    args_overview: >-
      --folder-id ID --instance-id ID --target-folder-id ID
      [--release-id ID] --confirm
  - path: scripts/uncategorize_release.py
    description: Move a collection item to Uncategorized (write; requires --confirm).
    args_overview: "--folder-id ID --instance-id ID [--release-id ID] --confirm"
  - path: scripts/rate_release.py
    description: Rate or annotate a collection item (write; requires --confirm).
    args_overview: >-
      --folder-id ID --instance-id ID --rating N [--notes TEXT]
      [--release-id ID] --confirm
---

# discogs-collection

User collection folders, items, value stats, and collection search via
`python3-discogs-client`. Requires an authenticated Discogs identity (User-token
or OAuth).

**Auth:** required. Enable the skill group with `skills.discogs.enabled` and
configure credentials via Telegram **config → Skills → Discogs → Setup** or
workspace secrets.

**Writes:** every mutating script requires `--confirm` unless
`skills.discogs.confirm_writes` is `false`. Without `--confirm`, the script
returns `{"ok": false, "error": {"code": "CONFIRM_REQUIRED", "would_do": {...}}}`
and makes no API call.

**Envelope:** each script prints one JSON object — success
`{"ok": true, "data": {...}, "paging"?: {...}}` or failure
`{"ok": false, "error": {"code", "message"}}`.

## Examples

List folders:

```bash
python scripts/list_folders.py
```

Search collection:

```bash
python scripts/search_collection.py --folder-id 0 --query "kraftwerk" --page 1
```

Add a release (dry-run preview without `--confirm`):

```bash
python scripts/add_release.py --folder-id 0 --release-id 249504
```

Apply the add:

```bash
python scripts/add_release.py --folder-id 0 --release-id 249504 --confirm
```

Collection value:

```bash
python scripts/collection_value.py
```
