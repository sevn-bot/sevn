---
name: proton-management
description: Proton suite CLI (Python port) — Pass, Mail, Drive, Calendar, Contacts.
version: "0.5.0"
see_also:
  - load_skill
  - run_skill_script
  - sevn-diagnostics
  - email-management
egress:
  - mail.proton.me
  - drive.proton.me
  - calendar.proton.me
  - pass.proton.me
  - account.proton.me
  - api.proton.me
scripts:
  - path: scripts/status.py
    description: Check proton-cli install, profile, and session file (no secrets).
    args_overview: "[--profile NAME]"
    abortable: true
  - path: scripts/pass_vaults_list.py
    description: List Pass vault metadata via proton-cli pass vaults list.
    args_overview: "[--profile NAME] [--output json] [--dry-run]"
    abortable: true
  - path: scripts/pass_items_list.py
    description: List Pass items (metadata; no password fields unless operator uses CLI directly).
    args_overview: "[--profile NAME] [--vault NAME] [--dry-run]"
    abortable: true
  - path: scripts/mail_list.py
    description: List mail messages in a folder via proton-cli mail messages list.
    args_overview: "[--profile NAME] [--folder INBOX] [--limit N] [--dry-run]"
    abortable: true
  - path: scripts/mail_read.py
    description: Read and decrypt one message by ID or search term.
    args_overview: "MESSAGE_ID [--profile NAME] [--dry-run]"
    abortable: true
  - path: scripts/drive_list.py
    description: List Drive folder contents via proton-cli drive items list.
    args_overview: "[--profile NAME] [--path /] [--dry-run]"
    abortable: true
  - path: scripts/calendar_events_list.py
    description: List calendar events via proton-cli calendar events list.
    args_overview: "[--profile NAME] [--calendar NAME] [--start YYYY-MM-DD] [--dry-run]"
    abortable: true
  - path: scripts/contacts_list.py
    description: List contacts via proton-cli contacts list.
    args_overview: "[--profile NAME] [--dry-run]"
    abortable: true
---

# proton-management

Python port of [roman-16/proton-cli](https://github.com/roman-16/proton-cli) integrated as a sevn skill.

**PR 5** adds **Calendar** (list calendars/events, get, delete) and **Contacts** (list, get, create, delete).

## Operator setup

1. Export credentials on the gateway host:

```bash
export PROTON_USER='you@proton.me'
export PROTON_PASSWORD='...'
# export PROTON_TOTP='123456'   # when 2FA enabled
```

2. Multi-account profiles use `PROTON_<PROFILE>_USER` / `PROTON_<PROFILE>_PASSWORD` or `--profile`.

3. Use `--dry-run` or `SEVN_PROTON_DRY_RUN=1` on skill scripts for plan-only JSON.

## CLI (also callable directly)

```bash
proton-cli mail messages list --folder inbox --output json
proton-cli mail messages search --keyword meeting --limit 10
proton-cli mail messages read MESSAGE_ID --output json
proton-cli mail messages send --to user@proton.me --subject "Hi" --body "Hello"
proton-cli mail labels list
proton-cli drive items list /
proton-cli drive folders create /Notes
proton-cli drive items upload ./doc.pdf /Documents
proton-cli drive trash list
proton-cli calendar calendars list
proton-cli calendar events list --calendar Work
proton-cli contacts list --output json
proton-cli pass vaults list --output json
proton-cli pass secrets get "API Key" --vault Personal
```

Sessions persist under `~/.config/proton-cli/sessions/<profile>.json`.

## Security

- Skill scripts never echo passwords in stdout.
- `mail_read.py` returns decrypted bodies — ask first before running on untrusted refs.
- `mail messages send` is operator ask-first (mutating).
- Configure `secrets_backend` type `proton_pass` with `cli_path: proton-cli` and optional `vault`.
