"""Leaf channel message types and adapter contract (`specs/17-gateway.md` §2.2).

Module: sevn.gateway.channel_types
Depends: abc, dataclasses, typing

Exports:
    IncomingMessage — normalised inbound webhook payload shape.
    OutgoingMessage — adapter-bound outbound send shape.
    ChannelAdapter — webhook parse + send contract for channel adapters.

This module is intentionally free of Telegram, router, and security imports so
channel adapters can depend on it without re-entering
:mod:`sevn.gateway.channel_router` during package initialisation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncomingMessage:
    """Normalised inbound envelope shared across channel adapters.

    Attributes:
        channel: Adapter key (``telegram``, ``webchat``, etc.).
        user_id: Channel-specific user identifier as a string.
        text: Decoded text body (empty for media-only updates).
        raw: Original adapter payload preserved for debugging.
        attachments: Per-attachment descriptors as plain dicts.
        metadata: Adapter-side routing hints (chat_id, topic_id, ...).

    Examples:
        >>> IncomingMessage(channel="telegram", user_id="1", text="hi").text
        'hi'
    """

    channel: str
    user_id: str
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """Adapter-bound outbound envelope produced by the gateway.

    Attributes:
        channel: Target adapter key.
        user_id: Destination user identifier.
        text: Sanitised reply text after hygiene filters.
        session_id: Gateway session id this reply belongs to.
        metadata: Optional adapter routing hints (chat_id, reply ids, ...).

    Examples:
        >>> OutgoingMessage(channel="webchat", user_id="u1", text="ok").session_id
        ''
    """

    channel: str
    user_id: str
    text: str
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(ABC):
    """Translates provider payloads to :class:`IncomingMessage` / :class:`OutgoingMessage`.

    Concrete adapters (Telegram, WebChat, ...) implement webhook parsing, outbound
    delivery, and optional polling loops so the gateway can drive them uniformly.

    Examples:
        >>> class _Stub(ChannelAdapter):
        ...     @property
        ...     def name(self) -> str:
        ...         return "stub"
        ...     def parse_webhook(self, payload):
        ...         return None
        ...     async def send(self, message):
        ...         return []
        >>> _Stub().name
        'stub'
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable adapter key matching ``routes["/webhook/{channel}"]``.

        Returns:
            str: Lowercase adapter identifier.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelAdapter.name.fget)
            True
        """

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
        """Return ``None`` when the webhook should be ignored.

        Args:
            payload (dict[str, Any]): Decoded webhook JSON body.

        Returns:
            IncomingMessage | None: Normalised envelope or ``None`` to skip.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ChannelAdapter.parse_webhook)
            True
        """

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> list[str]:
        """Deliver chunks outward; implementation records transport ids.

        Args:
            message (OutgoingMessage): Sanitised envelope from the router.

        Returns:
            list[str]: Provider message ids for each sent chunk.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelAdapter.send)
            True
        """

    async def start(self, router: Any) -> None:
        """Optional poll loops.

        Args:
            router (Any): The owning :class:`ChannelRouter` instance.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelAdapter.start)
            True
        """
        _ = router
        return

    async def stop(self) -> None:
        """Idempotent adapter shutdown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelAdapter.stop)
            True
        """
        return

    async def edit_text(
        self,
        *,
        channel_message_id: str,
        new_text: str,
        metadata: dict[str, Any] | None = None,
        send_split_followups: bool = True,
    ) -> bool:
        """Replace the text of a previously delivered message (``PROBLEMS.md`` Priority 2).

        Default implementation returns ``False`` to mean "edit not supported on
        this adapter"; callers (see :class:`sevn.gateway.turn.turn_finalizer.TierBAnswerFinalizer`)
        fall back to sending a new message in that case. Adapters that support
        in-place edits (Telegram via ``editMessageText``, future WebChat WS
        update broadcasts) override this method.

        Args:
            channel_message_id (str): The provider id captured from a prior
                :meth:`send` return.
            new_text (str): Replacement text body.
            metadata (dict[str, Any] | None): Optional routing hints (chat_id,
                topic_id, …) — same shape adapters use in :class:`OutgoingMessage`.
            send_split_followups (bool): Telegram-only; ignored by default impl.

        Returns:
            bool: ``True`` when the edit was successfully applied on the
            provider; ``False`` when the adapter doesn't support edits (caller
            falls back to a fresh send).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ChannelAdapter.edit_text)
            True
        """
        _ = (channel_message_id, new_text, metadata, send_split_followups)
        return False
