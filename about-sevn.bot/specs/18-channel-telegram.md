---
id: spec-18-channel-telegram
kind: spec
title: Channel — Telegram — Spec
status: draft
owner: Alex
summary: 'Deliver the primary daily-driver channel for personal messaging: a ChannelAdapter
  implementation that normalises Telegram Updates into spec-17-gateway IncomingMessage
  / OutgoingMessage and implements '
last_updated: '2026-07-12'
fingerprint: sha256:374cf638eff859b6e68373302bb3734271c26da2b07567d8787c6a87db8fe59b
related: []
sources:
- src/sevn/channels/**
parent_prd: prd-01-conversational-experience
depends_on:
- spec-02-config-and-workspace
- spec-05-llm-transports
- spec-06-secrets
- spec-07-egress-proxy
- spec-09-security-scanner
- spec-17-gateway
build_phase: null
interfaces:
- name: PlatformChannelConfig
  file: src/sevn/channels/_common.py
  symbol: PlatformChannelConfig
- name: busy_input_mode_for_channel
  file: src/sevn/channels/_common.py
  symbol: busy_input_mode_for_channel
- name: channel_blob
  file: src/sevn/channels/_common.py
  symbol: channel_blob
- name: dm_policy_for_channel
  file: src/sevn/channels/_common.py
  symbol: dm_policy_for_channel
- name: platform_config_from_workspace
  file: src/sevn/channels/_common.py
  symbol: platform_config_from_workspace
- name: session_reset_policy_for_channel
  file: src/sevn/channels/_common.py
  symbol: session_reset_policy_for_channel
- name: resolve_dispatcher_overflow_callback_data
  file: src/sevn/channels/callback_overflow.py
  symbol: resolve_dispatcher_overflow_callback_data
- name: telegram_callback_data_utf8_len
  file: src/sevn/channels/callback_overflow.py
  symbol: telegram_callback_data_utf8_len
- name: tokenize_inline_keyboard_callback_data
  file: src/sevn/channels/callback_overflow.py
  symbol: tokenize_inline_keyboard_callback_data
- name: DiscordChannelAdapter
  file: src/sevn/channels/discord.py
  symbol: DiscordChannelAdapter
- name: escape_intent_footer
  file: src/sevn/channels/markdown_safe.py
  symbol: escape_intent_footer
- name: escape_markdown_v2
  file: src/sevn/channels/markdown_safe.py
  symbol: escape_markdown_v2
- name: SelfImproveTelegramNotification
  file: src/sevn/channels/self_improve_copy.py
  symbol: SelfImproveTelegramNotification
- name: format_self_improve_job_telegram
  file: src/sevn/channels/self_improve_copy.py
  symbol: format_self_improve_job_telegram
- name: SlackChannelAdapter
  file: src/sevn/channels/slack.py
  symbol: SlackChannelAdapter
- name: StubChannelAdapter
  file: src/sevn/channels/stub.py
  symbol: StubChannelAdapter
- name: make_stub_adapter_class
  file: src/sevn/channels/stub.py
  symbol: make_stub_adapter_class
- name: TelegramAdapter
  file: src/sevn/channels/telegram.py
  symbol: TelegramAdapter
- name: TelegramApiMixin
  file: src/sevn/channels/telegram_api.py
  symbol: TelegramApiMixin
- name: RichCapability
  file: src/sevn/channels/telegram_capabilities.py
  symbol: RichCapability
- name: bot_api_error_description
  file: src/sevn/channels/telegram_capabilities.py
  symbol: bot_api_error_description
- name: detect_rich_support
  file: src/sevn/channels/telegram_capabilities.py
  symbol: detect_rich_support
- name: is_method_not_found_response
  file: src/sevn/channels/telegram_capabilities.py
  symbol: is_method_not_found_response
- name: is_rich_payload_rejected
  file: src/sevn/channels/telegram_capabilities.py
  symbol: is_rich_payload_rejected
- name: DMPolicy
  file: src/sevn/channels/telegram_config.py
  symbol: DMPolicy
- name: TelegramConfig
  file: src/sevn/channels/telegram_config.py
  symbol: TelegramConfig
- name: TelegramSendError
  file: src/sevn/channels/telegram_config.py
  symbol: TelegramSendError
- name: TopicConfig
  file: src/sevn/channels/telegram_config.py
  symbol: TopicConfig
- name: build_reply_keyboard_markup
  file: src/sevn/channels/telegram_config.py
  symbol: build_reply_keyboard_markup
- name: chunk_text
  file: src/sevn/channels/telegram_config.py
  symbol: chunk_text
- name: format_reply_quote
  file: src/sevn/channels/telegram_config.py
  symbol: format_reply_quote
- name: telegram_config_from_workspace
  file: src/sevn/channels/telegram_config.py
  symbol: telegram_config_from_workspace
- name: telegram_utf16_len
  file: src/sevn/channels/telegram_config.py
  symbol: telegram_utf16_len
- name: build_file_link_keyboard
  file: src/sevn/channels/telegram_file_links.py
  symbol: build_file_link_keyboard
- name: extract_file_link_paths
  file: src/sevn/channels/telegram_file_links.py
  symbol: extract_file_link_paths
- name: parse_file_link_callback
  file: src/sevn/channels/telegram_file_links.py
  symbol: parse_file_link_callback
- name: strip_file_link_markers
  file: src/sevn/channels/telegram_file_links.py
  symbol: strip_file_link_markers
- name: markdown_tables_to_pre
  file: src/sevn/channels/telegram_format.py
  symbol: markdown_tables_to_pre
- name: to_telegram
  file: src/sevn/channels/telegram_format.py
  symbol: to_telegram
- name: TelegramInboundMixin
  file: src/sevn/channels/telegram_inbound.py
  symbol: TelegramInboundMixin
- name: TelegramInlineSendMixin
  file: src/sevn/channels/telegram_inline_send.py
  symbol: TelegramInlineSendMixin
- name: MarkdownRegionDict
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: MarkdownRegionDict
- name: find_markdown_regions
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: find_markdown_regions
- name: parse_markdown_table
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: parse_markdown_table
- name: parse_table_alignments
  file: src/sevn/channels/telegram_markdown_regions.py
  symbol: parse_table_alignments
- name: TelegramOutboundMixin
  file: src/sevn/channels/telegram_outbound.py
  symbol: TelegramOutboundMixin
- name: TelegramPollMixin
  file: src/sevn/channels/telegram_poll.py
  symbol: TelegramPollMixin
- name: build_input_rich_message_markdown
  file: src/sevn/channels/telegram_rich.py
  symbol: build_input_rich_message_markdown
- name: render_markdown_to_rich_message
  file: src/sevn/channels/telegram_rich.py
  symbol: render_markdown_to_rich_message
- name: rich_module_ready
  file: src/sevn/channels/telegram_rich.py
  symbol: rich_module_ready
- name: build_anchor
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_anchor
- name: build_animation
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_animation
- name: build_audio
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_audio
- name: build_block_quotation
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_block_quotation
- name: build_caption
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_caption
- name: build_collage
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_collage
- name: build_details
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_details
- name: build_divider
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_divider
- name: build_footer
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_footer
- name: build_input_rich_message
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_input_rich_message
- name: build_list
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_list
- name: build_list_item
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_list_item
- name: build_math
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_math
- name: build_paragraph
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_paragraph
- name: build_photo
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_photo
- name: build_preformatted
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_preformatted
- name: build_pull_quotation
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_pull_quotation
- name: build_section_heading
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_section_heading
- name: build_slideshow
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_slideshow
- name: build_table
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_table
- name: build_table_cell
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_table_cell
- name: build_thinking
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_thinking
- name: build_video
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_video
- name: build_voice_note
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: build_voice_note
- name: parse_media_directive_attrs
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: parse_media_directive_attrs
- name: resolve_media_source
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: resolve_media_source
- name: rich_blocks_module_ready
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: rich_blocks_module_ready
- name: rich_text
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: rich_text
- name: rich_text_plain
  file: src/sevn/channels/telegram_rich_blocks.py
  symbol: rich_text_plain
- name: RichFallbackReason
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: RichFallbackReason
- name: is_reply_rich_worthy
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: is_reply_rich_worthy
- name: resolve_rich_config
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: resolve_rich_config
- name: send_with_rich_fallback
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: send_with_rich_fallback
- name: should_use_rich
  file: src/sevn/channels/telegram_rich_fallback.py
  symbol: should_use_rich
- name: ast_to_input_rich_message
  file: src/sevn/channels/telegram_rich_map.py
  symbol: ast_to_input_rich_message
- name: inline_to_rich_json
  file: src/sevn/channels/telegram_rich_map.py
  symbol: inline_to_rich_json
- name: inline_to_rich_text
  file: src/sevn/channels/telegram_rich_map.py
  symbol: inline_to_rich_text
- name: AstAnchor
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstAnchor
- name: AstBlockquote
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstBlockquote
- name: AstCollage
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstCollage
- name: AstDetails
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstDetails
- name: AstDivider
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstDivider
- name: AstFooter
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstFooter
- name: AstHeading
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstHeading
- name: AstInlineCode
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineCode
- name: AstInlineLink
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineLink
- name: AstInlineMath
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineMath
- name: AstInlineMention
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineMention
- name: AstInlineStyled
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineStyled
- name: AstInlineText
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstInlineText
- name: AstList
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstList
- name: AstListItem
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstListItem
- name: AstMathBlock
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstMathBlock
- name: AstMedia
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstMedia
- name: AstParagraph
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstParagraph
- name: AstPreformatted
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstPreformatted
- name: AstPullQuote
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstPullQuote
- name: AstSlideshow
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstSlideshow
- name: AstTable
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstTable
- name: AstThinking
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: AstThinking
- name: markdown_to_ast
  file: src/sevn/channels/telegram_rich_parse.py
  symbol: markdown_to_ast
- name: TelegramRichSendMixin
  file: src/sevn/channels/telegram_rich_send.py
  symbol: TelegramRichSendMixin
- name: serialize_input_rich_message
  file: src/sevn/channels/telegram_rich_validate.py
  symbol: serialize_input_rich_message
- name: validate_rich_message_shape
  file: src/sevn/channels/telegram_rich_validate.py
  symbol: validate_rich_message_shape
- name: TelegramTextSendMixin
  file: src/sevn/channels/telegram_send_edit.py
  symbol: TelegramTextSendMixin
- name: build_text_api_body
  file: src/sevn/channels/telegram_send_edit.py
  symbol: build_text_api_body
- name: is_entity_parse_error
  file: src/sevn/channels/telegram_send_edit.py
  symbol: is_entity_parse_error
- name: is_message_not_modified
  file: src/sevn/channels/telegram_send_edit.py
  symbol: is_message_not_modified
- name: is_message_too_long_desc
  file: src/sevn/channels/telegram_send_edit.py
  symbol: is_message_too_long_desc
- name: TelegramSendHost
  file: src/sevn/channels/telegram_send_host.py
  symbol: TelegramSendHost
- name: add_custom_button
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: add_custom_button
- name: build_custom_inline_keyboard
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: build_custom_inline_keyboard
- name: buttons_store_path
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: buttons_store_path
- name: clear_custom_buttons
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: clear_custom_buttons
- name: list_custom_buttons
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: list_custom_buttons
- name: remove_custom_button
  file: src/sevn/channels/telegram_skill/buttons.py
  symbol: remove_custom_button
- name: create_forum_topic
  file: src/sevn/channels/telegram_skill/forum.py
  symbol: create_forum_topic
- name: find_group_by_name
  file: src/sevn/channels/telegram_skill/forum.py
  symbol: find_group_by_name
- name: TelegramSkillHooks
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: TelegramSkillHooks
- name: bot_api_call_from_adapter
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: bot_api_call_from_adapter
- name: bot_api_call_from_token
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: bot_api_call_from_token
- name: resolve_telegram_skill_hooks
  file: src/sevn/channels/telegram_skill/hooks.py
  symbol: resolve_telegram_skill_hooks
- name: WebChatAdapter
  file: src/sevn/channels/webchat.py
  symbol: WebChatAdapter
- name: WebChatConfig
  file: src/sevn/channels/webchat.py
  symbol: WebChatConfig
- name: webchat_config_from_workspace
  file: src/sevn/channels/webchat.py
  symbol: webchat_config_from_workspace
specs: []
personas: []
prd_profile: null
---


## Purpose

Deliver the primary daily-driver channel for personal messaging: a ChannelAdapter implementation that normalises Telegram Updates into spec-17-gateway IncomingMessage / OutgoingMessage and implements

Primary code trees: [`src/sevn/channels`](src/sevn/channels/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`PlatformChannelConfig`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`busy_input_mode_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`channel_blob`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`dm_policy_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`platform_config_from_workspace`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`session_reset_policy_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`resolve_dispatcher_overflow_callback_data`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`telegram_callback_data_utf8_len`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`tokenize_inline_keyboard_callback_data`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`DiscordChannelAdapter`](src/sevn/channels/discord.py) — `src/sevn/channels/discord.py`
- [`escape_intent_footer`](src/sevn/channels/markdown_safe.py) — `src/sevn/channels/markdown_safe.py`
- [`escape_markdown_v2`](src/sevn/channels/markdown_safe.py) — `src/sevn/channels/markdown_safe.py`
- _…and 123 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`PlatformChannelConfig`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`busy_input_mode_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`channel_blob`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`dm_policy_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`platform_config_from_workspace`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`session_reset_policy_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`resolve_dispatcher_overflow_callback_data`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`telegram_callback_data_utf8_len`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`tokenize_inline_keyboard_callback_data`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`DiscordChannelAdapter`](src/sevn/channels/discord.py) — `src/sevn/channels/discord.py`
- [`escape_intent_footer`](src/sevn/channels/markdown_safe.py) — `src/sevn/channels/markdown_safe.py`
- [`escape_markdown_v2`](src/sevn/channels/markdown_safe.py) — `src/sevn/channels/markdown_safe.py`
- _…and 123 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/channels`](src/sevn/channels/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/channels`](src/sevn/channels/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Amendments (spec-36-sub-agents)

Telegram `/config` gains **Sub-agents** section: limits, live L1/L2 counts, queue mode
incl. `multi`, and **Running** kill submenu (owner-only). `busy_input_mode` may be
`multi`. Documented in `about-sevn.bot/Telegram Menu.html` (D13).

## Implemented by

- [`PlatformChannelConfig`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`busy_input_mode_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`channel_blob`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`dm_policy_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`platform_config_from_workspace`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`session_reset_policy_for_channel`](src/sevn/channels/_common.py) — `src/sevn/channels/_common.py`
- [`resolve_dispatcher_overflow_callback_data`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`telegram_callback_data_utf8_len`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`tokenize_inline_keyboard_callback_data`](src/sevn/channels/callback_overflow.py) — `src/sevn/channels/callback_overflow.py`
- [`DiscordChannelAdapter`](src/sevn/channels/discord.py) — `src/sevn/channels/discord.py`
- [`escape_intent_footer`](src/sevn/channels/markdown_safe.py) — `src/sevn/channels/markdown_safe.py`
- [`escape_markdown_v2`](src/sevn/channels/markdown_safe.py) — `src/sevn/channels/markdown_safe.py`
- [`SelfImproveTelegramNotification`](src/sevn/channels/self_improve_copy.py) — `src/sevn/channels/self_improve_copy.py`
- [`format_self_improve_job_telegram`](src/sevn/channels/self_improve_copy.py) — `src/sevn/channels/self_improve_copy.py`
- [`SlackChannelAdapter`](src/sevn/channels/slack.py) — `src/sevn/channels/slack.py`
- [`StubChannelAdapter`](src/sevn/channels/stub.py) — `src/sevn/channels/stub.py`
- [`make_stub_adapter_class`](src/sevn/channels/stub.py) — `src/sevn/channels/stub.py`
- [`TelegramAdapter`](src/sevn/channels/telegram.py) — `src/sevn/channels/telegram.py`
- [`TelegramApiMixin`](src/sevn/channels/telegram_api.py) — `src/sevn/channels/telegram_api.py`
- [`RichCapability`](src/sevn/channels/telegram_capabilities.py) — `src/sevn/channels/telegram_capabilities.py`
- _…and 115 more in frontmatter `interfaces:`._

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
