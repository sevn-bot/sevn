# Gmail search syntax

Useful Gmail query operators for `google_api.py gmail search`:

- `from:alice@example.com` — sender filter
- `to:bob@example.com` — recipient filter
- `subject:"quarterly report"` — subject text
- `label:inbox` or `label:work` — label filter
- `is:unread`, `is:starred`, `is:important` — state filters
- `has:attachment` — only messages with attachments
- `after:2026/07/01` and `before:2026/07/31` — date window
- `newer_than:7d`, `older_than:30d` — relative age
- `category:promotions`, `category:social`, `category:updates` — Gmail categories
- `in:anywhere` — search all mail, not just inbox
- `"exact phrase"` — exact text match
- `foo OR bar` — either term
- `-label:spam` or `-from:news@example.com` — exclusion

Examples:

- `is:unread label:inbox`
- `from:billing@example.com newer_than:14d`
- `subject:"meeting notes" has:attachment`
- `in:anywhere "contract renewal" -label:trash`
