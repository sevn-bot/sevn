"""Web UI WebSocket adapter (`specs/19-channel-webui.md`).
Module: sevn.channels.webchat
Depends: sevn.gateway.channel_types, sevn.gateway.web_transport
Exports:
    WebChatConfig — workspace-resolved adapter settings (`specs/19-channel-webui.md` §5).
    WebChatAdapter — translate WS frames ↔ :class:`IncomingMessage` / :class:`OutgoingMessage`.
    webchat_config_from_workspace — build :class:`WebChatConfig` from ``sevn.json``.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_WEBCHAT_JWT_TTL_SECONDS,
    DEFAULT_WEBCHAT_PUBLIC,
    DEFAULT_WEBCHAT_TTS_INLINE,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_types import ChannelAdapter, IncomingMessage, OutgoingMessage

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink
    from sevn.gateway.auth import JWTClaims
    from sevn.gateway.web_transport import WebChannelTransport
VALID_CLIENT_FRAME_TYPES: frozenset[str] = frozenset(
    {"auth", "message", "callback", "file", "ping"},
)


class WebChatConfig(BaseModel):
    """Resolved ``channels.webchat`` settings (`specs/19-channel-webui.md` §5).
    Attributes:
        allowed_origins (list[str]): Permitted ``Origin`` values for WS upgrade.
            Empty list rejects all cross-origin upgrades (loopback / same-origin
            documented for dev).
        public (bool): Issue anonymous JWT bound to a server-generated
            ``client_id`` for dev / testing. Production single-owner installs
            keep this ``False``.
        tts_inline (bool): Emit ``audio`` frames inline alongside text replies.
        jwt_ttl_seconds (int): Lifetime of webchat-scoped JWTs.
    """

    model_config = ConfigDict(extra="ignore")
    allowed_origins: list[str] = Field(default_factory=list)
    public: bool = Field(default=DEFAULT_WEBCHAT_PUBLIC)
    tts_inline: bool = Field(default=DEFAULT_WEBCHAT_TTS_INLINE)
    jwt_ttl_seconds: int = Field(default=DEFAULT_WEBCHAT_JWT_TTL_SECONDS, ge=1)


def webchat_config_from_workspace(workspace: WorkspaceConfig) -> WebChatConfig:
    """Materialise :class:`WebChatConfig` from ``channels.webchat`` (`specs/19-channel-webui.md` §5).
    Args:
        workspace (WorkspaceConfig): Validated workspace config.
    Returns:
        WebChatConfig: Defaults applied when the subtree is missing or partial.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> webchat_config_from_workspace(WorkspaceConfig.minimal()).public
        False
    """
    ch = workspace.channels
    wc = ch.webchat if ch is not None else None
    if wc is None:
        return WebChatConfig()
    origins = [o for o in (wc.allowed_origins or []) if isinstance(o, str) and o.strip()]
    public = bool(wc.public) if wc.public is not None else DEFAULT_WEBCHAT_PUBLIC
    tts_inline = bool(wc.tts_inline) if wc.tts_inline is not None else DEFAULT_WEBCHAT_TTS_INLINE
    ttl = int(wc.jwt_ttl_seconds) if wc.jwt_ttl_seconds else DEFAULT_WEBCHAT_JWT_TTL_SECONDS
    return WebChatConfig(
        allowed_origins=[o.strip() for o in origins],
        public=public,
        tts_inline=tts_inline,
        jwt_ttl_seconds=ttl,
    )


class WebChatAdapter(ChannelAdapter):
    """Owner WebSocket channel adapter (`specs/19-channel-webui.md`).
    The adapter never talks to :class:`~sevn.gateway.session_manager.SessionManager`
    directly. Inbound WS frames pass through :meth:`ingest_ws_frame` which
    returns an :class:`IncomingMessage` for the router pipeline; outbound
    deliveries are fanned-out by :meth:`send` through the gateway-owned
    :class:`~sevn.gateway.web_transport.WebChannelTransport` registry.
    The HTTP webhook contract is intentionally unused — :meth:`parse_webhook`
    always returns ``None``.
    Examples:
        >>> WebChatAdapter().name
        'webchat'
    """

    def __init__(
        self,
        *,
        transport: WebChannelTransport | None = None,
        config: WebChatConfig | None = None,
        trace: TraceSink | None = None,
    ) -> None:
        """Bind the adapter to its outbound transport.
        Args:
            transport (WebChannelTransport | None): Connection registry; when
                ``None``, :meth:`send` becomes a no-op (Phase 0 boot before the
                gateway wires the registry).
            config (WebChatConfig | None): Resolved channel config; the adapter
                only needs ``tts_inline`` for outbound frame shaping in this
                slice.
            trace (TraceSink | None): Optional gateway trace sink for lifecycle spans.
        Returns:
            None: Constructor.
        Examples:
            >>> from sevn.gateway.web_transport import WebChannelTransport
            >>> WebChatAdapter(transport=WebChannelTransport()).name
            'webchat'
        """
        self._transport = transport
        self._config = config or WebChatConfig()
        self._trace = trace

    @property
    def name(self) -> str:
        """Return the channel adapter name.
        Returns:
            str: Stable adapter key ``"webchat"`` used by the gateway router.
        Examples:
            >>> WebChatAdapter().name
            'webchat'
        """
        return "webchat"

    @property
    def transport(self) -> WebChannelTransport | None:
        """Return the bound outbound transport registry (or ``None``).
        Returns:
            WebChannelTransport | None: Transport when registered, else ``None``.
        Examples:
            >>> WebChatAdapter().transport is None
            True
        """
        return self._transport

    async def _emit_lifecycle_trace(self, *, kind: str, status: str = "ok") -> None:
        """Emit a channel lifecycle trace row when a sink is configured.

        Args:
            kind (str): Span kind (``channel.webchat.start`` / ``stop``).
            status (str): Span status label.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(WebChatAdapter._emit_lifecycle_trace)
            True
        """
        if self._trace is None:
            return
        import time
        import uuid as _uuid

        now = time.time_ns()
        from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent

        await self._trace.emit(
            TraceEvent(
                kind=kind,
                span_id=_uuid.uuid4().hex,
                parent_span_id=None,
                session_id="",
                turn_id=SYSTEM_TURN_ID,
                tier=None,
                ts_start_ns=now,
                ts_end_ns=now,
                status=status,
                attrs={},
            ),
        )

    async def start(self, router: object) -> None:
        """Record webchat adapter start (`channel.webchat.start` span).

        Args:
            router (object): Owning gateway router (unused for WS-only adapter).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(WebChatAdapter.start)
            True
        """
        _ = router
        await self._emit_lifecycle_trace(kind="channel.webchat.start", status="ok")

    async def stop(self) -> None:
        """Record webchat adapter stop (`channel.webchat.stop` span).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(WebChatAdapter.stop)
            True
        """
        await self._emit_lifecycle_trace(kind="channel.webchat.stop", status="ok")

    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """No HTTP webhook envelope (`specs/19-channel-webui.md` §2.1).
        Web UI traffic enters through the WebSocket handler which calls
        :meth:`ingest_ws_frame`; the HTTP webhook contract is intentionally
        unused.
        Args:
            payload (dict[str, Any]): Ignored webhook payload.
        Returns:
            IncomingMessage | None: Always ``None``.
        Examples:
            >>> WebChatAdapter().parse_webhook({}) is None
            True
            >>> WebChatAdapter().parse_webhook({"message": {"text": "hi"}}) is None
            True
        """
        _ = payload
        return None

    def ingest_ws_frame(
        self,
        frame: dict[str, Any],
        *,
        claims: JWTClaims,
        client_id: str | None = None,
        expected_session_id: str | None = None,
    ) -> IncomingMessage | None:
        """Map a client WS frame to :class:`IncomingMessage` (`specs/19-channel-webui.md` §2.6).
        Unknown ``type`` discriminators yield ``None`` — the gateway WS handler
        responds with an ``error`` frame and keeps the socket open.
        Supported mappings:
        - ``message`` → :class:`IncomingMessage` with ``text`` body.
        - ``callback`` → :class:`IncomingMessage` with ``metadata.is_callback``
          set and ``metadata.callback_data`` mirroring the Telegram dispatcher
          contract (`specs/18-channel-telegram.md`).
        - ``file`` → :class:`IncomingMessage` carrying an ``upload_id``-only
          attachment descriptor; the gateway resolves bytes via
          :class:`~sevn.gateway.media_store.MediaStore`.
        ``auth`` and ``ping`` are control frames consumed by the gateway WS
        handler and never produce an :class:`IncomingMessage`.
        Routing uses a stable per-subscriber scope key ``webchat:{claims.sub}``
        so :meth:`~sevn.gateway.session_manager.SessionManager.ensure_session`
        always resolves the same durable session while the client-supplied
        ``session_id`` field is checked against ``expected_session_id`` (the
        value sent in the ``ready`` frame) to detect forged ids.
        Args:
            frame (dict[str, Any]): Decoded JSON object.
            claims (JWTClaims): Verified webchat JWT claims for the connection.
            client_id (str | None): Connection identifier (anonymous WS client).
            expected_session_id (str | None): Post-auth gateway session id; when
                set, ``frame["session_id"]`` must match or this returns ``None``.
        Returns:
            IncomingMessage | None: Router-ready message or ``None`` when the
            frame type is control / unknown.
        Examples:
            >>> from sevn.gateway.auth import JWTClaims
            >>> claims = JWTClaims(sub="u1", aud="webchat", exp=10, scope=())
            >>> WebChatAdapter().ingest_ws_frame(
            ...     {"type": "message", "text": "hello", "session_id": "s1"},
            ...     claims=claims,
            ...     expected_session_id="s1",
            ... ).text
            'hello'
        """
        if not isinstance(frame, dict):
            return None
        frame_type = frame.get("type")
        if frame_type not in VALID_CLIENT_FRAME_TYPES:
            return None
        if frame_type in {"auth", "ping"}:
            return None
        session_id = frame.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        session_id = session_id.strip()
        if expected_session_id is not None and session_id != expected_session_id:
            return None
        scope_key = f"webchat:{claims.sub}"
        common_metadata: dict[str, Any] = {
            "session_scope_override": scope_key,
            "webchat_session_id": session_id,
        }
        if client_id:
            common_metadata["client_id"] = client_id
        if frame_type == "message":
            text = frame.get("text")
            if not isinstance(text, str):
                return None
            return IncomingMessage(
                channel="webchat",
                user_id=claims.sub,
                text=text,
                raw=dict(frame),
                metadata=common_metadata,
            )
        if frame_type == "callback":
            data = frame.get("data")
            if not isinstance(data, str) or not data:
                return None
            md = dict(common_metadata)
            md["is_callback"] = True
            md["callback_data"] = data
            md["callback_query_id"] = frame.get("callback_query_id")
            return IncomingMessage(
                channel="webchat",
                user_id=claims.sub,
                text=data,
                raw=dict(frame),
                metadata=md,
            )
        if frame_type == "file":
            upload_id = frame.get("upload_id")
            if not isinstance(upload_id, str) or not upload_id:
                return None
            filename = frame.get("filename") if isinstance(frame.get("filename"), str) else None
            attachment: dict[str, Any] = {
                "upload_id": upload_id,
                "filename": filename or upload_id,
                "source": "webchat",
            }
            return IncomingMessage(
                channel="webchat",
                user_id=claims.sub,
                text="",
                raw=dict(frame),
                attachments=[attachment],
                metadata=common_metadata,
            )
        return None

    async def send(self, message: OutgoingMessage) -> list[str]:
        """Fan-out an :class:`OutgoingMessage` to subscribed WS connections.
        Frames emitted (`specs/19-channel-webui.md` §2.2, §2.7):
        - ``message`` — when ``text`` is non-empty.
        - ``openui`` — when ``metadata.openui_iframe_src`` or
          ``metadata.openui_html`` is set.
        - ``audio`` — when ``metadata.tts_audio_path`` is set.
        Each emitted frame increments the synthetic platform id list returned
        to the router for ``platform_message_index`` bookkeeping.
        Args:
            message (OutgoingMessage): Outbound message produced by the router.
        Returns:
            list[str]: Synthetic platform ids (UUID strings) per emitted frame.
        Examples:
            >>> import asyncio
            >>> from sevn.gateway.channel_router import OutgoingMessage
            >>> adapter = WebChatAdapter()
            >>> asyncio.run(
            ...     adapter.send(
            ...         OutgoingMessage(
            ...             channel="webchat",
            ...             user_id="u1",
            ...             text="hi",
            ...             session_id="s1",
            ...         ),
            ...     )
            ... )
            []
        """
        session_id = message.session_id.strip() if isinstance(message.session_id, str) else ""
        if not session_id:
            return []
        transport = self._transport
        if transport is None or transport.session_count(session_id) == 0:
            return []
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        platform_ids: list[str] = []
        if message.text:
            mid = uuid.uuid4().hex
            frame: dict[str, object] = {
                "type": "message",
                "text": message.text,
                "session_id": session_id,
                "message_id": mid,
            }
            gw_mid = metadata.get("gateway_assistant_message_id")
            if gw_mid is not None:
                frame["gateway_message_id"] = int(gw_mid)
            await transport.send_to_session(
                session_id,
                json.dumps(frame, ensure_ascii=False),
            )
            platform_ids.append(mid)
        iframe_src = metadata.get("openui_iframe_src")
        openui_html = metadata.get("openui_html")
        if isinstance(iframe_src, str) and iframe_src.strip():
            mid = uuid.uuid4().hex
            await transport.send_to_session(
                session_id,
                json.dumps(
                    {
                        "type": "openui",
                        "session_id": session_id,
                        "iframe_src": iframe_src.strip(),
                        "title": metadata.get("openui_title") or "",
                        "safe_origin": metadata.get("openui_safe_origin") or "",
                        "message_id": mid,
                    },
                    ensure_ascii=False,
                ),
            )
            platform_ids.append(mid)
        elif isinstance(openui_html, str) and openui_html:
            mid = uuid.uuid4().hex
            await transport.send_to_session(
                session_id,
                json.dumps(
                    {
                        "type": "openui",
                        "session_id": session_id,
                        "html": openui_html,
                        "title": metadata.get("openui_title") or "",
                        "safe_origin": metadata.get("openui_safe_origin") or "",
                        "message_id": mid,
                    },
                    ensure_ascii=False,
                ),
            )
            platform_ids.append(mid)
        tts_path = metadata.get("tts_audio_path")
        if isinstance(tts_path, str) and tts_path and self._config.tts_inline:
            mid = uuid.uuid4().hex
            await transport.send_to_session(
                session_id,
                json.dumps(
                    {
                        "type": "audio",
                        "session_id": session_id,
                        "url": tts_path,
                        "message_id": mid,
                    },
                    ensure_ascii=False,
                ),
            )
            platform_ids.append(mid)
        return platform_ids


__all__ = [
    "VALID_CLIENT_FRAME_TYPES",
    "WebChatAdapter",
    "WebChatConfig",
    "webchat_config_from_workspace",
]
