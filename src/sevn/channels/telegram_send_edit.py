"""Plain-text Telegram send/edit with shared rich→plain parse-mode retry (W4).

Module: sevn.channels.telegram_send_edit
Depends: loguru, sevn.channels.telegram_format, sevn.logging.structured

Exports:
    is_entity_parse_error — detect Bot API entity-parse failures.
    is_message_not_modified — detect no-op edit responses.
    is_message_too_long_desc — detect MESSAGE_TOO_LONG descriptions.
    build_text_api_body — attach ``parse_mode`` + converted text for one attempt.
    TelegramTextSendMixin — ``sendMessage`` / ``editMessageText`` chunk helpers mixed
        into :class:`TelegramAdapter`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from loguru import logger

from sevn.channels.telegram_format import to_telegram
from sevn.channels.telegram_send_host import TelegramSendHost
from sevn.logging.structured import debug_event, preview

ParseMode = Literal["rich", "plain"]


def is_entity_parse_error(description: str) -> bool:
    """Return whether a Bot API description indicates entity-parse failure.

    Args:
        description (str): ``description`` field from a failed Bot API response.

    Returns:
        bool: ``True`` when Telegram rejected markup entities.

    Examples:
        >>> is_entity_parse_error("Bad Request: can't parse entities")
        True
        >>> is_entity_parse_error("message is not modified")
        False
    """
    desc_l = description.lower()
    return "can't parse entities" in desc_l or "parse entities" in desc_l


def is_message_not_modified(description: str) -> bool:
    """Return whether a Bot API edit failed because the body is unchanged.

    Args:
        description (str): ``description`` field from a failed Bot API response.

    Returns:
        bool: ``True`` for the canonical no-op edit error.

    Examples:
        >>> is_message_not_modified("Bad Request: message is not modified")
        True
        >>> is_message_not_modified("MESSAGE_TOO_LONG")
        False
    """
    return "message is not modified" in description.lower()


def is_message_too_long_desc(desc: str) -> bool:
    """Return whether a Bot API error description indicates ``MESSAGE_TOO_LONG``.

    Args:
        desc (str): ``description`` field from a failed Bot API response.

    Returns:
        bool: ``True`` when the text exceeds Telegram's UTF-16 limit.

    Examples:
        >>> is_message_too_long_desc("Bad Request: message is too long")
        True
        >>> is_message_too_long_desc("MESSAGE_TOO_LONG")
        True
        >>> is_message_too_long_desc("message is not modified")
        False
    """
    desc_l = desc.lower()
    return "too long" in desc_l or "message_too_long" in desc_l


def build_text_api_body(
    base: dict[str, Any],
    *,
    markdown: str,
    parse_mode: str,
    mode: ParseMode,
    pre_rendered: bool = False,
) -> dict[str, Any]:
    """Build one ``sendMessage`` / ``editMessageText`` body for a parse-mode attempt.

    Args:
        base (dict[str, Any]): Shared Bot API fields (``chat_id``, thread, markup, …).
        markdown (str): Source Markdown or pre-rendered Telegram text.
        parse_mode (str): Configured adapter parse mode (e.g. ``HTML``).
        mode (ParseMode): ``rich`` applies ``parse_mode`` + conversion; ``plain`` omits it.
        pre_rendered (bool): When ``True``, ``markdown`` is already converted for rich mode.

    Returns:
        dict[str, Any]: Request body ready for :meth:`TelegramAdapter._api`.

    Examples:
        >>> body = build_text_api_body({"chat_id": 1}, markdown="hi", parse_mode="HTML", mode="rich")
        >>> body["parse_mode"]
        'HTML'
        >>> "text" in body
        True
    """
    body = dict(base)
    if mode == "rich":
        body["parse_mode"] = parse_mode
        body["text"] = markdown if pre_rendered else to_telegram(markdown, parse_mode)
    else:
        body.pop("parse_mode", None)
        body["text"] = markdown
    return body


async def _parse_mode_retry(
    *,
    markdown: str,
    parse_mode: str,
    base_body: dict[str, Any],
    api_call: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    pre_rendered: bool = False,
    on_entity_parse_fallback: Callable[[], Awaitable[None]] | None = None,
) -> tuple[dict[str, Any], ParseMode | None]:
    """Run rich→plain Bot API attempts until success or a non-entity error.

    Args:
        markdown (str): Source or pre-rendered text body.
        parse_mode (str): Adapter parse mode for the rich attempt.
        base_body (dict[str, Any]): Shared request fields excluding ``text`` / ``parse_mode``.
        api_call (Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]): Async Bot API caller.
        pre_rendered (bool): Skip ``to_telegram`` on the rich attempt.
        on_entity_parse_fallback (Callable[[], Awaitable[None]] | None): Optional trace hook
            after a rich entity-parse failure.

    Returns:
        tuple[dict[str, Any], ParseMode | None]: Last response and winning mode, or
        ``({}, None)`` when every attempt failed without a response.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_parse_mode_retry)
        True
    """
    last_res: dict[str, Any] = {}
    for mode in ("rich", "plain"):
        body = build_text_api_body(
            base_body,
            markdown=markdown,
            parse_mode=parse_mode,
            mode=mode,
            pre_rendered=pre_rendered,
        )
        last_res = await api_call(body)
        if last_res.get("ok"):
            return last_res, mode
        desc = str(last_res.get("description") or "")
        if mode == "rich" and is_entity_parse_error(desc):
            if on_entity_parse_fallback is not None:
                await on_entity_parse_fallback()
            continue
        break
    return last_res, None


class TelegramTextSendMixin(TelegramSendHost):
    """Plain-text chunk send/edit helpers for :class:`TelegramAdapter`."""

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
    ) -> list[str]:
        """Send or edit pre-rendered legacy text (already passed through ``to_telegram``).

        Used by :func:`send_with_rich_fallback` so fallback bodies are not converted twice.

        Args:
            chat_id (int): Destination chat id.
            rendered_text (str): Telegram-ready body with ``parse_mode`` applied.
            thread_id (int | None): Forum thread id when set.
            reply_to_int (int | None): Reply target for fresh sends.
            disable_preview (bool): Link-preview disable flag.
            reply_markup_first (dict[str, Any] | None): Keyboard markup.
            edit_first (int | None): When set, edit this message instead of sending.
            skip_text_edit (bool): Skip redundant edit when streaming already wrote body.

        Returns:
            list[str]: Platform message ids.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramTextSendMixin._send_rendered_text)
            True
        """
        parse_mode = self._cfg.parse_mode
        use_edit = edit_first is not None
        edit_key = (chat_id, int(edit_first)) if edit_first is not None else None
        if (
            use_edit
            and edit_first is not None
            and edit_key is not None
            and (skip_text_edit or self._last_edit_text.get(edit_key) == rendered_text)
        ):
            if reply_markup_first is not None:
                ok_markup = await self.edit_reply_markup(
                    chat_id=chat_id,
                    message_id=int(edit_first),
                    reply_markup=reply_markup_first,
                    message_thread_id=thread_id,
                )
                if not ok_markup:
                    logger.info(
                        "telegram_edit_reply_markup_noop_skip chat_id={} message_id={}",
                        chat_id,
                        edit_first,
                    )
            self._remember_edit_text(edit_key, rendered_text)
            return [str(edit_first)]
        base_body: dict[str, Any] = {
            "chat_id": chat_id,
            "disable_web_page_preview": disable_preview,
        }
        if thread_id is not None:
            base_body["message_thread_id"] = thread_id
        if not use_edit and reply_to_int is not None:
            base_body["reply_to_message_id"] = reply_to_int
        if reply_markup_first is not None:
            base_body["reply_markup"] = reply_markup_first
        method = "editMessageText" if use_edit else "sendMessage"
        if use_edit and edit_first is not None:
            base_body["message_id"] = edit_first

        async def _call(body: dict[str, Any]) -> dict[str, Any]:
            return await self._api(method, body)

        res, _mode = await _parse_mode_retry(
            markdown=rendered_text,
            parse_mode=parse_mode,
            base_body=base_body,
            api_call=_call,
            pre_rendered=True,
        )
        if res.get("ok"):
            mid = self._message_id_from_api_result(res)
            if mid is not None:
                if use_edit and edit_first is not None:
                    self._remember_edit_text((chat_id, int(edit_first)), rendered_text)
                return [mid]
            if use_edit and edit_first is not None:
                self._remember_edit_text((chat_id, int(edit_first)), rendered_text)
                return [str(edit_first)]
        desc = str(res.get("description") or "").lower()
        if use_edit and is_message_not_modified(desc) and edit_first is not None:
            self._remember_edit_text((chat_id, int(edit_first)), rendered_text)
            if reply_markup_first is not None:
                await self.edit_reply_markup(
                    chat_id=chat_id,
                    message_id=edit_first,
                    reply_markup=reply_markup_first,
                    message_thread_id=thread_id,
                )
            return [str(edit_first)]
        self._log_send_api_error(method, res)
        return []

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
    ) -> list[str]:
        """Send one or more text chunks via ``sendMessage`` / ``editMessageText``.

        Markdown → escaped → plain retry chain applies per chunk. Only the first
        chunk may carry ``reply_to_message_id``, ``reply_markup``, or target
        ``edit_message_id``. When ``skip_text_edit`` is set (streaming already
        wrote the final body), or the cached last edit text matches, skip a
        redundant ``editMessageText`` and attach markup only when needed.

        Args:
            chat_id (int): Destination chat id.
            chunks (list[str]): Non-empty text segments from :func:`chunk_text`.
            thread_id (int | None): Forum ``message_thread_id`` when set.
            reply_to_int (int | None): Reply target for the first chunk.
            disable_preview (bool): ``disable_web_page_preview`` flag.
            reply_markup_first (dict[str, Any] | None): Inline or reply keyboard
                on the first chunk only.
            edit_first (int | None): When set, edit this message for chunk 0.
            skip_text_edit (bool): When ``True``, skip ``editMessageText`` for
                chunk 0 because streaming already wrote the identical body.

        Returns:
            list[str]: Telegram ``message_id`` strings per sent chunk.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramTextSendMixin._send_text)
            True
        """
        out_ids: list[str] = []
        multi_chunk = len(chunks) > 1
        parse_mode = self._cfg.parse_mode
        for i, chunk in enumerate(chunks):
            is_first = i == 0
            is_last = i == len(chunks) - 1
            use_edit = is_first and edit_first is not None
            chunk_reply_markup: dict[str, Any] | None = None
            if reply_markup_first is not None and (
                (multi_chunk and is_last) or (not multi_chunk and is_first)
            ):
                chunk_reply_markup = reply_markup_first
            if use_edit and edit_first is not None:
                edit_key = (chat_id, int(edit_first))
                text_unchanged = skip_text_edit or self._last_edit_text.get(edit_key) == chunk
                if text_unchanged:
                    if chunk_reply_markup is not None:
                        ok_markup = await self.edit_reply_markup(
                            chat_id=chat_id,
                            message_id=int(edit_first),
                            reply_markup=chunk_reply_markup,
                            message_thread_id=thread_id,
                        )
                        if not ok_markup:
                            logger.info(
                                "telegram_edit_reply_markup_noop_skip chat_id={} message_id={}",
                                chat_id,
                                edit_first,
                            )
                    self._remember_edit_text(edit_key, chunk)
                    out_ids.append(str(edit_first))
                    continue
            body: dict[str, Any] = {
                "chat_id": chat_id,
                "disable_web_page_preview": disable_preview,
            }
            if thread_id is not None:
                body["message_thread_id"] = thread_id
            if is_first and reply_to_int is not None and not use_edit:
                body["reply_to_message_id"] = reply_to_int
            if chunk_reply_markup is not None:
                body["reply_markup"] = chunk_reply_markup
            method = "editMessageText" if use_edit else "sendMessage"
            if use_edit:
                body["message_id"] = edit_first
            api_method = method

            async def _call(
                request_body: dict[str, Any],
                *,
                _method: str = api_method,
            ) -> dict[str, Any]:
                return await self._api(_method, request_body)

            async def _trace_fallback() -> None:
                await self._emit_trace(
                    kind="channel.telegram.markdown_fallback",
                    status="plain",
                    attrs={"step": 2, "from": parse_mode},
                )

            res, _mode = await _parse_mode_retry(
                markdown=chunk,
                parse_mode=parse_mode,
                base_body=body,
                api_call=_call,
                on_entity_parse_fallback=_trace_fallback,
            )
            if res.get("ok"):
                result = res.get("result")
                mid = None
                if isinstance(result, dict):
                    mid = result.get("message_id")
                if mid is not None:
                    out_ids.append(str(mid))
                    logger.info(
                        "telegram_send_api_ok method={} chat_id={} message_id={}",
                        method,
                        chat_id,
                        mid,
                    )
                elif use_edit and edit_first is not None:
                    out_ids.append(str(edit_first))
                if use_edit and edit_first is not None:
                    self._remember_edit_text((chat_id, int(edit_first)), chunk)
                continue
            desc = str(res.get("description") or "").lower()
            if use_edit and is_message_not_modified(desc):
                if edit_first is not None:
                    self._remember_edit_text((chat_id, int(edit_first)), chunk)
                if edit_first is not None and chunk_reply_markup is not None:
                    ok_markup = await self.edit_reply_markup(
                        chat_id=chat_id,
                        message_id=edit_first,
                        reply_markup=chunk_reply_markup,
                        message_thread_id=thread_id,
                    )
                    if not ok_markup:
                        logger.info(
                            "telegram_edit_reply_markup_noop_skip chat_id={} message_id={}",
                            chat_id,
                            edit_first,
                        )
                if edit_first is not None:
                    out_ids.append(str(edit_first))
                continue
            self._log_send_api_error(method, res)
            break
        return out_ids

    async def _edit_or_split_long_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
        send_followups: bool = True,
    ) -> tuple[bool, list[int]]:
        """Edit the first chunk in place and optionally ``sendMessage`` the rest.

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Placeholder message id to edit with chunk 0.
            text (str): Full outbound body to split via :func:`chunk_text`.
            reply_markup (dict[str, Any] | None): Inline keyboard for single-chunk
                edits only; multi-chunk callers attach markup on the last chunk.
            message_thread_id (int | None): Forum thread id when set.
            send_followups (bool): When ``False``, only chunk 0 is edited.

        Returns:
            tuple[bool, list[int]]: Success flag and extra ``message_id`` values
            from follow-up ``sendMessage`` calls.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramTextSendMixin._edit_or_split_long_message)
            True
        """
        from sevn.channels.telegram_config import chunk_text

        chunks = chunk_text(text)
        if not chunks:
            return False, []
        first_markup = reply_markup if len(chunks) == 1 else None
        first_ok = await self._edit_message_text_body(
            chat_id=chat_id,
            message_id=message_id,
            text=chunks[0],
            reply_markup=first_markup,
            message_thread_id=message_thread_id,
        )
        if not first_ok:
            return False, []
        extra_ids: list[int] = []
        if not send_followups or len(chunks) <= 1:
            return True, extra_ids
        for chunk in chunks[1:]:
            mid = await self._send_followup_text_message(
                chat_id=chat_id,
                text=chunk,
                message_thread_id=message_thread_id,
                reply_to_message_id=message_id,
            )
            if mid is None:
                return False, extra_ids
            extra_ids.append(mid)
        return True, extra_ids

    async def _edit_message_text_body(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        message_thread_id: int | None = None,
    ) -> bool:
        """Issue ``editMessageText`` with rich/plain retry (no split fallback).

        Args:
            chat_id (int): Destination chat id.
            message_id (int): Target Telegram message id.
            text (str): Replacement body (must fit Telegram limits).
            reply_markup (dict[str, Any] | None): Optional inline keyboard.
            message_thread_id (int | None): Forum ``message_thread_id`` when set.

        Returns:
            bool: ``True`` when the Bot API reports success.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramTextSendMixin._edit_message_text_body)
            True
        """
        edit_key = (chat_id, int(message_id))
        markup = self._prepare_inline_reply_markup(
            reply_markup,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
        )
        if markup is None and self._last_edit_text.get(edit_key) == text:
            return True
        parse_mode = self._cfg.parse_mode
        base_body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": int(message_id),
        }
        if message_thread_id is not None:
            base_body["message_thread_id"] = message_thread_id
        if markup is not None:
            base_body["reply_markup"] = markup

        async def _call(body: dict[str, Any]) -> dict[str, Any]:
            debug_event(
                "telegram.stream_edit",
                chat_id=chat_id,
                message_id=int(message_id),
                text_len=len(text),
                preview=preview(text),
                parse_mode=body.get("parse_mode"),
            )
            return await self._api("editMessageText", body)

        async def _trace_fallback() -> None:
            await self._emit_trace(
                kind="channel.telegram.markdown_fallback",
                status="plain",
                attrs={"step": 2, "from": parse_mode},
            )

        res, winning_mode = await _parse_mode_retry(
            markdown=text,
            parse_mode=parse_mode,
            base_body=base_body,
            api_call=_call,
            on_entity_parse_fallback=_trace_fallback,
        )
        if res.get("ok"):
            self._remember_edit_text(edit_key, text)
            return True
        desc = str(res.get("description") or "")
        debug_event(
            "telegram.stream_edit_failed",
            chat_id=chat_id,
            message_id=int(message_id),
            text_len=len(text),
            preview=preview(text),
            parse_mode=parse_mode if winning_mode == "rich" else None,
            desc=desc,
        )
        logger.info(
            "telegram_edit_message_text_failed chat_id={} message_id={} desc={}",
            chat_id,
            message_id,
            desc,
        )
        if is_message_not_modified(desc):
            self._remember_edit_text(edit_key, text)
            if markup is not None:
                return await self.edit_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=markup,
                    message_thread_id=message_thread_id,
                )
            return True
        if is_message_too_long_desc(desc):
            return False
        return False

    async def _send_followup_text_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None,
        reply_to_message_id: int | None = None,
    ) -> int | None:
        """Send one text chunk via ``sendMessage`` (split-message follow-up).

        Args:
            chat_id (int): Destination chat id.
            text (str): Chunk body.
            message_thread_id (int | None): Forum thread id when set.
            reply_to_message_id (int | None): Reply target (placeholder id).

        Returns:
            int | None: New ``message_id`` on success, else ``None``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramTextSendMixin._send_followup_text_message)
            True
        """
        parse_mode = self._cfg.parse_mode
        base_body: dict[str, Any] = {"chat_id": chat_id}
        if message_thread_id is not None:
            base_body["message_thread_id"] = message_thread_id
        if reply_to_message_id is not None:
            base_body["reply_to_message_id"] = reply_to_message_id

        async def _call(body: dict[str, Any]) -> dict[str, Any]:
            return await self._api("sendMessage", body)

        res, _mode = await _parse_mode_retry(
            markdown=text,
            parse_mode=parse_mode,
            base_body=base_body,
            api_call=_call,
        )
        if res.get("ok"):
            result = res.get("result")
            if isinstance(result, dict):
                mid = result.get("message_id")
                if isinstance(mid, int):
                    logger.info(
                        "telegram_send_api_ok method={} chat_id={} message_id={}",
                        "sendMessage",
                        chat_id,
                        mid,
                    )
                    return mid
            return None
        self._log_send_api_error("sendMessage", res)
        return None
