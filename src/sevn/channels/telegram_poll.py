"""Long-poll lifecycle and command-menu sync for TelegramAdapter.

Module: sevn.channels.telegram_poll
Depends: asyncio, secrets, socket, sevn.gateway.telegram.telegram_inline

Exports:
    TelegramPollMixin — ``start`` / ``stop`` / poll loop mixed into the adapter.

Examples:
    >>> import inspect
    >>> inspect.iscoroutinefunction(TelegramPollMixin.start)
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import secrets
import socket
from typing import Any

import httpx
from loguru import logger

from sevn.channels.telegram_api import _TELEGRAM_API_HOST
from sevn.channels.telegram_send_host import TelegramSendHost
from sevn.config.defaults import TELEGRAM_SET_MY_COMMANDS_DEBOUNCE_S

_POLL_BACKOFF_SCHEDULE_S = (1.0, 2.0, 5.0, 15.0, 30.0)
_POLL_BACKOFF_CAP_S = 30.0
_GET_UPDATES_TIMEOUT = 30
# Cap on concurrently in-flight ``handle_webhook`` dispatches spawned by the
# poll loop. The poll loop must not block on a slow turn dispatch (W2 / plan
# D9): each update is dispatched as a background task so reading the next update
# never waits on the previous turn. Per-session ordering is still guaranteed by
# the per-session queue downstream in ``SessionManager``. This bound only guards
# against unbounded task fan-out under a burst.
_MAX_INFLIGHT_DISPATCH = 64


def _is_poll_connectivity_error(exc: BaseException) -> bool:
    """Return True when a poll-loop failure is transport/DNS, not Bot API logic.

    Args:
        exc (BaseException): Exception raised from :meth:`TelegramAdapter._api`
            or the HTTP client during ``getUpdates``.

    Returns:
        bool: True for connection/DNS timeouts that should trigger backoff.

    Examples:
        >>> _is_poll_connectivity_error(httpx.ConnectError("dns", request=httpx.Request("GET", "https://x")))
        True
        >>> _is_poll_connectivity_error(RuntimeError("bad token"))
        False
    """
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, socket.gaierror)):
        return True
    cause = exc.__cause__
    return isinstance(cause, socket.gaierror)


def _poll_backoff_delay_s(attempt: int) -> float:
    """Exponential poll backoff with jitter (1→2→5→15→cap 30 s).

    Args:
        attempt (int): Zero-based consecutive connectivity failure count.

    Returns:
        float: Seconds to sleep before the next poll iteration.

    Examples:
        >>> 1.0 <= _poll_backoff_delay_s(0) <= 1.25
        True
        >>> _poll_backoff_delay_s(99) <= _POLL_BACKOFF_CAP_S
        True
    """
    schedule = _POLL_BACKOFF_SCHEDULE_S
    base = schedule[min(max(attempt, 0), len(schedule) - 1)]
    jitter = random.uniform(0.0, base * 0.25)  # nosec B311 — poll retry jitter, not crypto
    return min(base + jitter, _POLL_BACKOFF_CAP_S)


class TelegramPollMixin(TelegramSendHost):
    """Mixed into :class:`TelegramAdapter`."""

    async def start(self, router: Any) -> None:
        """Wire the adapter to a router and start webhook or polling transport.
        For ``webhook`` mode this calls ``setWebhook`` with the configured
        URL, allowed updates, and optional secret token. For ``poll`` mode
        a long-polling task is scheduled. A debounced ``setMyCommands``
        task is always scheduled so the visible command menu reflects the
        latest registry.
        Args:
            router (Any): Object exposing ``handle_webhook(channel, update)``
                (the gateway's :class:`ChannelRouter`).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin.start)
            True
        """
        self._router = router
        await self._ensure_client()
        if self._cfg.bot_token:
            await self._populate_bot_user_id_from_getme()
            await self._probe_rich_capability(force=True)
        if self._cfg.mode == "webhook" and self._cfg.bot_token and self._cfg.webhook_url:
            secret = self._cfg.webhook_secret_token.strip()
            if not secret:
                secret = secrets.token_urlsafe(32)
                self._cfg = self._cfg.model_copy(update={"webhook_secret_token": secret})
            sw: dict[str, Any] = {
                "url": self._cfg.webhook_url,
                "allowed_updates": self._allowed_updates(),
                "secret_token": secret,
            }
            await self._api("setWebhook", sw)
        if self._cfg.mode == "poll" and self._cfg.bot_token:
            self._stop.clear()
            self._poll_task = asyncio.create_task(self._poll_loop(), name="telegram_poll")
        self._commands_task = asyncio.create_task(
            self._debounced_set_my_commands(), name="tg_commands"
        )
        if self._cfg.bot_token:
            logger.info(
                "telegram_adapter_started mode={} poll={} webhook_url_set={}",
                self._cfg.mode,
                self._cfg.mode == "poll",
                bool((self._cfg.webhook_url or "").strip()),
            )
        else:
            logger.warning("telegram_adapter_started_without_bot_token")
        await self._emit_trace(kind="channel.telegram.start", status="ok")

    async def stop(self) -> None:
        """Cancel polling and command tasks, flush commands, and close owned HTTP client.
        Idempotent: safe to call multiple times. Externally-injected HTTP
        clients are left alone; only owned clients are closed.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin.stop)
            True
        """
        await self._emit_trace(kind="channel.telegram.stop", status="ok")
        self._stop.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        if self._commands_task is not None:
            self._commands_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._commands_task
            self._commands_task = None
        # W2: cancel and reap any in-flight background dispatch tasks so shutdown
        # does not leak running turns.
        if self._dispatch_tasks:
            pending = list(self._dispatch_tasks)
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._dispatch_tasks.clear()
        await self._flush_set_my_commands()
        if self._client_owned and self._external_client is not None:
            await self._external_client.aclose()
            self._external_client = None
            self._client_owned = False

    async def _debounced_set_my_commands(self) -> None:
        """Sleep ``TELEGRAM_SET_MY_COMMANDS_DEBOUNCE_S`` then push the command menu.
        Designed to be cancelled during :meth:`stop`; the cancellation path
        returns cleanly so the parent ``gather`` does not surface a
        spurious error.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin._debounced_set_my_commands)
            True
        """
        try:
            await asyncio.sleep(TELEGRAM_SET_MY_COMMANDS_DEBOUNCE_S)
            await self._flush_set_my_commands()
        except asyncio.CancelledError:
            return

    async def _flush_set_my_commands(self) -> None:
        """Push the bot command menu via ``setMyCommands`` for each scope.
        Posts the same command list to the ``default``,
        ``all_private_chats`` and ``all_group_chats`` scopes so the menu is
        consistent across surfaces. No-ops when the bot token is unset.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin._flush_set_my_commands)
            True
        """
        if not self._cfg.bot_token:
            return
        client = await self._ensure_client()
        if client is None:
            return
        cmds = [
            {"command": "start", "description": "Welcome and deep links"},
            {"command": "help", "description": "Help"},
            {"command": "new", "description": "New session"},
            {"command": "status", "description": "Status"},
            {"command": "stop", "description": "Stop in-flight run"},
            {"command": "config", "description": "Configuration menu"},
            {"command": "voice", "description": "Voice settings"},
            {"command": "model", "description": "Model settings"},
        ]
        router = self._router
        if router is not None:
            content_root = getattr(router, "_content_root", None)
            if content_root is not None:
                from sevn.gateway.commands.shortcuts_store import list_visible_shortcuts

                for row in list_visible_shortcuts(
                    content_root,
                    user_id="0",
                    is_owner=True,
                ):
                    name = str(row.get("name", "")).strip().lower()
                    desc = str(row.get("description", name))[:256]
                    if name:
                        cmds.append({"command": name, "description": desc or name})
        for locale in self._cfg.commands_locale:
            for scope in ("default", "all_private_chats", "all_group_chats"):
                body: dict[str, Any] = {"commands": cmds, "scope": {"type": scope}}
                if locale and locale != "en":
                    body["language_code"] = locale
                await self._api("setMyCommands", body)
        if router is not None:
            workspace = getattr(router, "_workspace", None)
            if workspace is not None:
                from sevn.gateway.webapp.webapp_viewer import sync_telegram_chat_menu_button

                await sync_telegram_chat_menu_button(self._api, workspace)

    async def _dispatch_update(self, upd: dict[str, Any]) -> None:
        """Schedule ``router.handle_webhook`` for *upd* without blocking the caller.

        The poll loop must keep reading updates while a turn runs, so each update
        is handed to a bounded background task (W2 / plan D9). Per-session
        ordering is preserved downstream by the per-session dispatch queue in
        :class:`~sevn.gateway.session_manager.SessionManager`; this layer only
        guarantees that one slow ``handle_webhook`` cannot delay the next
        update's dispatch. Backpressure: when ``_MAX_INFLIGHT_DISPATCH`` tasks
        are already in flight, the ``acquire`` below awaits a free slot.

        Args:
            upd (dict[str, Any]): Raw Telegram update object.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin._dispatch_update)
            True
        """
        router = self._router
        if router is None:
            return
        await self._dispatch_gate.acquire()

        async def _run() -> None:
            try:
                await router.handle_webhook("telegram", upd)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("telegram_dispatch_failed update_id={}", upd.get("update_id"))

        task = asyncio.create_task(_run(), name="telegram_dispatch")
        self._dispatch_tasks.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            self._dispatch_tasks.discard(t)
            self._dispatch_gate.release()

        task.add_done_callback(_done)

    async def _poll_loop(self) -> None:
        """Long-poll ``getUpdates`` and dispatch each update to the router.
        Drains any pending updates before entering the loop (see
        :meth:`_drain_pending`), then polls with ``_GET_UPDATES_TIMEOUT``
        seconds of long-poll. Transport/DNS failures log one WARNING (with a
        single traceback per outage), apply exponential backoff with jitter,
        and set :attr:`connected` to ``False`` until the next successful poll.
        Bot API ``ok: false`` responses use a short fixed delay without marking
        the adapter offline.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin._poll_loop)
            True
        """
        router = self._router
        if router is None:
            return
        await self._drain_pending()
        client = await self._ensure_client()
        if client is None:
            return
        poll_backoff_attempt = 0
        poll_was_offline = False
        poll_offline_detail_logged = False
        while not self._stop.is_set():
            await self._emit_trace(
                kind="channel.telegram.poll.cycle",
                status="tick",
                attrs={"offset": self._last_update_id + 1},
            )
            try:
                res = await self._api(
                    "getUpdates",
                    {
                        "offset": self._last_update_id + 1,
                        "timeout": _GET_UPDATES_TIMEOUT,
                        "allowed_updates": self._allowed_updates(),
                    },
                )
                if not res.get("ok"):
                    logger.warning(
                        "telegram_poll_api_not_ok ok={} description={!r}",
                        res.get("ok"),
                        res.get("description"),
                    )
                    await asyncio.sleep(1.0)
                    continue
                for upd in res.get("result") or []:
                    if not isinstance(upd, dict):
                        continue
                    uid = upd.get("update_id")
                    if isinstance(uid, int):
                        self._last_update_id = max(self._last_update_id, uid)
                    # W2: dispatch as a bounded background task so a slow turn
                    # never blocks reading the next update. Offset is already
                    # advanced above, so the server won't redeliver this update.
                    await self._dispatch_update(upd)
                if poll_was_offline:
                    logger.info(
                        "telegram_poll_recovered host={}",
                        _TELEGRAM_API_HOST,
                    )
                    await self._probe_rich_capability(force=True)
                poll_was_offline = False
                poll_offline_detail_logged = False
                poll_backoff_attempt = 0
                self._poll_connected = True
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if _is_poll_connectivity_error(exc):
                    self._poll_connected = False
                    if not poll_offline_detail_logged:
                        logger.opt(exception=exc).warning(
                            "telegram_poll_offline host={} err={}",
                            _TELEGRAM_API_HOST,
                            exc,
                        )
                        poll_offline_detail_logged = True
                    poll_was_offline = True
                    delay = _poll_backoff_delay_s(poll_backoff_attempt)
                    poll_backoff_attempt += 1
                    await asyncio.sleep(delay)
                else:
                    logger.warning("telegram_poll_api_error err={}", exc)
                    await asyncio.sleep(2.0)

    async def _drain_pending(self) -> None:
        """Consume any updates queued at the Bot API before entering the poll loop.
        Uses ``timeout=0`` so the server returns immediately if there is
        nothing queued. Each batch updates ``self._last_update_id`` and
        forwards to the router so we never replay a stale message.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramPollMixin._drain_pending)
            True
        """
        client = await self._ensure_client()
        if client is None or self._router is None:
            return
        offset = 0
        while True:
            res = await self._api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 0,
                    "allowed_updates": self._allowed_updates(),
                },
            )
            rows = res.get("result") if isinstance(res, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            for upd in rows:
                if isinstance(upd, dict):
                    uid = upd.get("update_id")
                    if isinstance(uid, int):
                        offset = uid + 1
                        self._last_update_id = max(self._last_update_id, uid)
                    # W2: consistent with the live poll loop — dispatch backlog
                    # updates as bounded background tasks. Per-session ordering is
                    # preserved by the downstream per-session dispatch queue.
                    await self._dispatch_update(upd)
