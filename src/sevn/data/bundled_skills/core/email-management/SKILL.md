---
name: email-management
description: Multi-account IMAP and Gmail API mail read/search/send scripts.
version: "1.0.0"
see_also:
  - load_skill
  - run_skill_script
  - message
egress:
  - gmail.googleapis.com
  - googleapis.com
  - imap.gmail.com
  - smtp.gmail.com
  - outlook.office365.com
  - imap-mail.outlook.com
  - smtp.office365.com
  - imap.mail.yahoo.com
  - smtp.mail.yahoo.com
  - fastmail.com
  - imap.fastmail.com
scripts:
  - path: scripts/list_accounts.py
    description: List configured mailbox accounts (metadata only; no secrets).
    args_overview: "[--dry-run]"
    abortable: true
  - path: scripts/list_folders.py
    description: List IMAP folders for one configured account.
    args_overview: "--account ID [--dry-run]"
    abortable: true
  - path: scripts/fetch_recent.py
    description: Fetch recent message summaries from an IMAP folder or Gmail label.
    args_overview: "--account ID [--folder INBOX] [--limit N] [--dry-run]"
    abortable: true
  - path: scripts/search.py
    description: Search messages by free-text query (IMAP TEXT or Gmail API plan).
    args_overview: "--account ID --query TEXT [--folder INBOX] [--limit N] [--dry-run]"
    abortable: true
  - path: scripts/send.py
    description: Send a plain-text email via SMTP for one account (operator ask-first).
    args_overview: "--account ID --to ADDR --subject TEXT --body TEXT [--dry-run]"
    abortable: false
---

# email-management

Multi-account mail workflows over **IMAP/SMTP** and **Gmail API** backends. Configure many accounts under ``skills.email_management.accounts`` in ``sevn.json``; credentials live in environment variables referenced by ``password_env`` (never returned in script JSON).

## Operator setup

1. Add accounts to ``sevn.json``:

```json
{
  "skills": {
    "email_management": {
      "accounts": [
        {
          "id": "personal",
          "label": "Personal Gmail",
          "backend": "imap",
          "host": "imap.gmail.com",
          "smtp_host": "smtp.gmail.com",
          "username": "me@gmail.com",
          "password_env": "EMAIL_PERSONAL_PASSWORD"
        },
        {
          "id": "work",
          "label": "Work Gmail API",
          "backend": "gmail_api",
          "username": "me@company.com",
          "password_env": "GMAIL_WORK_OAUTH_TOKEN"
        }
      ]
    }
  }
}
```

2. Export credentials on the gateway host (app passwords or OAuth bearer tokens):

```bash
export EMAIL_PERSONAL_PASSWORD='...'
export GMAIL_WORK_OAUTH_TOKEN='...'
```

Fallback env pattern: ``SEVN_EMAIL_<ACCOUNT_ID>_PASSWORD`` (uppercase, hyphens → underscores).

3. Use ``--dry-run`` or ``SEVN_EMAIL_DRY_RUN=1`` for plan-only JSON without network I/O.

## Security

- **Ask first** before sending mail (`send.py` is ``abortable: false``).
- Scripts never echo passwords/tokens in stdout.
- Gmail API live calls require operator OAuth wiring; v1 scripts emit API plans for ``gmail_api`` backends unless extended with live HTTP.
