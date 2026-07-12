"""Rich outbound orchestration facade for :class:`TelegramAdapter` (W5).

Module: sevn.channels.telegram_rich_outbound
Depends: sevn.channels.telegram_rich_send

W5 extraction lives in ``telegram_rich_send`` (``TelegramRichSendMixin``:
``send_rich_message``, ``edit_rich_message``, ``send_rich_message_draft``,
``_send_rich_outbound``). This module is the stable import surface pinned by
``test_smoke_post_split_telegram_rich_outbound_import``.

Exports:
    TelegramRichSendMixin — rich send/edit/draft mixin mixed into the adapter.

Examples:
    >>> from sevn.channels.telegram_rich_outbound import TelegramRichSendMixin
    >>> TelegramRichSendMixin.__name__
    'TelegramRichSendMixin'
"""

from __future__ import annotations

from sevn.channels.telegram_rich_send import TelegramRichSendMixin as TelegramRichSendMixin
