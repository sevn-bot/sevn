<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint channels` -->
# Channels — Telegram, Web UI bridge, and channel adapter patterns

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Telegram, Web UI bridge, and channel adapter patterns.

## Level 1 — Overview (non-technical)

**Channels** are how you talk to sevn.bot — Telegram, the browser Web UI (WebChat), and optional Discord/Slack adapters. Each channel normalises inbound messages into the gateway turn spine and delivers replies back through the same adapter.

Production paths today are **Telegram** and **WebChat**; Discord and Slack ship as narrower stubs (webhook-first / Events-API slices) until their specs mature.

## Level 2 — How it works (technical)

Implementation lives under [`src/sevn/channels/`](../../src/sevn/channels/). [`channel_boot.py`](../../src/sevn/gateway/channel_boot.py) loads configured adapters at gateway boot; [`channel_router.py`](../../src/sevn/gateway/channel_router.py) [`route_incoming`](../../src/sevn/gateway/channel_router.py#L1348) dispatches normalised events into the turn spine.

### Stub vs production adapters

| Channel | Adapter | Maturity | Notes |
| --- | --- | --- | --- |
| Telegram | [`TelegramAdapter`](../../src/sevn/channels/telegram.py#L106) | **Production** | Full inbound/outbound, menus, rich messages |
| Web UI | [`WebChatAdapter`](../../src/sevn/channels/webchat.py#L82) | **Production** | Browser bridge via [`webchat.py`](../../src/sevn/channels/webchat.py); config from [`webchat_config_from_workspace`](../../src/sevn/channels/webchat.py#L55) |
| Discord | [`DiscordChannelAdapter`](../../src/sevn/channels/discord.py#L26) | Stub | Webhook-first slice — [`from_gateway_boot`](../../src/sevn/channels/discord.py#L59) |
| Slack | [`SlackChannelAdapter`](../../src/sevn/channels/slack.py#L27) | Stub | Events-API slice — [`from_gateway_boot`](../../src/sevn/channels/slack.py#L60) |
| Other platforms | [`StubChannelAdapter`](../../src/sevn/channels/stub.py#L20) | Stub | Tier 2/3 placeholder via [`make_stub_adapter_class`](../../src/sevn/channels/stub.py#L127) |

Shared policy helpers ([`_common.py`](../../src/sevn/channels/_common.py)): [`platform_config_from_workspace`](../../src/sevn/channels/_common.py#L42), [`dm_policy_for_channel`](../../src/sevn/channels/_common.py#L117), [`session_reset_policy_for_channel`](../../src/sevn/channels/_common.py#L93).

Telegram callback overflow is handled in [`callback_overflow.py`](../../src/sevn/channels/callback_overflow.py) ([`resolve_dispatcher_overflow_callback_data`](../../src/sevn/channels/callback_overflow.py#L127)).

### Key modules

- [`telegram.py`](../../src/sevn/channels/telegram.py) — production Telegram adapter
- [`webchat.py`](../../src/sevn/channels/webchat.py) — Web UI bridge ([`WebChatAdapter`](../../src/sevn/channels/webchat.py#L82))
- [`discord.py`](../../src/sevn/channels/discord.py) / [`slack.py`](../../src/sevn/channels/slack.py) — stub adapters
- [`markdown_safe.py`](../../src/sevn/channels/markdown_safe.py) — Telegram MarkdownV2 escaping
- [`_common.py`](../../src/sevn/channels/_common.py) — shared channel policy helpers

Normative specs: [`18-channel-telegram.md`](../../about-sevn.bot/specs/18-channel-telegram.md), [`19-channel-webui.md`](../../about-sevn.bot/specs/19-channel-webui.md).


## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/channels`](../../src/sevn/channels/) (35 Python files). Normative design: `about-sevn.bot/specs/18-channel-telegram.md`, `about-sevn.bot/specs/19-channel-webui.md`.

### Module inventory

Messaging channel adapters.

Working with [`__init__.py`](../../src/sevn/channels/__init__.py): inspect the public entry points below.

Shared helpers for channel adapters.

