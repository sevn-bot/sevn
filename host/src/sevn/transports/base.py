"""Transport-agnostic connection surface (spec §3)."""

from __future__ import annotations

from typing import Protocol


class ConnectionClosed(Exception):
    """The peer is gone. ``recv_text`` raises this; ``wait_closed`` returns the same pair."""

    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason)


class Connection(Protocol):
    async def send_text(self, text: str) -> None: ...

    async def recv_text(self) -> str: ...

    async def close(self, code: int, reason: str) -> None: ...
