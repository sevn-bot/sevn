"""Bot API HTTP transport for TelegramAdapter.

Module: sevn.channels.telegram_api
Depends: asyncio, httpx, json, sevn.channels.telegram_config

Exports:
    TelegramApiMixin — ``_api`` / multipart helpers mixed into the adapter.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(TelegramApiMixin._api)
    True
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Literal

import httpx
from loguru import logger

from sevn.channels.telegram_send_host import TelegramSendHost

_BOT_API = "https://api.telegram.org"
_TELEGRAM_API_HOST = "api.telegram.org"
_HTTP_READ_TIMEOUT_S = 60.0
_MAX_SEND_RETRIES = 4
# Match the gateway typing loop resend interval (`channel_router._schedule_telegram_typing`).
_CHAT_ACTION_COALESCE_WINDOW_S = 4.0


class TelegramApiMixin(TelegramSendHost):
    """Mixed into :class:`TelegramAdapter`."""

    async def _api(
        self,
        method: str,
        body: dict[str, Any],
        *,
        probe: bool = False,
    ) -> dict[str, Any]:
        """Call one Bot API method with retry and rate-limit handling.
        Honours ``error_code=429`` / HTTP 429 by sleeping for the server-
        provided ``retry_after`` plus a small jitter and retrying. Network
        errors are retried with exponential backoff up to
        ``_MAX_SEND_RETRIES`` attempts; the last exception is re-raised
        when all attempts are exhausted.
        Args:
            method (str): Bot API method name (e.g. ``sendMessage``).
            body (dict[str, Any]): JSON body for the request.
            probe (bool, optional): When ``True``, expected probe failures such as
                ``chat not found`` log at DEBUG instead of WARNING. Defaults to ``False``.
        Returns:
            dict[str, Any]: Decoded JSON response, or ``{}`` when the bot
            token is unset or the response is not a JSON object.
        Raises:
            RuntimeError: When the HTTP client has not been initialised.
            BaseException: Re-raises the last transport error after all
                retries are exhausted.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramApiMixin._api)
            True
        """
        token = self._cfg.bot_token
        if not token:
            return {}
        url = f"{_BOT_API}/bot{token}/{method}"
        client = self._external_client
        if client is None:
            raise RuntimeError("telegram_http_client_not_initialized")
        last_err: BaseException | None = None
        for attempt in range(_MAX_SEND_RETRIES):
            try:
                r = await client.post(url, json=body)
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    data = {}
                if not isinstance(data, dict):
                    data = {}
                err_code = data.get("error_code")
                if err_code == 429 or r.status_code == 429:
                    raw_params = data.get("parameters")
                    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
                    retry_after = float(params.get("retry_after") or 1.0)
                    logger.warning(
                        "telegram_429 method={} retry_after={} attempt={}",
                        method,
                        retry_after,
                        attempt,
                    )
                    await asyncio.sleep(retry_after + 0.05)
                    continue
                # §9 (`PROBLEMS.md`): log 400 description so MarkdownV2 parse failures
                # are visible. Previously the body was consumed silently. A no-op
                # "message is not modified" 400 is an expected outcome of streaming a
                # final body that already matches the placeholder (`specs/18` §4.5);
                # log it at DEBUG so it doesn't read as an error — callers treat it as
                # success and attach quick-action markup separately.
                if r.status_code == 400 or err_code == 400:
                    desc_400 = str(data.get("description") or "")
                    desc_lower = desc_400.lower()
                    if "message is not modified" in desc_lower:
                        logger.debug(
                            "telegram_400_not_modified method={} attempt={}",
                            method,
                            attempt,
                        )
                    elif probe and "chat not found" in desc_lower:
                        logger.debug(
                            "telegram_400_probe method={} description={!r} attempt={}",
                            method,
                            data.get("description"),
                            attempt,
                        )
                    else:
                        logger.warning(
                            "telegram_400 method={} description={!r} attempt={}",
                            method,
                            data.get("description"),
                            attempt,
                        )
                return data
            except BaseException as exc:
                last_err = exc
                await asyncio.sleep(0.5 * (2**attempt) + 0.05)
        if last_err:
            raise last_err
        return {}

    async def answer_callback(
        self,
        callback_query_id: str,
        *,
        text: str = "",
    ) -> dict[str, Any]:
        """Answer an inline-button ``callback_query`` (gateway-owned per §2.2).

        Args:
            callback_query_id (str): Telegram ``callback_query.id`` string.
            text (str): Optional toast shown to the operator (≤ 200 chars).

        Returns:
            dict[str, Any]: Telegram Bot API response body (includes ``ok``).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramApiMixin.answer_callback)
            True
        """
        cqid = callback_query_id.strip()
        if not cqid:
            return {"ok": False, "description": "empty callback_query_id"}
        body: dict[str, Any] = {"callback_query_id": cqid}
        toast = text.strip()
        if toast:
            body["text"] = toast[:200]
        return await self._api("answerCallbackQuery", body)

    async def send_chat_action(
        self,
        *,
        chat_id: int,
        action: Literal["typing"] = "typing",
        message_thread_id: int | None = None,
    ) -> None:
        """Send a Bot API chat action (e.g. typing) — gateway-owned per §4.3.
        Args:
            chat_id (int): Target chat id.
            action (Literal["typing"], optional): Telegram ``action`` field.
                Defaults to ``"typing"``.
            message_thread_id (int | None, optional): Forum topic thread id.
        Returns:
            None: Always.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramApiMixin.send_chat_action)
            True
        """
        key = (chat_id, action, message_thread_id)
        now = time.monotonic()
        last_sent = self._chat_action_last_sent.get(key)
        if last_sent is not None and (now - last_sent) < _CHAT_ACTION_COALESCE_WINDOW_S:
            return
        self._chat_action_last_sent[key] = now
        body: dict[str, Any] = {"chat_id": chat_id, "action": action}
        if message_thread_id is not None:
            body["message_thread_id"] = message_thread_id
        await self._api("sendChatAction", body)

    async def _api_multipart(
        self,
        method: str,
        *,
        data: dict[str, Any],
        files: dict[str, tuple[str, bytes, str]],
    ) -> dict[str, Any]:
        """Call one Bot API multipart method with retry and rate-limit handling.
        Used for ``sendVoice`` and other file-upload endpoints. Retry semantics
        mirror :meth:`_api` (429 ``retry_after`` + transport backoff).
        Args:
            method (str): Bot API method name (e.g. ``sendVoice``).
            data (dict[str, Any]): Form fields (``chat_id``, ``message_thread_id``, …).
            files (dict[str, tuple[str, bytes, str]]): Multipart file map keyed by
                field name; values are ``(filename, bytes, content_type)`` tuples.
        Returns:
            dict[str, Any]: Decoded JSON response, or ``{}`` when the bot token
            is unset or the response is not a JSON object.
        Raises:
            RuntimeError: When the HTTP client has not been initialised.
            BaseException: Re-raises the last transport error after all retries
                are exhausted.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramApiMixin._api_multipart)
            True
        """
        token = self._cfg.bot_token
        if not token:
            return {}
        url = f"{_BOT_API}/bot{token}/{method}"
        client = self._external_client
        if client is None:
            raise RuntimeError("telegram_http_client_not_initialized")
        last_err: BaseException | None = None
        for attempt in range(_MAX_SEND_RETRIES):
            try:
                r = await client.post(url, data=data, files=files)
                try:
                    payload = r.json()
                except json.JSONDecodeError:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                err_code = payload.get("error_code")
                if err_code == 429 or r.status_code == 429:
                    raw_params = payload.get("parameters")
                    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
                    retry_after = float(params.get("retry_after") or 1.0)
                    logger.warning(
                        "telegram_429 method={} retry_after={} attempt={}",
                        method,
                        retry_after,
                        attempt,
                    )
                    await asyncio.sleep(retry_after + 0.05)
                    continue
                return payload
            except BaseException as exc:
                last_err = exc
                await asyncio.sleep(0.5 * (2**attempt) + 0.05)
        if last_err:
            raise last_err
        return {}

    def _log_send_api_error(self, method: str, res: dict[str, Any]) -> None:
        """Emit canonical ``telegram_send_api_error`` for a failed Bot API response.

        Args:
            method (str): Telegram method name that failed.
            res (dict[str, Any]): Parsed JSON body from the Bot API.

        Examples:
            >>> import inspect
            >>> inspect.ismethod(TelegramApiMixin._log_send_api_error)
            False
        """
        logger.info(
            "telegram_send_api_error method={} description={} error_code={}",
            method,
            res.get("description"),
            res.get("error_code"),
        )

    def _message_id_from_api_result(self, res: dict[str, Any]) -> str | None:
        """Extract ``message_id`` from a successful Bot API JSON body.

        Args:
            res (dict[str, Any]): Parsed JSON body from the Bot API.

        Returns:
            str | None: Stringified ``message_id`` when present.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TelegramApiMixin._message_id_from_api_result)
            True
        """
        result = res.get("result")
        if not isinstance(result, dict):
            return None
        mid = result.get("message_id")
        return str(mid) if mid is not None else None

    async def _ensure_client(self) -> httpx.AsyncClient | None:
        """Return an ``httpx.AsyncClient``, lazily constructing one if needed.
        Returns the externally-injected client when present. Otherwise
        creates an owned client with the configured proxy and read timeout,
        marking it for close in :meth:`stop`. Returns ``None`` when no bot
        token is configured (callers short-circuit on that).
        Returns:
            httpx.AsyncClient | None: Active HTTP client, or ``None`` when
            no bot token is set.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramApiMixin._ensure_client)
            True
        """
        if self._external_client is not None:
            return self._external_client
        if not self._cfg.bot_token:
            return None
        proxy = self._cfg.proxy_url
        self._external_client = httpx.AsyncClient(
            timeout=httpx.Timeout(_HTTP_READ_TIMEOUT_S),
            proxy=proxy,
        )
        self._client_owned = True
        return self._external_client
