"""Speak the loopback protocol using the token file (D7, D13)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, cast

from sevn.config import Settings
from sevn.contracts.errors import JsonObject, JsonValue
from sevn.contracts.frames import AuthToken, Evt, Hello, Req, Res, Welcome, dump, parse
from sevn.paths import Paths

_TIMEOUT = 10.0


class ProbeError(Exception):
    """The probe could not complete a call. The message never includes the token."""


async def call_method(method: str, params: JsonObject) -> JsonObject:
    """Handshake and return the ``res.r`` object for ``method``."""

    async def work(ws: _Socket) -> JsonObject:
        await ws.send(dump(Req(t="req", id="1", m=method, p=params)))
        while True:
            frame = parse(await _recv(ws))
            if isinstance(frame, Evt):
                continue
            if isinstance(frame, Res):
                if frame.e is not None:
                    raise ProbeError(frame.e.message)
                if frame.r is None:
                    raise ProbeError("empty result")
                return frame.r
            raise ProbeError("unexpected frame")

    return await _session(work)


async def events_since(seq: int) -> list[JsonObject]:
    """Replay durable events after ``seq`` and return them as JSON objects."""

    async def work(ws: _Socket) -> list[JsonObject]:
        await ws.send(dump(Req(t="req", id="1", m="sync.since", p={"seq": seq})))
        found: list[JsonObject] = []
        host_seq = seq
        saw_res = False
        while True:
            frame = parse(await _recv(ws))
            if isinstance(frame, Evt):
                found.append(cast(JsonObject, frame.model_dump(mode="json")))
                if saw_res and frame.s == host_seq:
                    return found
                continue
            if isinstance(frame, Res):
                if frame.e is not None:
                    raise ProbeError(frame.e.message)
                host_seq = _host_seq(frame.r)
                saw_res = True
                if host_seq <= seq or any(_seq_of(item) == host_seq for item in found):
                    return found
                continue
            raise ProbeError("unexpected frame")

    return await _session(work)


def parse_params(text: str) -> JsonObject:
    value = _parse_json(text)
    if not isinstance(value, dict):
        raise ProbeError("params must be a JSON object")
    return value


class _Socket(Protocol):
    """The slice of a websockets connection the probe uses."""

    async def send(self, text: str) -> None: ...

    async def recv(self) -> str | bytes: ...


async def _session[T](work: Callable[[_Socket], Awaitable[T]]) -> T:
    settings = Settings.load()
    paths = Paths.from_env()
    token = _read_token(paths.run / "token")
    url = _ws_url(settings.http.host, settings.http.port)
    try:
        return await asyncio.wait_for(_connected(url, token, work), _TIMEOUT)
    except ProbeError:
        raise
    except TimeoutError as exc:
        raise ProbeError("timed out talking to the host") from exc
    except OSError as exc:
        raise ProbeError("host is not reachable") from exc


async def _connected[T](url: str, token: str, work: Callable[[_Socket], Awaitable[T]]) -> T:
    from websockets.asyncio.client import connect
    from websockets.exceptions import WebSocketException

    try:
        async with connect(
            url,
            max_size=1024 * 1024,
            open_timeout=_TIMEOUT,
            origin=None,
            proxy=None,
        ) as ws:
            socket = _Ws(ws)
            await _handshake(socket, token)
            return await work(socket)
    except WebSocketException as exc:
        raise ProbeError("host is not reachable") from exc


class _Ws:
    def __init__(self, ws: object) -> None:
        self._ws = ws

    async def send(self, text: str) -> None:
        send = getattr(self._ws, "send", None)
        if send is None:
            raise ProbeError("host is not reachable")
        await send(text)

    async def recv(self) -> str | bytes:
        recv = getattr(self._ws, "recv", None)
        if recv is None:
            raise ProbeError("host is not reachable")
        message: object = await recv()
        if isinstance(message, str | bytes):
            return message
        raise ProbeError("unexpected frame")


async def _handshake(ws: _Socket, token: str) -> None:
    hello = Hello(
        t="hello",
        proto=[1, 1],
        client="cli",
        device="probe",
        last_seq=0,
        caps=[],
    )
    await ws.send(dump(hello))
    await ws.send(dump(AuthToken(t="auth", token=token)))
    frame = parse(await _recv(ws))
    if not isinstance(frame, Welcome):
        raise ProbeError("expected welcome")


async def _recv(ws: _Socket) -> str:
    message = await ws.recv()
    if isinstance(message, bytes):
        return message.decode("utf-8")
    return message


def _read_token(path: Path) -> str:
    if not path.is_file():
        raise ProbeError("token file is missing")
    token = path.read_text(encoding="utf-8").strip()
    if token == "":
        raise ProbeError("token file is empty")
    return token


def _ws_url(host: str, port: int) -> str:
    dial = "127.0.0.1" if host in {"0.0.0.0", "::"} else host  # noqa: S104
    if ":" in dial and not dial.startswith("["):
        dial = f"[{dial}]"
    return f"ws://{dial}:{port}/ws"


def _host_seq(result: JsonObject | None) -> int:
    if result is None:
        raise ProbeError("empty result")
    value = result.get("host_seq")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ProbeError("sync.since did not return host_seq")


def _seq_of(item: JsonObject) -> int | None:
    value = item.get("s")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _parse_json(text: str) -> JsonValue:
    try:
        loaded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProbeError("invalid json") from exc
    return _as_json(loaded)


def _as_json(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        raw = cast("dict[object, object]", value)
        body: dict[str, JsonValue] = {}
        for key, item in raw.items():
            if not isinstance(key, str):
                raise ProbeError("invalid json")
            body[key] = _as_json(item)
        return body
    if isinstance(value, list):
        items = cast("list[object]", value)
        return [_as_json(item) for item in items]
    raise ProbeError("invalid json")
