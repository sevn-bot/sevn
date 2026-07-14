"""Telegram channel adapter facade (`specs/18-channel-telegram.md`).

Module: sevn.channels.telegram
Depends: sevn.channels.telegram_config, sevn.channels.telegram_{inbound,api,outbound,poll},
    sevn.channels.telegram_{rich_send,send_edit,inline_send}, sevn.gateway.channel_types

The monolithic adapter was split into focused mixins (finding-1 follow-up). This module
assembles :class:`TelegramAdapter` and re-exports the stable public surface from
``telegram_config`` and related helpers.

Exports:
    TelegramAdapter - Parse webhook updates, send via Bot API, optional long-poll.

Re-exports (stable imports; defined in ``telegram_config``):
    DMPolicy, TopicConfig, TelegramConfig, TelegramSendError,
    telegram_utf16_len, chunk_text, format_reply_quote,
    build_reply_keyboard_markup, telegram_config_from_workspace.

Examples:
    >>> from sevn.channels.telegram import TelegramAdapter, chunk_text
    >>> TelegramAdapter(resolved_bot_token="t").name
    'telegram'
    >>> chunk_text("hi")[0]
    'hi'
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections import OrderedDict
from time import time_ns
from typing import TYPE_CHECKING, Any

from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent, TraceSink
from sevn.channels.telegram_api import TelegramApiMixin
from sevn.channels.telegram_capabilities import RichCapability, detect_rich_support
from sevn.channels.telegram_config import (
    DMPolicy as DMPolicy,
)
from sevn.channels.telegram_config import (
    TelegramConfig as TelegramConfig,
)
from sevn.channels.telegram_config import (
    TelegramSendError as TelegramSendError,
)
from sevn.channels.telegram_config import (
    TopicConfig as TopicConfig,
)
from sevn.channels.telegram_config import (
    _markdown_escape as _markdown_escape,
)
from sevn.channels.telegram_config import (
    _parse_dm_policy as _parse_dm_policy,
)
from sevn.channels.telegram_config import (
    build_reply_keyboard_markup as build_reply_keyboard_markup,
)
from sevn.channels.telegram_config import (
    chunk_text as chunk_text,
)
from sevn.channels.telegram_config import (
    format_reply_quote as format_reply_quote,
)
from sevn.channels.telegram_config import (
    telegram_config_from_workspace as telegram_config_from_workspace,
)
from sevn.channels.telegram_config import (
    telegram_utf16_len as telegram_utf16_len,
)
from sevn.channels.telegram_inbound import TelegramInboundMixin
from sevn.channels.telegram_inline_send import TelegramInlineSendMixin
from sevn.channels.telegram_outbound import (
    TELEGRAM_STREAM_PLACEHOLDER as TELEGRAM_STREAM_PLACEHOLDER,
)
from sevn.channels.telegram_outbound import TelegramOutboundMixin
from sevn.channels.telegram_poll import (
    _MAX_INFLIGHT_DISPATCH,
    TelegramPollMixin,
)
from sevn.channels.telegram_poll import (
    _is_poll_connectivity_error as _is_poll_connectivity_error,
)
from sevn.channels.telegram_poll import (
    _poll_backoff_delay_s as _poll_backoff_delay_s,
)
from sevn.channels.telegram_rich_send import (
    TELEGRAM_RICH_DRAFT_KEY as TELEGRAM_RICH_DRAFT_KEY,
)
from sevn.channels.telegram_rich_send import (
    TELEGRAM_STREAMING_ACTIVE_KEY as TELEGRAM_STREAMING_ACTIVE_KEY,
)
from sevn.channels.telegram_rich_send import (
    TELEGRAM_USE_RICH_KEY as TELEGRAM_USE_RICH_KEY,
)
from sevn.channels.telegram_rich_send import TelegramRichSendMixin
from sevn.channels.telegram_send_edit import TelegramTextSendMixin
from sevn.gateway.channel_types import ChannelAdapter
from sevn.gateway.telegram.telegram_inline import resolve_inline_config, telegram_allowed_updates
from sevn.ui.openui.models import RasteriseCaps

if TYPE_CHECKING:
    import httpx


class TelegramAdapter(
    TelegramOutboundMixin,
    TelegramInboundMixin,
    TelegramApiMixin,
    TelegramPollMixin,
    TelegramRichSendMixin,
    TelegramTextSendMixin,
    TelegramInlineSendMixin,
    ChannelAdapter,
):
    """Telegram Bot API adapter: parse updates, enforce access policy, send messages."""

    def __init__(
        self,
        *,
        config: TelegramConfig | None = None,
        bot_token_ref: str | None = None,
        resolved_bot_token: str | None = None,
        sqlite_conn: sqlite3.Connection | None = None,
        trace: TraceSink | None = None,
        http_client: httpx.AsyncClient | None = None,
        pairing_store: Any | None = None,
    ) -> None:
        """Wire up adapter state without performing any I/O.

        Either ``config`` (already-validated ``TelegramConfig``) or
        ``resolved_bot_token`` (raw token string) must carry the bot token;
        if both are present the explicit ``resolved_bot_token`` wins. The
        HTTP client is lazily constructed in :meth:`_ensure_client` unless
        one is injected via ``http_client`` (the typical test path).

        Args:
            config (TelegramConfig | None, optional): Pre-built adapter
                configuration. Defaults to None.
            bot_token_ref (str | None, optional): Reference id for the token
                stored in the secrets manager (audit only). Defaults to None.
            resolved_bot_token (str | None, optional): Raw bot token used
                when ``config`` is omitted or lacks one. Defaults to None.
            sqlite_conn (sqlite3.Connection | None, optional): Connection
                used for topic-name persistence and callback-overflow
                tokenisation. Defaults to None.
            trace (TraceSink | None, optional): Trace sink for adapter
                spans. Defaults to None.
            http_client (httpx.AsyncClient | None, optional): Pre-built HTTP
                client (typically injected for tests). Defaults to None.
            pairing_store (Any | None, optional): DM pairing store for
                ``dm_policy=pairing`` approval checks. Defaults to None.

        Examples:
            >>> adapter = TelegramAdapter(resolved_bot_token="t")
            >>> adapter.name
            'telegram'
            >>> adapter._cfg.bot_token
            't'
        """
        self._token_ref = bot_token_ref
        self._cfg = config or TelegramConfig(
            bot_token=(resolved_bot_token or "").strip(),
        )
        if resolved_bot_token and not self._cfg.bot_token:
            self._cfg = self._cfg.model_copy(update={"bot_token": resolved_bot_token.strip()})
        self._conn = sqlite_conn
        self._trace = trace
        self._external_client = http_client
        self._client_owned = False
        self._poll_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._router: Any = None
        self._seen_updates: OrderedDict[int, None] = OrderedDict()
        self._commands_task: asyncio.Task[None] | None = None
        self._last_update_id: int = 0
        self._reply_keyboard_chats: set[int] = set()
        self._bot_user_id_warned = False
        self._poll_connected = True
        self._last_edit_text: OrderedDict[tuple[int, int], str] = OrderedDict()
        self._dispatch_tasks: set[asyncio.Task[None]] = set()
        self._dispatch_gate = asyncio.Semaphore(_MAX_INFLIGHT_DISPATCH)
        self._pairing_store = pairing_store
        self._rich_capability: RichCapability | None = None

    @property
    def rich_capability(self) -> RichCapability:
        """Cached Bot API 10.1 rich-message capability (D2).

        Returns:
            RichCapability: Last probe verdict; ``NOT_CAPABLE`` before the first probe.

        Examples:
            >>> TelegramAdapter(resolved_bot_token="t").rich_capability
            <RichCapability.NOT_CAPABLE: 'not_capable'>
        """
        return self._rich_capability or RichCapability.NOT_CAPABLE

    def _allowed_updates(self) -> list[str]:
        """Return Bot API ``allowed_updates`` for webhook registration and polling (D7).

        Returns:
            list[str]: Base message/callback updates plus inline types when
            ``channels.telegram.inline.enabled`` (and feedback when enabled).

        Examples:
            >>> TelegramAdapter(resolved_bot_token="t")._allowed_updates()[:2]
            ['message', 'edited_message']
        """
        return telegram_allowed_updates(resolve_inline_config(self._cfg.inline))

    async def _probe_rich_capability(self, *, force: bool = False) -> RichCapability:
        """Probe Bot API 10.1 rich-message support once and cache the verdict (D2).

        Args:
            force (bool, optional): Re-probe even when a cached verdict exists.
                Defaults to ``False``.

        Returns:
            RichCapability: Cached capability verdict.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramAdapter._probe_rich_capability)
            True
        """
        if self._rich_capability is not None and not force:
            return self._rich_capability
        verdict = await detect_rich_support(self._api)
        self._rich_capability = verdict
        return verdict

    @property
    def connected(self) -> bool:
        """Return whether the adapter considers its transport healthy.

        Returns:
            bool: ``False`` after repeated poll connectivity failures.

        Examples:
            >>> TelegramAdapter(resolved_bot_token="t").connected
            True
        """
        return self._poll_connected

    @property
    def name(self) -> str:
        """Channel name for router dispatch.

        Returns:
            str: Always ``telegram``.

        Examples:
            >>> TelegramAdapter(resolved_bot_token="t").name
            'telegram'
        """
        return "telegram"

    def rasterise_caps(self) -> RasteriseCaps:
        """Return Telegram Bot API raster budgets for OpenUI (`specs/29-openui.md` §2.4).

        Values follow product limits documented in PRD §5.7; the adapter owns the
        numbers so the bridge does not hard-code channel-specific caps.

        Returns:
            RasteriseCaps: PNG / PDF byte ceilings and max raster dimension.

        Examples:
            >>> caps = TelegramAdapter(resolved_bot_token="t").rasterise_caps()
            >>> caps.png_max_bytes > 0
            True
        """
        return RasteriseCaps()

    async def _emit_trace(
        self,
        *,
        kind: str,
        status: str,
        attrs: dict[str, object] | None = None,
    ) -> None:
        """Emit one trace event when a sink is configured.

        Args:
            kind (str): Trace kind string (e.g. ``channel.telegram.start``).
            status (str): Status label (``ok``, ``degraded``, …).
            attrs (dict[str, object] | None, optional): Extra span attributes.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramAdapter._emit_trace)
            True
        """
        if self._trace is None:
            return
        now = time_ns()
        await self._trace.emit(
            TraceEvent(
                kind=kind,
                span_id=f"{now:x}",
                parent_span_id=None,
                session_id="",
                turn_id=SYSTEM_TURN_ID,
                tier=None,
                ts_start_ns=now,
                ts_end_ns=now,
                status=status,
                attrs=dict(attrs or {}),
            ),
        )
