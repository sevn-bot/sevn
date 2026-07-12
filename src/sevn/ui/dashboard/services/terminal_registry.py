"""In-memory pending terminal session upgrades (MC W8).

Module: sevn.ui.dashboard.services.terminal_registry
Depends: time, uuid

Exports:
    TerminalUpgradeTicket — short-lived owner upgrade slot for WebSocket attach.
    TerminalSessionRegistry — register/consume pending terminal sessions.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TerminalUpgradeTicket:
    """Short-lived owner upgrade slot before WebSocket PTY attach.

    Attributes:
        session_id (str): Correlation id returned to the SPA.
        owner_sub (str): Dashboard owner subject that minted the ticket.
        expires_at (float): Monotonic deadline for consumption.
    """

    session_id: str
    owner_sub: str
    expires_at: float


@dataclass
class TerminalSessionRegistry:
    """Register and consume one-shot terminal upgrade tickets."""

    _tickets: dict[str, TerminalUpgradeTicket] = field(default_factory=dict)

    def mint(self, *, owner_sub: str, ttl_s: float = 120.0) -> TerminalUpgradeTicket:
        """Create a pending upgrade ticket for the verified owner.

        Args:
            owner_sub (str): Dashboard JWT ``sub`` (``owner`` in v1).
            ttl_s (float): Seconds until the ticket expires unused.

        Returns:
            TerminalUpgradeTicket: Ticket handed to the SPA before WS connect.

        Examples:
            >>> reg = TerminalSessionRegistry()
            >>> t = reg.mint(owner_sub="owner", ttl_s=60.0)
            >>> t.owner_sub
            'owner'
        """
        self._prune()
        session_id = uuid.uuid4().hex
        ticket = TerminalUpgradeTicket(
            session_id=session_id,
            owner_sub=owner_sub,
            expires_at=time.monotonic() + ttl_s,
        )
        self._tickets[session_id] = ticket
        return ticket

    def consume(self, session_id: str, *, owner_sub: str) -> TerminalUpgradeTicket | None:
        """Remove and return a ticket when owner + id match and not expired.

        Args:
            session_id (str): Ticket id from :meth:`mint`.
            owner_sub (str): Dashboard owner subject attempting attach.

        Returns:
            TerminalUpgradeTicket | None: Consumed ticket or ``None`` when invalid.

        Examples:
            >>> reg = TerminalSessionRegistry()
            >>> t = reg.mint(owner_sub="owner")
            >>> reg.consume(t.session_id, owner_sub="owner") is not None
            True
        """
        self._prune()
        ticket = self._tickets.pop(session_id, None)
        if ticket is None:
            return None
        if ticket.owner_sub != owner_sub:
            return None
        if time.monotonic() > ticket.expires_at:
            return None
        return ticket

    def _prune(self) -> None:
        """Drop expired tickets.

        Returns:
            None: Side-effect only.

        Examples:
            >>> TerminalSessionRegistry()._prune() is None
            True
        """
        now = time.monotonic()
        stale = [sid for sid, t in self._tickets.items() if now > t.expires_at]
        for sid in stale:
            self._tickets.pop(sid, None)


terminal_session_registry = TerminalSessionRegistry()

__all__ = [
    "TerminalSessionRegistry",
    "TerminalUpgradeTicket",
    "terminal_session_registry",
]