Working with [`_common.py`](../../src/sevn/channels/_common.py): inspect the public entry points below.
Start with [`platform_config_from_workspace`](../../src/sevn/channels/_common.py#L42), then [`busy_input_mode_for_channel`](../../src/sevn/channels/_common.py#L72), [`session_reset_policy_for_channel`](../../src/sevn/channels/_common.py#L93), [`dm_policy_for_channel`](../../src/sevn/channels/_common.py#L117).

Telegram callback_data overflow via dispatcher_state (about-sevn.bot/specs/18-channel-telegram.md §3.1, §4.5).

Working with [`callback_overflow.py`](../../src/sevn/channels/callback_overflow.py): inspect the public entry points below.
Start with [`telegram_callback_data_utf8_len`](../../src/sevn/channels/callback_overflow.py#L33), then [`tokenize_inline_keyboard_callback_data`](../../src/sevn/channels/callback_overflow.py#L46), [`resolve_dispatcher_overflow_callback_data`](../../src/sevn/channels/callback_overflow.py#L127).

Discord channel adapter — webhook-first slice.

Working with [`discord.py`](../../src/sevn/channels/discord.py): inspect the public entry points below.
Start with [`DiscordChannelAdapter.from_gateway_boot`](../../src/sevn/channels/discord.py#L59), then [`DiscordChannelAdapter.name`](../../src/sevn/channels/discord.py#L76), [`DiscordChannelAdapter.config`](../../src/sevn/channels/discord.py#L89).

MarkdownV2 escape pipeline for outbound Telegram text (PROBLEMS.md §9).

Working with [`markdown_safe.py`](../../src/sevn/channels/markdown_safe.py): inspect the public entry points below.
Start with [`escape_markdown_v2`](../../src/sevn/channels/markdown_safe.py#L65), then [`escape_intent_footer`](../../src/sevn/channels/markdown_safe.py#L117).

Owner-facing Telegram copy for improve-job transitions (about-sevn.bot/specs/33-self-improvement.md §10.6).

Working with [`self_improve_copy.py`](../../src/sevn/channels/self_improve_copy.py): inspect the public entry points below.
Start with [`format_self_improve_job_telegram`](../../src/sevn/channels/self_improve_copy.py#L55).

Slack channel adapter — Events API slice.

Working with [`slack.py`](../../src/sevn/channels/slack.py): inspect the public entry points below.
Start with [`SlackChannelAdapter.from_gateway_boot`](../../src/sevn/channels/slack.py#L60), then [`SlackChannelAdapter.name`](../../src/sevn/channels/slack.py#L77), [`SlackChannelAdapter.config`](../../src/sevn/channels/slack.py#L90).

Stub channel adapter for Tier 2/3 platforms.

Working with [`stub.py`](../../src/sevn/channels/stub.py): inspect the public entry points below.
Start with [`StubChannelAdapter.name`](../../src/sevn/channels/stub.py#L52), then [`StubChannelAdapter.configured`](../../src/sevn/channels/stub.py#L65), [`StubChannelAdapter.config`](../../src/sevn/channels/stub.py#L78), [`make_stub_adapter_class`](../../src/sevn/channels/stub.py#L127).

Telegram channel adapter facade (about-sevn.bot/specs/18-channel-telegram.md).

Working with [`telegram.py`](../../src/sevn/channels/telegram.py): inspect the public entry points below.
Start with [`TelegramAdapter.rich_capability`](../../src/sevn/channels/telegram.py#L187), then [`TelegramAdapter.connected`](../../src/sevn/channels/telegram.py#L234), [`TelegramAdapter.name`](../../src/sevn/channels/telegram.py#L247).

Bot API HTTP transport for TelegramAdapter.

Working with [`telegram_api.py`](../../src/sevn/channels/telegram_api.py): inspect the public entry points below.
Start with [`TelegramApiMixin.answer_callback`](../../src/sevn/channels/telegram_api.py#L116), then [`TelegramApiMixin.send_chat_action`](../../src/sevn/channels/telegram_api.py#L135).

Bot API 10.1 rich-message capability probe (R1, D2).

Working with [`telegram_capabilities.py`](../../src/sevn/channels/telegram_capabilities.py): inspect the public entry points below.
Start with [`bot_api_error_description`](../../src/sevn/channels/telegram_capabilities.py#L46), then [`is_method_not_found_response`](../../src/sevn/channels/telegram_capabilities.py#L70), [`is_rich_payload_rejected`](../../src/sevn/channels/telegram_capabilities.py#L93), [`detect_rich_support`](../../src/sevn/channels/telegram_capabilities.py#L145).

Telegram adapter configuration, text utilities, and workspace wiring.

Working with [`telegram_config.py`](../../src/sevn/channels/telegram_config.py): inspect the public entry points below.
Start with [`build_reply_keyboard_markup`](../../src/sevn/channels/telegram_config.py#L95), then [`telegram_utf16_len`](../../src/sevn/channels/telegram_config.py#L145), [`chunk_text`](../../src/sevn/channels/telegram_config.py#L165), [`format_reply_quote`](../../src/sevn/channels/telegram_config.py#L296).

23 more Python files under [`src/sevn/channels`](../../src/sevn/channels/) — including `src/sevn/channels/telegram_file_links.py`, `src/sevn/channels/telegram_format.py`, `src/sevn/channels/telegram_inbound.py`, `src/sevn/channels/telegram_inline_send.py`.

### Extension and invariants

Follow [`18-channel-telegram.md`](../../about-sevn.bot/specs/18-channel-telegram.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/channels`](../../src/sevn/channels/), run `sevn readme update channels` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/18-channel-telegram.md](../../about-sevn.bot/specs/18-channel-telegram.md)
- [../../about-sevn.bot/specs/19-channel-webui.md](../../about-sevn.bot/specs/19-channel-webui.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/18-channel-telegram.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/channels/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
