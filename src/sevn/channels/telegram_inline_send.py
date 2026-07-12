"""Telegram inline-query answer helper for :class:`TelegramAdapter` (W4).

Module: sevn.channels.telegram_inline_send
Depends: typing

Exports:
    TelegramInlineSendMixin — ``answerInlineQuery`` mixed into the adapter.
"""

from __future__ import annotations

from typing import Any

from sevn.channels.telegram_send_host import TelegramSendHost


class TelegramInlineSendMixin(TelegramSendHost):
    """Inline-query send helper for :class:`TelegramAdapter`."""

    async def answer_inline_query(
        self,
        inline_query_id: str,
        *,
        results: list[dict[str, Any]],
        cache_time: int = 300,
        is_personal: bool = True,
        next_offset: str = "",
    ) -> dict[str, Any]:
        """Answer an ``inline_query`` via ``answerInlineQuery`` (I3.1, D8/D10).

        Args:
            inline_query_id (str): Telegram ``inline_query.id`` string.
            results (list[dict[str, Any]]): Inline result objects (≤ 50 per call).
            cache_time (int): Client cache TTL in seconds. Defaults to ``300``.
            is_personal (bool): ``is_personal`` flag (D8). Defaults to ``True``.
            next_offset (str): Pagination cursor when more rows exist.

        Returns:
            dict[str, Any]: Parsed Bot API JSON body (empty when token unset).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramInlineSendMixin.answer_inline_query)
            True
        """
        qid = inline_query_id.strip()
        if not qid:
            return {}
        body: dict[str, Any] = {
            "inline_query_id": qid,
            "results": results[:50],
            "cache_time": max(0, int(cache_time)),
            "is_personal": bool(is_personal),
        }
        offset = next_offset.strip()
        if offset:
            body["next_offset"] = offset
        return await self._api("answerInlineQuery", body)
