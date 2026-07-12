"""Bot API 10.1 rich send/edit/draft helpers for :class:`TelegramAdapter` (W4).

Module: sevn.channels.telegram_rich_send
Depends: loguru, sevn.channels.telegram_rich, sevn.logging.structured

Exports:
    TelegramRichSendMixin — rich outbound orchestration mixed into the adapter.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from sevn.channels.telegram_rich import (
    build_input_rich_message_markdown,
    send_with_rich_fallback,
    should_use_rich,
)
from sevn.channels.telegram_send_edit import is_message_not_modified, is_message_too_long_desc
from sevn.channels.telegram_send_host import TelegramSendHost
from sevn.logging.structured import debug_event, preview

TELEGRAM_USE_RICH_KEY = "telegram_use_rich"
TELEGRAM_STREAMING_ACTIVE_KEY = "telegram_streaming_active"
TELEGRAM_RICH_DRAFT_KEY = "telegram_rich_draft"


class TelegramRichSendMixin(TelegramSendHost):
    """Rich-message send/edit/draft helpers for :class:`TelegramAdapter`."""

    def _outbound_use_rich(
        self,
        metadata: dict[str, Any],
        markdown: str,
        *,
        streaming_active: bool | None = None,
    ) -> bool:
        """Resolve whether this outbound should attempt Bot API 10.1 rich send (R4.4).

        Args:
            metadata (dict[str, Any]): Outbound routing metadata (may carry
                ``telegram_use_rich`` from :meth:`ChannelRouter.route_outgoing`).
            markdown (str): Agent Markdown body.
            streaming_active (bool | None, optional): Override streaming flag.
                Defaults to metadata ``telegram_streaming_active``.

        Returns:
            bool: ``True`` when the rich path should be attempted.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TelegramRichSendMixin._outbound_use_rich)
            True
        """
        hint = metadata.get(TELEGRAM_USE_RICH_KEY)
        if hint is False:
            return False
        stream = (
            streaming_active
            if streaming_active is not None
            else bool(metadata.get(TELEGRAM_STREAMING_ACTIVE_KEY))
        )
        if hint is True:
            return should_use_rich(
                markdown,
                self.rich_capability,
                self._cfg.rich,
                streaming_active=stream,
            )
        return should_use_rich(
            markdown,
            self.rich_capability,
            self._cfg.rich,
            streaming_active=stream,
        )

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        markdown: str,
        thread_id: int | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
        disable_preview: bool = False,
    ) -> str:
        """Send one message via ``sendRichMessage`` (Bot API 10.1, R4.1).

        Args:
            chat_id (int): Destination chat id.
            markdown (str): Agent Markdown rendered to ``InputRichMessage``.
            thread_id (int | None): Forum ``message_thread_id`` when set.
            reply_to_message_id (int | None): Optional reply target.
            reply_markup (dict[str, Any] | None): Inline or reply keyboard markup.
            disable_preview (bool): ``disable_web_page_preview`` flag.

        Returns:
            str: Telegram ``message_id`` string.

        Raises:
            ValueError: When rendering or the Bot API call fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramRichSendMixin.send_rich_message)
            True
        """
        rich_message = build_input_rich_message_markdown(markdown)
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "rich_message": rich_message,
            "disable_web_page_preview": disable_preview,
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
        markup = self._prepare_inline_reply_markup(
            reply_markup,
            chat_id=chat_id,
            message_thread_id=thread_id,
        )
        if markup is not None:
            body["reply_markup"] = markup
        res = await self._api("sendRichMessage", body)
        if not res.get("ok"):
            desc = str(res.get("description") or "sendRichMessage failed")
            self._log_send_api_error("sendRichMessage", res)
            raise ValueError(desc)
        mid = self._message_id_from_api_result(res)
        if mid is None:
            raise ValueError("sendRichMessage missing message_id")
        logger.info(
            "telegram_send_api_ok method={} chat_id={} message_id={}",
            "sendRichMessage",
            chat_id,
            mid,
        )
        return mid

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        markdown: str,
        draft_id: int,
        thread_id: int | None = None,
    ) -> bool:
        """Stream an ephemeral partial rich message via ``sendRichMessageDraft``.

        Per Bot API 10.1 the draft is a temporary ~30-second live preview: it takes
        a non-zero ``draft_id``, returns ``True`` (**no** ``message_id``), and does
        not persist — the final message must be committed with ``sendRichMessage``.
        This makes it unsuitable for sevn's placeholder→``editMessageText`` streaming
        model, so it is **not** on the outbound hot path (see
        :meth:`_send_rich_outbound`, which sends a persistent rich placeholder
        instead). Retained for API-correct direct use.

        Args:
            chat_id (int): Destination private chat id.
            markdown (str): Partial draft body.
            draft_id (int): Non-zero draft identifier; edits to the same id animate.
            thread_id (int | None): Forum ``message_thread_id`` when set.

        Returns:
            bool: ``True`` when the Bot API accepts the draft.

        Raises:
            ValueError: When ``draft_id`` is zero, rendering, or the API call fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramRichSendMixin.send_rich_message_draft)
            True
        """
        if draft_id == 0:
            raise ValueError("sendRichMessageDraft draft_id must be non-zero")
        rich_message = build_input_rich_message_markdown(markdown)
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "draft_id": draft_id,
            "rich_message": rich_message,
        }
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        res = await self._api("sendRichMessageDraft", body)
        if not res.get("ok"):
            desc = str(res.get("description") or "sendRichMessageDraft failed")
            self._log_send_api_error("sendRichMessageDraft", res)
            raise ValueError(desc)
        logger.info(
            "telegram_send_api_ok method={} chat_id={} draft_id={}",
            "sendRichMessageDraft",
            chat_id,
            draft_id,
        )
        return True

    async def edit_rich_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        markdown: str,
        reply_markup: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
        skip_text_edit: bool = False,
    ) -> bool:
        """Edit a message via ``editMessageText(rich_message=…)`` (R4.2, D5).

        Reuses no-op-edit and markup-only attach handling shared with plain edits.

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Target Telegram message id.
            markdown (str): Replacement Markdown rendered to ``InputRichMessage``.
            reply_markup (dict[str, Any] | None): Optional inline keyboard.
            message_thread_id (int | None): Forum ``message_thread_id`` when set.
            skip_text_edit (bool): When ``True``, skip the rich body edit and attach
                markup only (streaming finalize no-op).

        Returns:
            bool: ``True`` when the Bot API reports success.

        Raises:
            ValueError: When rendering fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramRichSendMixin.edit_rich_message)
            True
        """
        edit_key = (chat_id, int(message_id))
        markup = self._prepare_inline_reply_markup(
            reply_markup,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
        )
        if skip_text_edit:
            if markup is not None:
                return await self.edit_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                    message_thread_id=message_thread_id,
                )
            return True
        if markup is None and self._last_edit_text.get(edit_key) == markdown:
            return True
        rich_message = build_input_rich_message_markdown(markdown)
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "rich_message": rich_message,
        }
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        if markup is not None:
            body["reply_markup"] = markup
        debug_event(
            "telegram.stream_edit",
            chat_id=chat_id,
            message_id=int(message_id),
            text_len=len(markdown),
            preview=preview(markdown),
            parse_mode="rich_message",
        )
        res = await self._api("editMessageText", body)
        if res.get("ok"):
            self._remember_edit_text(edit_key, markdown)
            return True
        desc = str(res.get("description") or "")
        debug_event(
            "telegram.stream_edit_failed",
            chat_id=chat_id,
            message_id=int(message_id),
            text_len=len(markdown),
            preview=preview(markdown),
            parse_mode="rich_message",
            desc=desc,
        )
        if is_message_not_modified(desc):
            self._remember_edit_text(edit_key, markdown)
            if markup is not None:
                return await self.edit_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                    message_thread_id=message_thread_id,
                )
            return True
        logger.info(
            "telegram_edit_message_text_failed chat_id={} message_id={} desc={}",
            chat_id,
            message_id,
            desc,
        )
        if is_message_too_long_desc(desc):
            return False
        return False

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
    ) -> list[str]:
        """Rich send/edit/draft wrapper with guaranteed legacy degrade (D4, R4.1-R4.3).

        Args:
            markdown (str): Agent Markdown body.
            chat_id (int): Destination chat id.
            thread_id (int | None): Forum thread id when set.
            reply_to_int (int | None): Reply target for fresh sends.
            disable_preview (bool): Link-preview disable flag.
            reply_markup_first (dict[str, Any] | None): Keyboard on first/last chunk.
            edit_first (int | None): Edit target message id when set.
            skip_text_edit (bool): Skip redundant rich edit on finalize.
            streaming_active (bool): Streaming flag for ``auto`` mode.
            rich_draft (bool): Use ``sendRichMessageDraft`` for placeholders.

        Returns:
            list[str]: Platform message ids.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramRichSendMixin._send_rich_outbound)
            True
        """

        async def legacy_send(converted: str) -> list[str]:
            return await self._send_rendered_text(
                chat_id=chat_id,
                rendered_text=converted,
                thread_id=thread_id,
                reply_to_int=reply_to_int,
                disable_preview=disable_preview,
                reply_markup_first=reply_markup_first,
                edit_first=edit_first,
                skip_text_edit=skip_text_edit,
            )

        async def rich_send() -> list[str]:
            if rich_draft and edit_first is None:
                # ``sendRichMessageDraft`` is ephemeral (~30s) and returns no
                # message_id, so it cannot anchor sevn's placeholder→edit streaming.
                # Send a persistent rich placeholder whose message_id later
                # ``editMessageText(rich_message=…)`` calls can target.
                mid = await self.send_rich_message(
                    chat_id=chat_id,
                    markdown=markdown,
                    thread_id=thread_id,
                    reply_to_message_id=reply_to_int,
                    disable_preview=disable_preview,
                )
                return [mid]
            if edit_first is not None:
                ok = await self.edit_rich_message(
                    chat_id=chat_id,
                    message_id=int(edit_first),
                    markdown=markdown,
                    reply_markup=reply_markup_first,
                    message_thread_id=thread_id,
                    skip_text_edit=skip_text_edit,
                )
                if not ok:
                    raise ValueError("editMessageText rich_message failed")
                return [str(edit_first)]
            mid = await self.send_rich_message(
                chat_id=chat_id,
                markdown=markdown,
                thread_id=thread_id,
                reply_to_message_id=reply_to_int,
                reply_markup=reply_markup_first,
                disable_preview=disable_preview,
            )
            return [mid]

        return await send_with_rich_fallback(
            reply=markdown,
            capability=self.rich_capability,
            rich_cfg=self._cfg.rich,
            parse_mode=self._cfg.parse_mode,
            legacy_send=legacy_send,
            rich_send=rich_send,
            emit_trace=self._emit_trace,
            streaming_active=streaming_active,
        )
