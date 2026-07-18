---
name: discogs-marketplace
description: >-
  Discogs marketplace — inventory search, listings CRUD, orders, messages, and
  fee lookup. Writes require --confirm unless confirm_writes is disabled.
version: "1.0.0"
see_also:
  - discogs-database
  - discogs-collection
  - discogs-wantlist
  - discogs-identity
scripts:
  - path: scripts/_discogs_common.py
    description: Shared Discogs client, JSON envelope, and error-mapping helpers.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/_helpers.py
    description: Shared serialization and CLI runner helpers for this skill's scripts.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/search_inventory.py
    description: Search the authed user's inventory (domain search).
    args_overview: >-
      [--status S] [--min-price N] [--max-price N] [--query Q] [--page N]
      [--per-page N]
  - path: scripts/get_listing.py
    description: Fetch one marketplace listing by id.
    args_overview: "--id ID"
  - path: scripts/create_listing.py
    description: Create a listing (write; requires --confirm).
    args_overview: >-
      --release-id ID --condition CONDITION --price PRICE [--status STATUS]
      [--sleeve-condition S] [--comments TEXT] --confirm
  - path: scripts/edit_listing.py
    description: Edit a listing (write; requires --confirm).
    args_overview: >-
      --listing-id ID [--price P] [--condition C] [--status S]
      [--sleeve-condition S] [--comments TEXT] --confirm
  - path: scripts/delete_listing.py
    description: Delete a listing (write; requires --confirm).
    args_overview: "--listing-id ID --confirm"
  - path: scripts/get_order.py
    description: Fetch one marketplace order by id.
    args_overview: "--id ID"
  - path: scripts/list_orders.py
    description: List the authed user's orders.
    args_overview: "[--page N] [--per-page N]"
  - path: scripts/update_order.py
    description: Update order status or shipping (write; requires --confirm).
    args_overview: "--order-id ID [--status S] [--shipping N] --confirm"
  - path: scripts/list_order_messages.py
    description: List messages on an order.
    args_overview: "--id ORDER_ID"
  - path: scripts/add_order_message.py
    description: Add a message to an order (write; requires --confirm).
    args_overview: "--order-id ID --message TEXT [--status S] --confirm"
  - path: scripts/fee.py
    description: Compute marketplace fee for a price.
    args_overview: "--price P [--currency USD]"
---

# discogs-marketplace

Marketplace inventory, listings, orders, and fees via `python3-discogs-client`.
Requires an authenticated Discogs identity (User-token or OAuth).

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

Search inventory:

```bash
python scripts/search_inventory.py --status "For Sale" --page 1
```

Create a listing (dry-run preview without `--confirm`):

```bash
python scripts/create_listing.py --release-id 249504 --condition Mint --price 25.00
```

Apply the listing:

```bash
python scripts/create_listing.py --release-id 249504 --condition Mint --price 25.00 --confirm
```

Compute fee:

```bash
python scripts/fee.py --price 25.00 --currency USD
```
