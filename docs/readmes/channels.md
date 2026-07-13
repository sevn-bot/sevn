<!-- generated: do not edit by hand; run `sevn readme update channels` -->
# Channels — Telegram, Web UI bridge, voice hooks, and channel adapter patterns

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Telegram, Web UI bridge, voice hooks, and channel adapter patterns.

## Level 1 — Overview (non-technical)

**Channels** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Telegram, Web UI bridge, voice hooks, and channel adapter patterns.

In everyday use, channels helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/channels/`. The package contains 35 Python module(s); primary entry points include `src/sevn/channels/__init__.py`, `src/sevn/channels/_common.py`, `src/sevn/channels/callback_overflow.py`, `src/sevn/channels/discord.py`, `src/sevn/channels/markdown_safe.py`, `src/sevn/channels/self_improve_copy.py`, and 29 more.

### Data and control flow

Channels sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/18-channel-telegram.md`, `about-sevn.bot/specs/19-channel-webui.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/channels/_common.py` — `platform_config_from_workspace`, `busy_input_mode_for_channel`, `session_reset_policy_for_channel`, `dm_policy_for_channel`
- `src/sevn/channels/callback_overflow.py` — `telegram_callback_data_utf8_len`, `tokenize_inline_keyboard_callback_data`, `resolve_dispatcher_overflow_callback_data`
- `src/sevn/channels/discord.py` — `DiscordChannelAdapter.from_gateway_boot`, `DiscordChannelAdapter.name`, `DiscordChannelAdapter.config`, `DiscordChannelAdapter (+2 methods)`
- `src/sevn/channels/markdown_safe.py` — `escape_markdown_v2`, `escape_intent_footer`
- `src/sevn/channels/self_improve_copy.py` — `format_self_improve_job_telegram`

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/channels/` (35 Python files). Normative design: `about-sevn.bot/specs/18-channel-telegram.md`, `about-sevn.bot/specs/19-channel-webui.md`.

### Module inventory

- `src/sevn/channels/__init__.py` — Messaging channel adapters.
- `src/sevn/channels/_common.py` — Shared helpers for channel adapters.
- `src/sevn/channels/callback_overflow.py` — Telegram ''callback_data'' overflow via ''dispatcher_state'' ('about-sevn.bot/specs/18-channel-telegram.md' §3.1, §4.5).
- `src/sevn/channels/discord.py` — Discord channel adapter — webhook-first slice.
- `src/sevn/channels/markdown_safe.py` — MarkdownV2 escape pipeline for outbound Telegram text ('PROBLEMS.md' §9).
- `src/sevn/channels/self_improve_copy.py` — Owner-facing Telegram copy for improve-job transitions ('about-sevn.bot/specs/33-self-improvement.md' §10.6).
- `src/sevn/channels/slack.py` — Slack channel adapter — Events API slice.
- `src/sevn/channels/stub.py` — Stub channel adapter for Tier 2/3 platforms.
- `src/sevn/channels/telegram.py` — Telegram channel adapter facade ('about-sevn.bot/specs/18-channel-telegram.md').
- `src/sevn/channels/telegram_api.py` — Bot API HTTP transport for TelegramAdapter.
- `src/sevn/channels/telegram_capabilities.py` — Bot API 10.1 rich-message capability probe (R1, D2).
- `src/sevn/channels/telegram_config.py` — Telegram adapter configuration, text utilities, and workspace wiring.
- … and 23 more Python modules

### Package init (`src/sevn/channels/__init__.py`)

See `src/sevn/channels/__init__.py` for implementation details.

###  Common (`src/sevn/channels/_common.py`)

Public entry points:
- `platform_config_from_workspace`
- `busy_input_mode_for_channel`
- `session_reset_policy_for_channel`
- `dm_policy_for_channel`
- `channel_blob`

### Callback Overflow (`src/sevn/channels/callback_overflow.py`)

Public entry points:
- `telegram_callback_data_utf8_len`
- `tokenize_inline_keyboard_callback_data`
- `resolve_dispatcher_overflow_callback_data`

### Discord (`src/sevn/channels/discord.py`)

Public entry points:
- `DiscordChannelAdapter.from_gateway_boot`
- `DiscordChannelAdapter.name`
- `DiscordChannelAdapter.config`
- `DiscordChannelAdapter (+2 methods)`

### Markdown Safe (`src/sevn/channels/markdown_safe.py`)

Public entry points:
- `escape_markdown_v2`
- `escape_intent_footer`

### Self Improve Copy (`src/sevn/channels/self_improve_copy.py`)

Public entry points:
- `format_self_improve_job_telegram`

### Slack (`src/sevn/channels/slack.py`)

Public entry points:
- `SlackChannelAdapter.from_gateway_boot`
- `SlackChannelAdapter.name`
- `SlackChannelAdapter.config`
- `SlackChannelAdapter (+2 methods)`

### Stub (`src/sevn/channels/stub.py`)

Public entry points:
- `StubChannelAdapter.name`
- `StubChannelAdapter.configured`
- `StubChannelAdapter.config`
- `StubChannelAdapter (+2 methods)`
- `make_stub_adapter_class`

### Telegram (`src/sevn/channels/telegram.py`)

Public entry points:
- `TelegramAdapter.rich_capability`
- `TelegramAdapter.connected`
- `TelegramAdapter.name`
- `TelegramAdapter (+1 methods)`

### Telegram Api (`src/sevn/channels/telegram_api.py`)

Public entry points:
- `TelegramApiMixin.answer_callback`
- `TelegramApiMixin.send_chat_action`

### Telegram Capabilities (`src/sevn/channels/telegram_capabilities.py`)

See `src/sevn/channels/telegram_capabilities.py` for implementation details.

### Telegram Config (`src/sevn/channels/telegram_config.py`)

See `src/sevn/channels/telegram_config.py` for implementation details.

### Additional modules

23 more Python files under `src/sevn/channels/` — including `src/sevn/channels/telegram_file_links.py`, `src/sevn/channels/telegram_format.py`, `src/sevn/channels/telegram_inbound.py`, `src/sevn/channels/telegram_inline_send.py`.

### Extension and invariants

Follow `about-sevn.bot/specs/18-channel-telegram.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/channels/`, run `sevn readme update channels` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/18-channel-telegram.md](../../about-sevn.bot/specs/18-channel-telegram.md)
- [../../about-sevn.bot/specs/19-channel-webui.md](../../about-sevn.bot/specs/19-channel-webui.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/18-channel-telegram.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/channels/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
