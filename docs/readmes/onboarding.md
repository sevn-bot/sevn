<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint onboarding` -->
# Onboarding — Operator setup: CLI, web wizard, Telegram flows, daemon install, and profiles

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Operator setup: CLI, web wizard, Telegram flows, daemon install, and profiles.

## Overview

**Onboarding** is the shared pipeline every setup path uses to produce a valid **`sevn.json`**, seed the workspace, store secrets outside the gateway process, and optionally install launchd/systemd units for the gateway and egress proxy. Re-running onboarding is safe: the wizard detects prior artifacts and offers reuse vs wipe.

Normative specs: [`22-onboarding`](../../about-sevn.bot/specs/22-onboarding.md), [`23-cli`](../../about-sevn.bot/specs/23-cli.md).

## First-time setup

From the repo checkout (development) or installed CLI (operator):

1. **`make setup`** — sync deps, install git guards, optional `.envrc`
2. **`sevn onboard`** — defaults to the **web wizard** when a graphical browser is detected (`create_onboarding_app`); use **`sevn onboard --cli`** for the Textual TUI
3. **`sevn doctor`** — health probes after promote

### Web wizard vs CLI

| Surface | Command | When |
| --- | --- | --- |
| Web (default) | `sevn onboard` or `sevn onboard --web` | macOS/Windows or Linux with `$DISPLAY` / `$WAYLAND_DISPLAY` |
| Textual TUI | `sevn onboard --cli` | Headless servers, SSH sessions (`SEVN_FORCE_HEADLESS=1`) |
| File-driven fast path | `sevn onboard --config path/to/sevn.json` | CI, scripted installs (`fast_onboard.py`) |

The wizard collects provider credentials, channel tokens (Telegram bot token, optional user API fields), workspace paths, and profile selection. **`--no-open`** prints the local URL without launching a browser.

### Telegram during onboarding

Telegram setup is part of the wizard/TUI credential step (`wizard_credentials.py`):

- Bot token → `channels.telegram.bot_token` (via secrets backend)
- Optional user API (`my.telegram.org`) for advanced flows
- Live validation probes run before **promote**

After promote, finish linking in Telegram per [`18-channel-telegram`](../../about-sevn.bot/specs/18-channel-telegram.md) (owner `/start`, menu surfaces).

### Profiles (`src/sevn/data/onboarding_profiles/`)

Presets ship as JSON fragments merged by `load_profile_fragment`:

| Profile id | Intent |
| --- | --- |
| `full_free` | Balanced defaults for demos |
| `good_value_osx` / `good_value_docker` | MiniMax M2.7 daily driver |
| `best_agent` | Quality-first caps + browser/graphify |
| `fastest` | Latency trim (LCM off) |
| `ollama_local` | Local triager via Ollama |
| `docker_sandbox` | Docker-backed tool isolation |

Select with `sevn onboard --profile good_value_osx` (not a file path — use `--config` for JSON/YAML files).

### Daemon install

By default **`--install-daemon`** installs gateway + proxy launchd/systemd units after promote (`maybe_install_daemon_after_promote`). Skip with `--no-install-daemon` for manual `sevn gateway start`. Unit paths live under operator home; `sevn doctor` reports missing units.

## Re-running safely

`sevn onboard` detects prior drafts and workspace artifacts (`install_discovery.workspace_has_artifacts`). You can:

- **Reuse** — prefill from existing `sevn.json` / draft store
- **Wipe + reseed** — fresh workspace layout (explicit confirmation)
- **Rotate secrets** — wizard credential store without full wipe

`promote_draft` (`onboarding/promote.py`) merges validated JSON → bound `sevn.json`; always run **`sevn config validate`** afterward.

## Daily operations

- **`sevn gateway start`** / daemon — run the control plane
- **`sevn config validate`** — after manual `sevn.json` edits
- **`sevn config show <section>`** — inspect a subtree
- **`sevn export-secrets`** / **`sevn onboard fast`** — bundle migration path

## References

- [Spec 22 — onboarding](../../about-sevn.bot/specs/22-onboarding.md)
- [Spec 23 — CLI](../../about-sevn.bot/specs/23-cli.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/22-onboarding.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/onboarding/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
