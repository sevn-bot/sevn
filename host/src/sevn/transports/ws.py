"""Starlette WebSocket adapted to ``Connection`` (D7)."""

from __future__ import annotations

from typing import cast

from starlette.websockets import WebSocket, WebSocketDisconnect

from sevn.transports.base import ConnectionClosed

_MAX_FRAME = 1024 * 1024
_CLOSE_TOO_BIG = 1009
_REASON_TOO_BIG = "message too big"


class WsConnection:
    """One accepted WebSocket.

    Inbound frames larger than 1 MiB close the socket with 1009.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._closed = False
        self._code = 1000
        self._reason = ""

    async def send_text(self, text: str) -> None:
        if self._closed:
            raise ConnectionClosed(self._code, self._reason)
        try:
            await self._ws.send_text(text)
        except WebSocketDisconnect as exc:
            self._mark(exc.code, exc.reason or "")
            raise ConnectionClosed(self._code, self._reason) from exc
        except RuntimeError as exc:
            self._mark(1006, "closed")
            raise ConnectionClosed(self._code, self._reason) from exc

    async def recv_text(self) -> str:
        if self._closed:
            raise ConnectionClosed(self._code, self._reason)
        try:
            message = await self._ws.receive()
        except WebSocketDisconnect as exc:
            self._mark(exc.code, exc.reason or "")
            raise ConnectionClosed(self._code, self._reason) from exc
        except RuntimeError as exc:
            self._mark(1006, "closed")
            raise ConnectionClosed(self._code, self._reason) from exc
        if message["type"] == "websocket.disconnect":
            code = _code(message.get("code"))
            reason = _reason(message.get("reason"))
            self._mark(code, reason)
            raise ConnectionClosed(code, reason)
        payload = _payload(message)
        if payload is None:
            await self.close(1002, "protocol error")
            raise ConnectionClosed(1002, "protocol error")
        if _nbytes(payload) > _MAX_FRAME:
            await self.close(_CLOSE_TOO_BIG, _REASON_TOO_BIG)
            raise ConnectionClosed(_CLOSE_TOO_BIG, _REASON_TOO_BIG)
        if isinstance(payload, bytes):
            await self.close(1002, "protocol error")
            raise ConnectionClosed(1002, "protocol error")
        return payload

    async def close(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._mark(code, reason)
        try:
            await self._ws.close(code=code, reason=reason)
        except (WebSocketDisconnect, RuntimeError):
            return

    def _mark(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        self._code = code
        self._reason = reason


def _payload(message: object) -> str | bytes | None:
    if not isinstance(message, dict):
        return None
    fields = cast("dict[object, object]", message)
    text = fields.get("text")
    if isinstance(text, str):
        return text
    raw = fields.get("bytes")
    if isinstance(raw, bytes):
        return raw
    return None


def _nbytes(payload: str | bytes) -> int:
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    return len(payload)


def _code(value: object) -> int:
    if isinstance(value, int):
        return value
    return 1000


def _reason(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""
