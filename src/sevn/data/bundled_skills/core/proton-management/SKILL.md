---
name: proton-management
description: Proton suite CLI (Python port) — full deferred feature set.
version: "0.7.0"
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

**PR 7** completes deferred features: calendar create/RSVP, mail attachments, contact groups/pin-key, pure-Python drive keygen, and HV webview helper support.

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
proton-cli mail messages send --to user@proton.me --subject "Hi" --body "Hello" --attach ./doc.pdf
proton-cli mail attachments list MESSAGE_ID
proton-cli drive items list /
proton-cli drive folders create /Notes
proton-cli calendar events create --title "Sync" --start 2026-07-16T10:00 --calendar Work
proton-cli calendar events respond EVENT_TITLE --status accept
proton-cli contacts groups list
proton-cli contacts pin-key REF --key ./key.asc --email user@example.com
proton-cli status
proton-cli pass vaults list --output json
```

Sessions persist under `~/.config/proton-cli/sessions/<profile>.json`.

For CAPTCHA challenges during login:
- Set `PROTON_HV_TOKEN` after solving in the browser (optional `PROTON_HV_TYPE=captcha`), or
- Install/run `proton-cli-hv` (override with `PROTON_HV_HELPER`).

## Security

- Skill scripts never echo passwords in stdout.
- `mail_read.py` returns decrypted bodies — ask first before running on untrusted refs.
- `mail messages send` and `calendar events create` are operator ask-first (mutating).
- Configure `secrets_backend` type `proton_pass` with `cli_path: proton-cli` and optional `vault`.
