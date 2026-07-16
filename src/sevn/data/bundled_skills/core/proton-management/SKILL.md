---
name: proton-management
description: Proton suite CLI (Python port) — Pass vaults/items with E2EE; Mail/Drive/Calendar/Contacts planned.
version: "0.2.0"
see_also:
  - load_skill
  - run_skill_script
  - sevn-diagnostics
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
---

# proton-management

Python port of [roman-16/proton-cli](https://github.com/roman-16/proton-cli) integrated as a sevn skill.
**PR 2** adds Pass write paths (`items create/edit/delete`, `vaults create/rename/delete`) and
`pass secrets {get,set,delete}` for the sevn ``proton_pass`` secrets backend via ``cli_path: proton-cli``.

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
proton-cli --version
proton-cli pass vaults list --output json
proton-cli pass items list --vault Personal
proton-cli pass items create --name "API Key" --password '...' --vault Personal
proton-cli pass items edit "API Key" --password '...'
proton-cli pass secrets get "API Key" --vault Personal   # stdout password only
```

Sessions persist under `~/.config/proton-cli/sessions/<profile>.json`.

## Security

- Skill scripts never echo passwords in stdout.
- Decrypted secrets are only returned when the operator runs `pass items get` with explicit IDs.
- Configure `secrets_backend` type `proton_pass` with `cli_path: proton-cli` and optional `vault`.
