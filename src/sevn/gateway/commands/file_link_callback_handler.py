"""Dispatch ``sf:<path>`` Telegram callbacks to ``send_file`` without an LLM round.

When tier-B drops a ``[📎 send: <path>]`` marker, the Telegram outbound layer
turns it into an inline button whose ``callback_data`` is ``sf:<path>`` (or a
``ds:`` overflow token expanding to the same). Pressing the button generates a
``callback_query`` update; this handler intercepts those callbacks at the
gateway layer (alongside menu / config / form handlers) and ships the file
directly via ``ChannelRouter.route_outgoing`` with the attachment metadata that
``sevn.tools.outbound.send_file_tool`` already understands.

Module: sevn.gateway.commands.file_link_callback_handler
Depends: sevn.channels.telegram_file_links, sevn.gateway.channel_router,
    sevn.tools.outbound

Exports:
    FileLinkCallbackHandler — ``matches`` / ``handle`` dispatch pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.channels.telegram_file_links import (
    FILE_LINK_CALLBACK_PREFIX,
    parse_file_link_callback,
)

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter, IncomingMessage


@dataclass
class FileLinkCallbackHandler:
    """Intercept ``sf:<path>`` callbacks and deliver the file inline.

    Attributes:
        router (ChannelRouter): Gateway channel router for outbound delivery.
        content_root (Path): Workspace content root for path resolution.

    Examples:
        >>> from dataclasses import is_dataclass
        >>> is_dataclass(FileLinkCallbackHandler)
        True
    """

    router: ChannelRouter
    content_root: Path

    def matches(self, msg: IncomingMessage) -> bool:
        """Return ``True`` when ``msg`` is an inbound ``sf:`` callback.

        Args:
            msg (IncomingMessage): Inbound envelope.

        Returns:
            bool: Whether this handler should claim the message.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(FileLinkCallbackHandler.matches)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        if not md.get("is_callback"):
            return False
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        return isinstance(raw, str) and raw.startswith(FILE_LINK_CALLBACK_PREFIX)

    async def handle(self, msg: IncomingMessage, *, session_id: str) -> str | None:
        """Resolve the path on the callback and deliver the file.

        Args:
            msg (IncomingMessage): Inbound callback envelope.
            session_id (str): Active gateway session id.

        Returns:
            str | None: Optional toast string for the gateway to surface to
            the user. Returns ``None`` on success (the file itself replies).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(FileLinkCallbackHandler.handle)
            True
        """
        md = msg.metadata if isinstance(msg.metadata, dict) else {}
        raw = md.get("callback_data")
        if not isinstance(raw, str):
            raw = msg.text or ""
        rel_path = parse_file_link_callback(str(raw))
        if not rel_path:
            return None
        # Resolve and guard against escaping the workspace.
        target = (self.content_root / rel_path).resolve()
        try:
            target.relative_to(self.content_root.resolve())
        except ValueError:
            return "That file is outside the workspace."
        if not target.is_file():
            return f"File not found: {rel_path}"

        # Mirror send_file_tool's attachment metadata so adapters dispatch
        # the right Telegram method (document / photo / audio / video).
        from sevn.tools.outbound import _attachment_kind, _guess_mime

        attachment_meta: dict[str, Any] = {
            "attachment_path": str(target),
            "attachment_filename": target.name,
            "attachment_mime": _guess_mime(target),
            "attachment_kind": _attachment_kind(target),
        }
        # Carry over inbound routing hints (chat_id, topic_id, …) so the file
        # lands in the same chat as the button press.
        for key in (
            "chat_id",
            "topic_id",
            "telegram_thread_id",
            "telegram_chat_id",
            "callback_query_id",
        ):
            if key in md and md[key] is not None:
                attachment_meta[key] = md[key]

        from sevn.gateway.channel_router import OutgoingMessage

        try:
            await self.router.route_outgoing(
                OutgoingMessage(
                    channel=msg.channel,
                    user_id=msg.user_id,
                    text="",
                    session_id=session_id,
                    metadata=attachment_meta,
                ),
            )
        except Exception:
            logger.exception(
                "file_link_callback_send_failed channel={} path={}",
                msg.channel,
                rel_path,
            )
            return "Sorry — I couldn't send that file."
        return None


__all__ = ["FileLinkCallbackHandler"]
