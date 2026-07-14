"""Gateway command / callback short-circuit (`specs/17-gateway.md` §2.4).
Module: sevn.gateway.commands.dispatcher
Depends: sevn.gateway.channel_router, sevn.gateway.commands.registry, sevn.gateway.util.strings
Exports:
    CommandDispatcher — ``try_dispatch`` registry-driven bypass and optional bypass toasts.
"""

from __future__ import annotations

import shlex
import time
import uuid
from time import time_ns
from typing import TYPE_CHECKING

from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.gateway.commands.registry import DEFAULT_COMMAND_SPECS, CommandSpec
from sevn.gateway.queue.steer_store import SessionSteerStore, parse_steer_command_text
from sevn.gateway.util.strings import (
    CALLBACK_AUTH_BLOCKED_TOAST,
    STEER_ACK_V1,
    STEER_BUFFER_FULL_V1,
    STEER_NOT_AVAILABLE_V1,
    STEER_NOT_OWNER_V1,
    STEER_USAGE_V1,
)
from sevn.plugins.command_spec import PluginSlashBinding
from sevn.plugins.hook import HookContext

if TYPE_CHECKING:
    from sevn.gateway.channel_router import IncomingMessage


class CommandDispatcher:
    """Normative bypass for slash commands and callback namespaces."""

    def __init__(
        self,
        specs: tuple[CommandSpec, ...] | None = None,
        *,
        plugin_slash: tuple[PluginSlashBinding, ...] = (),
        steer_store: SessionSteerStore | None = None,
    ) -> None:
        """Build a dispatcher from core specs plus optional plugin slash rows.
        Args:
            specs (tuple[CommandSpec, ...] | None): Custom matchers; ``None``
                uses :data:`DEFAULT_COMMAND_SPECS`.
            plugin_slash (tuple[PluginSlashBinding, ...]): Plugin-owned slash patterns
                (`specs/34-plugin-hooks.md` §2.2).
            steer_store (SessionSteerStore | None): Session-scoped ``/steer`` buffer
                (`specs/17-gateway.md` Wave 7).
        Examples:
            >>> CommandDispatcher() is not None
            True
        """
        self._specs = specs if specs is not None else DEFAULT_COMMAND_SPECS
        self._plugin_slash = plugin_slash
        self._steer_store = steer_store

    def callback_auth_blocked_user_toast(self) -> str:
        """Return copy for callback authorization denials (`specs/17-gateway.md` §8).
        Returns:
            str: Stable English v1 string from :mod:`sevn.gateway.util.strings`.
        Examples:
            >>> CommandDispatcher().callback_auth_blocked_user_toast()
            'You are not allowed to use this action.'
        """
        return CALLBACK_AUTH_BLOCKED_TOAST

    def bypass_reply_text(
        self,
        msg: IncomingMessage,
        *,
        session_id: str | None = None,
        is_owner: bool = False,
    ) -> str | None:
        """User-visible follow-up for some bypassed commands (English v1).
        Args:
            msg (IncomingMessage): Same inbound message that matched ``try_dispatch``.
            session_id (str | None): Owning session when steer enqueue is required.
            is_owner (bool): Whether ``msg`` originated from the workspace owner.
        Returns:
            str | None: Short reply text to send on the channel adapter, or ``None``.
        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> d = CommandDispatcher()
            >>> d.bypass_reply_text(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/steer"),
            ... ) == STEER_NOT_AVAILABLE_V1
            True
        """
        text_raw = msg.text or ""
        text = text_raw.strip() if isinstance(text_raw, str) else ""
        if text == "/steer" or text.startswith("/steer "):
            return self._steer_bypass_reply(
                text,
                session_id=session_id,
                is_owner=is_owner,
            )
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cb = md.get("callback_data")
        if isinstance(cb, str) and cb.startswith(("menu:", "nav:")):
            return None
        return None

    def _steer_bypass_reply(
        self,
        text: str,
        *,
        session_id: str | None,
        is_owner: bool,
    ) -> str:
        """Return user-visible copy for an owner ``/steer`` bypass.
        Args:
            text (str): Normalised inbound command text.
            session_id (str | None): Owning session id for enqueue.
            is_owner (bool): Whether the sender may steer.
        Returns:
            str: Ack, usage, or rejection copy.
        Examples:
            >>> from sevn.gateway.queue.steer_store import SessionSteerStore
            >>> store = SessionSteerStore()
            >>> CommandDispatcher(steer_store=store)._steer_bypass_reply(
            ...     "/steer", session_id="s", is_owner=True,
            ... )
            'Usage: /steer <text>'
        """
        if self._steer_store is None or session_id is None:
            return STEER_NOT_AVAILABLE_V1
        if not is_owner:
            return STEER_NOT_OWNER_V1
        payload = parse_steer_command_text(text)
        if payload is None:
            return STEER_USAGE_V1
        result = self._steer_store.enqueue(session_id, payload)
        if result.buffer_full:
            return STEER_BUFFER_FULL_V1
        if result.accepted:
            return STEER_ACK_V1
        return STEER_USAGE_V1

    def _plugin_slash_matches(self, msg: object) -> PluginSlashBinding | None:
        """Return the first plugin binding that matches inbound ``text``.
        Args:
            msg (object): Duck-typed inbound message.
        Returns:
            PluginSlashBinding | None: Match descriptor or ``None``.
        Examples:
            >>> CommandDispatcher()._plugin_slash_matches(type("M", (), {"text": "/x"})()) is None
            True
        """
        t = getattr(msg, "text", "") or ""
        if not isinstance(t, str):
            return None
        text = t.strip()
        for b in self._plugin_slash:
            pat = b.command.pattern
            if text == pat or text.startswith(f"{pat} "):
                return b
        return None

    def try_dispatch(self, msg: IncomingMessage) -> bool:
        """Return ``True`` when scanner + Triager must be skipped.
        Args:
            msg (IncomingMessage): Normalised inbound message.
        Returns:
            bool: ``True`` when a registered spec matches.
        Examples:
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> CommandDispatcher().try_dispatch(
            ...     IncomingMessage(channel="webchat", user_id="u1", text="/help"),
            ... )
            True
            >>> CommandDispatcher().try_dispatch(
            ...     IncomingMessage(channel="webchat", user_id="u1", text="/unknown"),
            ... )
            False
        """
        for spec in self._specs:
            try:
                matched = spec.matcher(msg)
            except Exception:
                matched = False
            if matched:
                return True
        return self._plugin_slash_matches(msg) is not None

    async def dispatch_plugin_slash_if_any(
        self,
        msg: IncomingMessage,
        hook_ctx: HookContext,
        trace: TraceSink | None,
    ) -> str | None:
        """Invoke ``dispatch_tool`` when this message matched a plugin slash row.
        Args:
            msg (IncomingMessage): Inbound user message.
            hook_ctx (HookContext): Hook runtime context.
            trace (TraceSink | None): Optional trace sink.
        Returns:
            str | None: User-visible reply text, or ``None`` to fall back to core bypass toasts.
        Examples:
            >>> import asyncio
            >>> from sevn.gateway.channel_router import IncomingMessage
            >>> from sevn.plugins.hook import HookContext
            >>> async def _demo():
            ...     d = CommandDispatcher()
            ...     ctx = HookContext(
            ...         workspace_id="w",
            ...         session_id="s",
            ...         turn_id="t",
            ...         tier="B",
            ...         correlation_id="c",
            ...     )
            ...     return await d.dispatch_plugin_slash_if_any(
            ...         IncomingMessage(channel="telegram", user_id="u", text="/unknown"),
            ...         ctx,
            ...         None,
            ...     )
            >>> asyncio.run(_demo()) is None
            True
        """
        bind = self._plugin_slash_matches(msg)
        if bind is None:
            return None
        raw_t = msg.text or ""
        if not isinstance(raw_t, str):
            return None
        text = raw_t.strip()
        body = text[len(bind.command.pattern) :].lstrip()
        try:
            tokens = shlex.split(body, posix=True) if body else []
        except ValueError:
            tokens = []
        t0 = time.perf_counter()
        try:
            out = await bind.hook.dispatch_tool(bind.command.dispatch_key, tokens, hook_ctx)
        except Exception as exc:
            logger.exception("plugin dispatch_tool failed key={}", bind.command.dispatch_key)
            if trace is not None:
                await trace.emit(
                    TraceEvent(
                        kind="plugin.hook.error",
                        span_id=str(uuid.uuid4()),
                        parent_span_id=None,
                        session_id=hook_ctx.session_id,
                        turn_id=hook_ctx.turn_id,
                        tier=hook_ctx.tier,
                        ts_start_ns=time_ns(),
                        ts_end_ns=time_ns(),
                        status="error",
                        attrs={"plugin.name": bind.hook.name, "exc_type": type(exc).__name__},
                    ),
                )
            return f"plugin command error ({type(exc).__name__})"
        ms = int((time.perf_counter() - t0) * 1000)
        if trace is not None:
            await trace.emit(
                TraceEvent(
                    kind="plugin.hook.dispatch_tool",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=None,
                    session_id=hook_ctx.session_id,
                    turn_id=hook_ctx.turn_id,
                    tier=hook_ctx.tier,
                    ts_start_ns=time_ns(),
                    ts_end_ns=time_ns(),
                    status="ok",
                    attrs={
                        "plugin.name": bind.hook.name,
                        "command": bind.command.pattern,
                        "duration_ms": ms,
                    },
                ),
            )
        if out is None:
            return None
        return out if isinstance(out, str) else repr(out)
