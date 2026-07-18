<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint discogs` -->
# Discogs skills

> **Summary.** Opt-in bundled skill group for the Discogs REST API — catalog search, marketplace, collection, wantlist, and identity — via `python3-discogs-client` subprocess scripts with JSON envelopes.

## Overview

The **Discogs skill group** ships five bundled core skills under one opt-in switch (`skills.discogs.enabled`):

| Skill | Domain | Auth |
| --- | --- | --- |
| `discogs-database` | Public catalog search, artist/release/master/label lookups, price suggestions, marketplace stats | Optional (rate-limited without token) |
| `discogs-marketplace` | Inventory search, listings CRUD, orders, messages, fee lookup | Required |
| `discogs-collection` | Folders, collection search, value stats, add/remove/move/rate | Required |
| `discogs-wantlist` | Browse/search wantlist, add/remove/edit wants | Required |
| `discogs-identity` | `whoami` smoke-test, user profiles, public lists, contributions | Required for `whoami` |

All scripts print **one JSON object** on stdout:

- Success: `{"ok": true, "data": {...}, "paging"?: {"page", "pages", "per_page", "count"}}`
- Failure: `{"ok": false, "error": {"code", "message", "detail"?}}`

Write scripts require `--confirm` unless `skills.discogs.confirm_writes` is `false`. Without `--confirm` they return `CONFIRM_REQUIRED` with a `would_do` preview and make **no** API call.

Install the optional dependency once per environment:

```bash
uv sync --extra discogs
```

Bundled skill trees live under `src/sevn/data/bundled_skills/core/discogs-*/`. Per-skill manifests are in each `SKILL.md`.

## Enable the group

**Config (`sevn.json`):**

```json
{
  "skills": {
    "discogs": {
      "enabled": true,
      "auth_method": "user_token",
      "confirm_writes": true
    }
  }
}
```

**Telegram:** `/config` → **Skills** → **📀 Discogs**

1. Toggle **Enable Discogs skills** (`skills.discogs.enabled`).
2. Optionally toggle individual domain skills (`database`, `marketplace`, `collection`, `wantlist`, `identity`).
3. Cycle **Auth method** (`user_token` | `oauth`).
4. Open **⚙ Setup** to store credentials and run **Test connection** (`whoami`).

**Onboarding:** enable the **Discogs** Group-B capability (`skill.discogs`) during the wizard — it toggles `skills.discogs.enabled` and installs the `[discogs]` optional extra.

## User-token authentication

Use a Discogs **personal access token** for single-workspace operator auth.

### Generate a token (Discogs website)

1. Sign in at [discogs.com](https://www.discogs.com/).
2. **Settings** → **Developers**.
3. **Generate new token** (or use an existing token).
4. Copy the token — Discogs shows it once.

### Store in sevn (Telegram Setup)

1. `/config` → **Skills** → **Discogs** → **⚙ Setup**.
2. Tap **User-token**.
3. Paste the token when prompted.
4. sevn stores `discogs.user_token` in the workspace secrets chain and sets `skills.discogs.auth_method` to `user_token`.
5. Tap **Test connection** — success replies with your Discogs username from `discogs-identity/whoami`.

**Secret alias:** `discogs.user_token` (referenced in `sevn.json` as `${SECRET:discogs.user_token}` if configured manually).

## OAuth 1.0a authentication

Use OAuth when you need a registered Discogs application (consumer key/secret) and the standard authorize → verifier handshake.

### Create a Discogs application

1. Sign in at [discogs.com](https://www.discogs.com/).
2. **Settings** → **Developers** → **Create an application**.
3. Note the **Consumer Key** and **Consumer Secret**.
4. Callback URL is not required — sevn uses the manual verifier paste flow in Telegram.

### Complete OAuth in Telegram Setup

1. `/config` → **Skills** → **Discogs** → **⚙ Setup**.
2. Tap **OAuth**.
3. **Step 1:** paste **Consumer Key** → stored as `discogs.consumer_key`.
4. **Step 2:** paste **Consumer Secret** → stored as `discogs.consumer_secret`.
5. **Step 3:** sevn calls `begin_oauth`, DMs the **authorize URL** — open it in a browser and approve access. The URL embeds a one-time session token; open it only on a trusted device and do not forward the Telegram message to others.
6. **Step 4:** paste the **verifier** code from Discogs.
7. sevn calls `complete_oauth`, stores `discogs.oauth_token` and `discogs.oauth_token_secret`, sets `auth_method` to `oauth`, and runs a `whoami` smoke-test.

**Dispatcher payload hygiene:** OAuth wizard state in `dispatcher_state` carries step metadata only — consumer credentials and request tokens live exclusively in the workspace secrets chain, never in the JSON payload.

**Secret aliases:** `discogs.consumer_key`, `discogs.consumer_secret`, `discogs.oauth_token`, `discogs.oauth_token_secret`.

## Script reference

Each example shows the subprocess invocation (from the skill's `scripts/` directory) and a representative success envelope. IDs are illustrative.

### discogs-database

| Script | Purpose |
| --- | --- |
| `search.py` | Domain search (artists, releases, masters, labels) |
| `get_artist.py` | Artist by id |
| `get_release.py` | Release by id |
| `get_master.py` | Master by id |
| `get_label.py` | Label by id |
| `price_suggestions.py` | Marketplace price suggestions for a release |
| `marketplace_stats.py` | For-sale count and lowest price for a release |

**search.py**

```bash
python scripts/search.py --query "kraftwerk" --type release --genre Electronic --page 1
```

```json
{"ok": true, "data": {"results": [{"id": 249504, "title": "Autobahn", "type": "release"}]}, "paging": {"page": 1, "pages": 3, "per_page": 50, "count": 120}}
```

**get_release.py**

```bash
python scripts/get_release.py --id 249504
```

```json
{"ok": true, "data": {"id": 249504, "title": "Autobahn", "artists": [{"name": "Kraftwerk"}], "formats": [{"name": "Vinyl"}]}}
```

**get_artist.py**

```bash
python scripts/get_artist.py --id 1234
```

```json
{"ok": true, "data": {"id": 1234, "name": "Kraftwerk", "profile": "..."}}
```

**get_master.py**

```bash
python scripts/get_master.py --id 5678
```

```json
{"ok": true, "data": {"id": 5678, "title": "Autobahn", "main_release": 249504}}
```

**get_label.py**

```bash
python scripts/get_label.py --id 90
```

```json
{"ok": true, "data": {"id": 90, "name": "Philips", "sublabels": []}}
```

**price_suggestions.py**

```bash
python scripts/price_suggestions.py --id 249504
```

```json
{"ok": true, "data": {"release_id": 249504, "suggestions": {"Mint": {"value": 25.0, "currency": "USD"}}}}
```

**marketplace_stats.py**

```bash
python scripts/marketplace_stats.py --id 249504
```

```json
{"ok": true, "data": {"num_for_sale": 12, "lowest_price": {"value": 8.5, "currency": "USD"}}}
```

### discogs-marketplace

| Script | Write? |
| --- | --- |
| `search_inventory.py` | no |
| `get_listing.py` | no |
| `create_listing.py` | yes (`--confirm`) |
| `edit_listing.py` | yes |
| `delete_listing.py` | yes |
| `get_order.py` | no |
| `list_orders.py` | no |
| `update_order.py` | yes |
| `list_order_messages.py` | no |
| `add_order_message.py` | yes |
| `fee.py` | no |

**search_inventory.py**

```bash
python scripts/search_inventory.py --status "For Sale" --page 1
```

```json
{"ok": true, "data": {"listings": [{"id": 999, "price": 25.0}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 3}}
```

**create_listing.py** (preview without `--confirm`):

```bash
python scripts/create_listing.py --release-id 249504 --condition Mint --price 25.00
```

```json
{"ok": false, "error": {"code": "CONFIRM_REQUIRED", "message": "Pass --confirm to create listing", "would_do": {"release_id": 249504, "condition": "Mint", "price": 25.0}}}
```

**fee.py**

```bash
python scripts/fee.py --price 25.00 --currency USD
```

```json
{"ok": true, "data": {"price": 25.0, "currency": "USD", "fee": 1.25}}
```

**get_listing.py**

```bash
python scripts/get_listing.py --id 999
```

```json
{"ok": true, "data": {"id": 999, "status": "For Sale", "price": 25.0}}
```

**edit_listing.py**

```bash
python scripts/edit_listing.py --listing-id 999 --price 22.00 --confirm
```

```json
{"ok": true, "data": {"id": 999, "price": 22.0}}
```

**delete_listing.py**

```bash
python scripts/delete_listing.py --listing-id 999 --confirm
```

```json
{"ok": true, "data": {"deleted": true, "listing_id": 999}}
```

**get_order.py**

```bash
python scripts/get_order.py --id 555
```

```json
{"ok": true, "data": {"id": 555, "status": "Payment Received"}}
```

**list_orders.py**

```bash
python scripts/list_orders.py --page 1
```

```json
{"ok": true, "data": {"orders": [{"id": 555}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 1}}
```

**update_order.py**

```bash
python scripts/update_order.py --order-id 555 --status Shipped --confirm
```

```json
{"ok": true, "data": {"id": 555, "status": "Shipped"}}
```

**list_order_messages.py**

```bash
python scripts/list_order_messages.py --id 555
```

```json
{"ok": true, "data": {"messages": [{"message": "Shipped today", "timestamp": "2026-07-18T12:00:00Z"}]}}
```

**add_order_message.py**

```bash
python scripts/add_order_message.py --order-id 555 --message "Thanks!" --confirm
```

```json
{"ok": true, "data": {"order_id": 555, "message": "Thanks!"}}
```

### discogs-collection

| Script | Write? |
| --- | --- |
| `list_folders.py` | no |
| `get_folder.py` | no |
| `search_collection.py` | no |
| `collection_value.py` | no |
| `add_release.py` | yes |
| `remove_release.py` | yes |
| `move_release.py` | yes |
| `uncategorize_release.py` | yes |
| `rate_release.py` | yes |

**list_folders.py**

```bash
python scripts/list_folders.py
```

```json
{"ok": true, "data": {"folders": [{"id": 0, "name": "All"}, {"id": 1, "name": "Uncategorized"}]}}
```

**get_folder.py**

```bash
python scripts/get_folder.py --folder-id 0 --page 1
```

```json
{"ok": true, "data": {"folder_id": 0, "releases": [{"instance_id": 42, "release_id": 249504}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 1}}
```

**search_collection.py**

```bash
python scripts/search_collection.py --folder-id 0 --query "kraftwerk" --page 1
```

```json
{"ok": true, "data": {"results": [{"release_id": 249504, "title": "Autobahn"}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 1}}
```

**collection_value.py**

```bash
python scripts/collection_value.py
```

```json
{"ok": true, "data": {"minimum": 100.0, "median": 500.0, "maximum": 1200.0, "currency": "USD"}}
```

**add_release.py**

```bash
python scripts/add_release.py --folder-id 0 --release-id 249504 --confirm
```

```json
{"ok": true, "data": {"folder_id": 0, "release_id": 249504, "instance_id": 43}}
```

**remove_release.py**

```bash
python scripts/remove_release.py --folder-id 0 --instance-id 43 --confirm
```

```json
{"ok": true, "data": {"removed": true, "instance_id": 43}}
```

**move_release.py**

```bash
python scripts/move_release.py --folder-id 0 --instance-id 43 --target-folder-id 2 --confirm
```

```json
{"ok": true, "data": {"instance_id": 43, "target_folder_id": 2}}
```

**uncategorize_release.py**

```bash
python scripts/uncategorize_release.py --folder-id 2 --instance-id 43 --confirm
```

```json
{"ok": true, "data": {"instance_id": 43, "folder_id": 1}}
```

**rate_release.py**

```bash
python scripts/rate_release.py --folder-id 0 --instance-id 43 --rating 5 --notes "Mint copy" --confirm
```

```json
{"ok": true, "data": {"instance_id": 43, "rating": 5, "notes": "Mint copy"}}
```

### discogs-wantlist

| Script | Write? |
| --- | --- |
| `get_wantlist.py` | no |
| `search_wantlist.py` | no |
| `add_want.py` | yes |
| `remove_want.py` | yes |
| `edit_want.py` | yes |

**get_wantlist.py**

```bash
python scripts/get_wantlist.py --page 1
```

```json
{"ok": true, "data": {"items": [{"release_id": 249504, "notes": "must have"}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 1}}
```

**search_wantlist.py**

```bash
python scripts/search_wantlist.py --artist Kraftwerk
```

```json
{"ok": true, "data": {"items": [{"release_id": 249504, "title": "Autobahn"}]}}
```

**add_want.py**

```bash
python scripts/add_want.py --release-id 249504 --notes "must have" --confirm
```

```json
{"ok": true, "data": {"release_id": 249504, "notes": "must have"}}
```

**remove_want.py**

```bash
python scripts/remove_want.py --release-id 249504 --confirm
```

```json
{"ok": true, "data": {"removed": true, "release_id": 249504}}
```

**edit_want.py**

```bash
python scripts/edit_want.py --release-id 249504 --rating 5 --confirm
```

```json
{"ok": true, "data": {"release_id": 249504, "rating": 5}}
```

### discogs-identity

| Script | Purpose |
| --- | --- |
| `whoami.py` | Auth smoke-test — authenticated username |
| `get_user.py` | Public user profile |
| `list_user_lists.py` | User's public lists |
| `get_list.py` | One list and its items |
| `search_lists.py` | Filter lists by name |
| `contributions.py` | Releases a user contributed |

**whoami.py**

```bash
python scripts/whoami.py
```

```json
{"ok": true, "data": {"username": "mydiscogsuser", "id": 12345}}
```

**get_user.py**

```bash
python scripts/get_user.py --username someone
```

```json
{"ok": true, "data": {"username": "someone", "num_collection": 500, "num_wantlist": 20}}
```

**list_user_lists.py**

```bash
python scripts/list_user_lists.py --username someone --page 1
```

```json
{"ok": true, "data": {"lists": [{"id": 12345, "name": "Best of 2020"}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 1}}
```

**get_list.py**

```bash
python scripts/get_list.py --list-id 12345
```

```json
{"ok": true, "data": {"id": 12345, "name": "Best of 2020", "items": [{"release_id": 249504}]}}
```

**search_lists.py**

```bash
python scripts/search_lists.py --username someone --name "best of"
```

```json
{"ok": true, "data": {"lists": [{"id": 12345, "name": "Best of 2020"}]}}
```

**contributions.py**

```bash
python scripts/contributions.py --username someone --page 1
```

```json
{"ok": true, "data": {"releases": [{"id": 249504, "title": "Autobahn"}]}, "paging": {"page": 1, "pages": 1, "per_page": 50, "count": 1}}
```

## References

- Skills catalog: [`docs/readmes/skills.md`](skills.md)
- Bundled trees: `src/sevn/data/bundled_skills/core/discogs-{database,marketplace,collection,wantlist,identity}/`
- Config section: `src/sevn/config/sections/skills_discogs.py`
- Gate and secrets: `src/sevn/skills/discogs.py`, `src/sevn/skills/discogs_secrets.py`
- Telegram menu: `src/sevn/gateway/menu/discogs_menu.py`
- OAuth integration: `src/sevn/integrations/discogs/oauth.py`
- Client library: [python3-discogs-client](https://python3-discogs-client.readthedocs.io/en/latest/)
