"""Execute core slash handlers from Telegram menu button contexts (TMF Wave 2).

Module: sevn.gateway.commands.menu_command_invoke
Depends: sevn.gateway.channel_router, sevn.gateway.commands.core_commands,
    sevn.gateway.menu.menu

Exports:
    MenuCommandInvoker — dispatch ``cfg:help:cmd:*`` / ``menu:cmd:*`` to slash handlers.
    is_dashboard_pin_message — detect callbacks on a registered dashboard pin message.

Examples:
    >>> from sevn.gateway.commands.menu_command_invoke import MenuCommandInvoker
    >>> MenuCommandInvoker.__name__
    'MenuCommandInvoker'
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
    from sevn.gateway.commands.core_commands import CoreCommandHandler
    from sevn.gateway.menu.menu import ConfigMenuHandler, MenuCallbackHandler

from sevn.gateway.channel_router import IncomingMessage, OutgoingMessage, _telegram_reply_metadata

_MENU_COMMANDS = frozenset({"help", "menu", "new", "voice", "model", "status", "stop", "config"})


def is_dashboard_pin_message(router: ChannelRouter, msg: IncomingMessage) -> bool:
    """Return whether the callback originated from a registered dashboard pin message.

    Args:
        router (ChannelRouter): Gateway router carrying ``_telegram_dashboard_pins``.
        msg (IncomingMessage): Inbound callback envelope.

    Returns:
        bool: ``True`` when ``message_id`` matches a stored pin id.

    Examples:
        >>> from sevn.gateway.channel_router import IncomingMessage
        >>> class _PinRouter:
        ...     _telegram_dashboard_pins = {"telegram:1:0": 42}
        >>> is_dashboard_pin_message(
        ...     _PinRouter(),  # type: ignore[arg-type]
        ...     IncomingMessage(
        ...         channel="telegram",
        ...         user_id="1",
        ...         text="",
        ...         metadata={"message_id": 42},
        ...     ),
        ... )
        True
    """
    md = msg.metadata if isinstance(msg.metadata, dict) else {}
    message_id = md.get("message_id")
    if not isinstance(message_id, int):
        return False
    pins = getattr(router, "_telegram_dashboard_pins", None)
    if not isinstance(pins, dict):
        return False
    return message_id in pins.values()


class MenuCommandInvoker:
    """Run slash-command handlers from inline menu / help / pin button presses."""

    def __init__(
        self,
        *,
        router: ChannelRouter,
        core_handler: CoreCommandHandler,
        config_menu_handler: ConfigMenuHandler,
        menu_handler: MenuCallbackHandler,
    ) -> None:
        """Bind router and slash handlers used for menu command dispatch.

        Args:
            router (ChannelRouter): Gateway router (adapter lookup + pin registry).
            core_handler (CoreCommandHandler): Option-B core slash handler.
            config_menu_handler (ConfigMenuHandler): ``/config`` menu opener.
            menu_handler (MenuCallbackHandler): ``/menu`` recovery opener.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MenuCommandInvoker.__init__)
            True
        """
        self._router = router
        self._core_handler = core_handler
        self._config_menu_handler = config_menu_handler
        self._menu_handler = menu_handler

    async def invoke(
        self,
        msg: IncomingMessage,
        *,
        session_id: str,
        command: str,
    ) -> None:
        """Execute ``command`` with the same outcome as typing the matching slash.

        Opens ``/menu`` or ``/config`` via their menu handlers; other commands run
        through :class:`CoreCommandHandler` and send a **new** chat message (never
        edit-in-place on pin or menu surfaces).

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            session_id (str): Active gateway session id.
            command (str): Command name without leading ``/`` (e.g. ``help``).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MenuCommandInvoker.invoke)
            True
        """
        cmd = command.strip().lower()
        if cmd not in _MENU_COMMANDS:
            return
        adapter = self._router._adapters.get(msg.channel)
        if adapter is None:
            return
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        cq_id = md.get("callback_query_id")
        if isinstance(cq_id, str) and cq_id.strip():
            await _answer_callback_query(adapter, callback_query_id=cq_id.strip())
        if cmd == "menu":
            await self._menu_handler.handle_slash(msg, session_id=session_id)
            return
        if cmd == "config":
            await self._config_menu_handler.handle_slash(msg, session_id=session_id)
            return
        synth = IncomingMessage(
            channel=msg.channel,
            user_id=msg.user_id,
            text=f"/{cmd}",
            metadata=dict(_telegram_reply_metadata(msg)),
        )
        reply = await self._core_handler.handle(synth, session_id=session_id)
        if not reply:
            return
        out_meta = dict(_telegram_reply_metadata(msg))
        if not is_dashboard_pin_message(self._router, msg):
            mid = md.get("message_id")
            if isinstance(mid, int):
                out_meta["reply_to_message_id"] = mid
        await adapter.send(
            OutgoingMessage(
                channel=msg.channel,
                user_id=msg.user_id,
                text=reply,
                session_id=session_id,
                metadata=out_meta,
            ),
        )


async def _answer_callback_query(
    adapter: object,
    *,
    callback_query_id: str,
) -> bool:
    """Acknowledge a Telegram callback query without a toast hint.

    Args:
        adapter (object): Channel adapter (``TelegramAdapter`` in production).
        callback_query_id (str): Telegram callback query id.

    Returns:
        bool: ``True`` when the API reports success.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_answer_callback_query)
        True
    """
    if not callback_query_id.strip():
        return False
    answer_fn = getattr(adapter, "answer_callback_query", None)
    if callable(answer_fn):
        return bool(
            await cast("Callable[..., Awaitable[Any]]", answer_fn)(
                callback_query_id=callback_query_id,
            ),
        )
    api = getattr(adapter, "_api", None)
    if not callable(api):
        return False
    result = await cast("Callable[..., Awaitable[Any]]", api)(
        "answerCallbackQuery",
        {"callback_query_id": callback_query_id},
    )
    return bool(result)


__all__ = ["MenuCommandInvoker", "is_dashboard_pin_message"]
