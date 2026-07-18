---
name: discogs-identity
description: >-
  Discogs authenticated identity — whoami smoke-test, user profiles, public lists,
  and release contributions.
version: "1.0.0"
see_also:
  - discogs-database
  - discogs-marketplace
  - discogs-collection
  - discogs-wantlist
scripts:
  - path: scripts/whoami.py
    description: Auth smoke-test — returns the authenticated Discogs username.
    args_overview: "(no args)"
  - path: scripts/get_user.py
    description: Fetch a user profile (collection/wantlist counts, rank, rating).
    args_overview: "--username NAME"
  - path: scripts/list_user_lists.py
    description: List a user's public lists.
    args_overview: "--username NAME [--page N] [--per-page N]"
  - path: scripts/get_list.py
    description: Fetch one list and its items.
    args_overview: "--list-id ID [--page N] [--per-page N]"
  - path: scripts/search_lists.py
    description: Search a user's lists by name (domain search).
    args_overview: "--username NAME [--name QUERY] [--page N] [--per-page N]"
  - path: scripts/contributions.py
    description: List releases a user contributed to Discogs.
    args_overview: "--username NAME [--page N] [--per-page N]"
---

# discogs-identity

Authenticated Discogs identity, profiles, public lists, and contributions via
`python3-discogs-client`. Read-only — no write scripts in this skill.

**Auth:** required for `whoami` (uses `Client.identity()`). Profile and list
scripts accept any public username; enable the skill group with
`skills.discogs.enabled` and configure credentials via Telegram
**config → Skills → Discogs → Setup** or workspace secrets.

**Smoke-test:** run `whoami.py` after configuring User-token or OAuth to confirm
the workspace is authenticated.

**Envelope:** each script prints one JSON object — success
`{"ok": true, "data": {...}, "paging"?: {...}}` or failure
`{"ok": false, "error": {"code", "message"}}`.

## Examples

Confirm authentication:

```bash
python scripts/whoami.py
```

Fetch a profile:

```bash
python scripts/get_user.py --username someone
```

List public lists:

```bash
python scripts/list_user_lists.py --username someone --page 1
```

Search lists by name:

```bash
python scripts/search_lists.py --username someone --name "best of"
```

Fetch list items:

```bash
python scripts/get_list.py --list-id 12345
```

Contributions:

```bash
python scripts/contributions.py --username someone
```
