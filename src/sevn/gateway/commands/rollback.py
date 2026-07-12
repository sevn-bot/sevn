"""``/rollback`` slash command stub (checkpoint restore not yet implemented).

Module: sevn.gateway.commands.rollback
Depends: sevn.gateway.channel_router

Exports:
    RollbackCommandHandler — matches ``/rollback`` and returns stub reply.
"""

from __future__ import annotations

from sevn.gateway.channel_router import IncomingMessage

_ROLLBACK_STUB_REPLY = (
    "Checkpoint rollback is not yet available in this build. "
    "Use /new to start a fresh session, or restore from a saved MEMORY.md snapshot."
)


class RollbackCommandHandler:
    """Stub handler for the ``/rollback`` slash command.

    Returns an informational reply; full checkpoint restore lands in a future wave
    once the checkpoint store (F1.2 completion) is shipped.

    Examples:
        >>> h = RollbackCommandHandler()
        >>> h.matches_slash(IncomingMessage(channel="telegram", user_id="1", text="/rollback"))
        True
        >>> h.matches_slash(IncomingMessage(channel="telegram", user_id="1", text="/new"))
        False
    """

    def matches_slash(self, msg: IncomingMessage) -> bool:
        """Return ``True`` when ``msg`` is the ``/rollback`` command.

        Args:
            msg (IncomingMessage): Inbound message.

        Returns:
            bool: Match verdict.

        Examples:
            >>> h = RollbackCommandHandler()
            >>> h.matches_slash(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/rollback"),
            ... )
            True
        """
        text = (msg.text or "").strip().lower()
        return text == "/rollback" or text.startswith("/rollback ")

    def handle(self, msg: IncomingMessage, *, is_owner: bool = False) -> str:
        """Return the rollback stub reply.

        Args:
            msg (IncomingMessage): Inbound message (unused by stub).
            is_owner (bool): Whether the actor is an owner (unused by stub).

        Returns:
            str: Informational reply for the user.

        Examples:
            >>> h = RollbackCommandHandler()
            >>> reply = h.handle(
            ...     IncomingMessage(channel="telegram", user_id="1", text="/rollback"),
            ... )
            >>> "rollback" in reply.lower()
            True
        """
        _ = msg
        _ = is_owner
        return _ROLLBACK_STUB_REPLY


__all__ = ["RollbackCommandHandler"]
