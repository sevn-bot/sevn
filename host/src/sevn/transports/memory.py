"""In-process connection pair for tests and the probe."""

from __future__ import annotations

import asyncio
from collections import deque

from sevn.transports.base import ConnectionClosed


class MemoryConnection:
    """One end of a memory pair.

    ``send_text`` does not return until the peer's ``recv_text`` takes the frame
    or the connection closes, so an unread session fills its outbound queue.
    """

    def __init__(self) -> None:
        self._other: MemoryConnection | None = None
        self._inbox: deque[tuple[str, asyncio.Future[None]]] = deque()
        self._signal = asyncio.Event()
        self._closed = asyncio.Event()
        self._code = 1000
        self._reason = ""

    async def send_text(self, text: str) -> None:
        peer = self._peer()
        if self._closed.is_set() or peer._closed.is_set():
            raise self._closed_error()
        ack: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        peer._inbox.append((text, ack))
        peer._signal.set()
        await ack

    async def recv_text(self) -> str:
        while True:
            if self._inbox:
                text, ack = self._inbox.popleft()
                if not ack.done():
                    ack.set_result(None)
                return text
            if self._closed.is_set():
                raise ConnectionClosed(self._code, self._reason)
            self._signal.clear()
            if self._inbox or self._closed.is_set():
                continue
            await self._wait_for_frame()

    async def close(self, code: int, reason: str) -> None:
        self._mark(code, reason)
        other = self._other
        if other is not None:
            other._mark(code, reason)

    async def wait_closed(self) -> tuple[int, str]:
        await self._closed.wait()
        return self._code, self._reason

    async def _wait_for_frame(self) -> None:
        signal = asyncio.create_task(self._signal.wait())
        closed = asyncio.create_task(self._closed.wait())
        try:
            _done, pending = await asyncio.wait(
                {signal, closed},
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            signal.cancel()
            closed.cancel()
            raise
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def _mark(self, code: int, reason: str) -> None:
        if self._closed.is_set():
            return
        self._code = code
        self._reason = reason
        self._closed.set()
        self._signal.set()
        for _text, ack in self._inbox:
            if not ack.done():
                ack.set_result(None)

    @classmethod
    def pair(cls) -> tuple[MemoryConnection, MemoryConnection]:
        client = cls()
        server = cls()
        client._other = server
        server._other = client
        return client, server

    def _peer(self) -> MemoryConnection:
        other = self._other
        if other is None:
            raise ConnectionClosed(1006, "not paired")
        return other

    def _closed_error(self) -> ConnectionClosed:
        if self._closed.is_set():
            return ConnectionClosed(self._code, self._reason)
        other = self._other
        if other is not None and other._closed.is_set():
            return ConnectionClosed(other._code, other._reason)
        return ConnectionClosed(1006, "closed")


def pair() -> tuple[MemoryConnection, MemoryConnection]:
    """Return ``(client, server)`` ends of one in-process connection."""
    return MemoryConnection.pair()
