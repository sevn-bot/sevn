"""Typing-only host surface shared by Telegram adapter mixins (W5 / Final.2).

Module: sevn.channels.telegram_send_host
Depends: typing

Send/edit/rich/inline helpers and the Final.2 inbound/api/outbound/poll mixins call
adapter members (``_api``, ``_cfg``, …) defined on
:class:`~sevn.channels.telegram.TelegramAdapter`. This base declares that surface for
static typing only — the runtime body is empty, so the real implementations on
``TelegramAdapter`` are used via the MRO.

Exports:
    TelegramSendHost — ``TYPE_CHECKING``-only declarations of shared adapter state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio
    import sqlite3
    from collections import OrderedDict

    import httpx

    from sevn.agent.tracing.sink import TraceSink
    from sevn.channels.telegram_capabilities import RichCapability
    from sevn.channels.telegram_config import TelegramConfig

__all__: list[str] = ["TelegramSendHost"]


class TelegramSendHost:
    """Declare the :class:`TelegramAdapter` surface used by the send/edit mixins.

    Runtime body is intentionally empty; all members are declared under
    ``TYPE_CHECKING`` and implemented on ``TelegramAdapter`` (which inherits the
    mixins). Mixins inherit this base purely so static type-checking resolves the
    shared adapter members.
    """

    if TYPE_CHECKING:
        _cfg: TelegramConfig
        _conn: sqlite3.Connection | None
        _trace: TraceSink | None
        _external_client: httpx.AsyncClient | None
        _client_owned: bool
        _poll_task: asyncio.Task[None] | None
        _commands_task: asyncio.Task[None] | None
        _stop: asyncio.Event
        _router: Any
        _seen_updates: OrderedDict[int, None]
        _last_update_id: int
        _reply_keyboard_chats: set[int]
        _bot_user_id_warned: bool
        _poll_connected: bool
        _last_edit_text: OrderedDict[tuple[int, int], str]
        _dispatch_tasks: set[asyncio.Task[None]]
        _dispatch_gate: asyncio.Semaphore
        _pairing_store: Any | None
        _rich_capability: RichCapability | None

        async def _ensure_client(self) -> httpx.AsyncClient | None: ...

        async def _probe_rich_capability(self, *, force: bool = False) -> RichCapability: ...

        async def _populate_bot_user_id_from_getme(self) -> None: ...

        def _allowed_updates(self) -> list[str]: ...

        @property
        def name(self) -> str: ...

        @property
        def rich_capability(self) -> RichCapability: ...

        async def _api(self, method: str, body: dict[str, Any]) -> dict[str, Any]: ...

        async def _api_multipart(
            self,
            method: str,
            *,
            data: dict[str, Any],
            files: dict[str, tuple[str, bytes, str]],
        ) -> dict[str, Any]: ...

        def _outbound_use_rich(
            self,
            metadata: dict[str, Any],
            markdown: str,
            *,
            streaming_active: bool | None = None,
        ) -> bool: ...

        async def _send_rich_outbound(
            self,
            *,
            markdown: str,
            chat_id: int,
            thread_id: int | None,
            reply_to_int: int | None,
            disable_preview: bool,
            reply_markup_first: dict[str, Any] | None,
            edit_first: int | None,
            skip_text_edit: bool,
            streaming_active: bool,
            rich_draft: bool = False,
        ) -> list[str]: ...

        async def _send_text(
            self,
            *,
            chat_id: int,
            chunks: list[str],
            thread_id: int | None,
            reply_to_int: int | None,
            disable_preview: bool,
            reply_markup_first: dict[str, Any] | None,
            edit_first: int | None,
            skip_text_edit: bool = False,
        ) -> list[str]: ...

        async def edit_rich_message(
            self,
            *,
            chat_id: int,
            message_id: int,
            markdown: str,
            reply_markup: dict[str, Any] | None = None,
            message_thread_id: int | None = None,
            skip_text_edit: bool = False,
        ) -> bool: ...

        async def _edit_or_split_long_message(
            self,
            *,
            chat_id: int,
            message_id: int,
            text: str,
            reply_markup: dict[str, Any] | None = None,
            message_thread_id: int | None = None,
            send_followups: bool = True,
        ) -> tuple[bool, list[int]]: ...

        async def _edit_message_text_body(
            self,
            *,
            chat_id: int,
            message_id: int,
            text: str,
            reply_markup: dict[str, Any] | None = None,
            message_thread_id: int | None = None,
        ) -> bool: ...

        async def _emit_trace(
            self,
            *,
            kind: str,
            status: str,
            attrs: dict[str, object] | None = None,
        ) -> None: ...

        def _prepare_inline_reply_markup(
            self,
            reply_markup: dict[str, Any] | None,
            *,
            chat_id: int,
            message_thread_id: int | None,
        ) -> dict[str, Any] | None: ...

        def _remember_edit_text(self, key: tuple[int, int], text: str) -> None: ...

        async def edit_reply_markup(
            self,
            *,
            chat_id: int,
            message_id: int,
            reply_markup: dict[str, Any],
            message_thread_id: int | None = None,
        ) -> bool: ...

        def _log_send_api_error(self, method: str, res: dict[str, Any]) -> None: ...

        def _message_id_from_api_result(self, res: dict[str, Any]) -> str | None: ...

        async def _send_rendered_text(
            self,
            *,
            chat_id: int,
            rendered_text: str,
            thread_id: int | None,
            reply_to_int: int | None,
            disable_preview: bool,
            reply_markup_first: dict[str, Any] | None,
            edit_first: int | None,
            skip_text_edit: bool = False,
        ) -> list[str]: ...
