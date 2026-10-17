"""In-process host for protocol tests.

Pinned constructors (W4):
- `Outbox(url)`, `OpLog(url)`, `upgrade(url)`
- `Hub(outbox, oplog)` or `Hub(outbox, oplog, clock=clock)`
- `Session(connection, hub, *, token, queue_limit)` with `run()`
- `pair()` → `(client, server)` connections
- `client.wait_closed()` → `(code, reason)`
- `recv_text` raises `sevn.transports.base.ConnectionClosed`
"""

from __future__ import annotations

import asyncio
import inspect
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from support.clock import ManualClock


@dataclass
class MemoryHost:
    hub: Any
    outbox: Any
    token: str
    queue_limit: int
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    clients: list[Any] = field(default_factory=list)

    def open(self) -> tuple[Any, Any]:
        from sevn.protocol.session import Session
        from sevn.transports.memory import pair

        client, server = pair()
        session = Session(server, self.hub, token=self.token, queue_limit=self.queue_limit)
        self.tasks.append(asyncio.create_task(session.run()))
        self.clients.append(client)
        return client, session


@asynccontextmanager
async def memory_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    queue_limit: int = 1000,
    clock: ManualClock | None = None,
) -> AsyncIterator[MemoryHost]:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_DEV", raising=False)
    (tmp_path / "config.toml").write_text(
        f'[protocol]\nsession_queue_limit = {queue_limit}\n\n[secrets]\nbackend = "age-file"\n',
        encoding="utf-8",
    )

    import sevn.system as system
    from sevn.config import Settings
    from sevn.identity import load_or_create
    from sevn.paths import Paths
    from sevn.protocol.hub import Hub
    from sevn.secrets.backends import open_backend
    from sevn.store.db import upgrade
    from sevn.store.oplog import OpLog
    from sevn.store.outbox import Outbox

    settings = Settings.load()
    paths = Paths.from_env()
    url = f"sqlite+aiosqlite:///{paths.db}"
    await upgrade(url)
    outbox = Outbox(url)
    oplog = OpLog(url)
    backend = open_backend(settings, paths)
    created = load_or_create(backend)
    if inspect.isawaitable(created):
        await created
    hub = Hub(outbox, oplog) if clock is None else Hub(outbox, oplog, clock=clock)
    assert system.__name__ == "sevn.system"

    host = MemoryHost(
        hub=hub,
        outbox=outbox,
        token=secrets.token_urlsafe(16),
        queue_limit=queue_limit,
    )
    try:
        yield host
    finally:
        for client in host.clients:
            close = getattr(client, "close", None)
            if close is None:
                continue
            with suppress(Exception):
                result = close(1000, "test done")
                if asyncio.iscoroutine(result):
                    await result
        for task in host.tasks:
            task.cancel()
        for task in host.tasks:
            with suppress(asyncio.CancelledError):
                await task


def hello_frame(*, proto: list[int] | None = None, last_seq: int = 0) -> dict[str, Any]:
    return {
        "t": "hello",
        "proto": [1, 1] if proto is None else proto,
        "client": "web",
        "device": "dev_test",
        "last_seq": last_seq,
        "caps": [],
    }


async def send_frame(client: Any, frame: dict[str, Any]) -> None:
    await client.send_text(json.dumps(frame))


async def send_req(client: Any, req_id: str, method: str, params: dict[str, Any]) -> None:
    await send_frame(client, {"t": "req", "id": req_id, "m": method, "p": params})


async def recv_frame(client: Any, seconds: float = 2) -> dict[str, Any]:
    raw = await asyncio.wait_for(client.recv_text(), seconds)
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


async def handshake(
    client: Any,
    token: str,
    *,
    proto: list[int] | None = None,
    last_seq: int = 0,
    auth_token: str | None = None,
) -> dict[str, Any]:
    await send_frame(client, hello_frame(proto=proto, last_seq=last_seq))
    await send_frame(client, {"t": "auth", "token": token if auth_token is None else auth_token})
    frame = await recv_frame(client)
    return frame


async def collect_until_close(client: Any) -> tuple[list[dict[str, Any]], Any]:
    from sevn.transports.base import ConnectionClosed

    frames: list[dict[str, Any]] = []
    while True:
        try:
            frames.append(await recv_frame(client))
        except ConnectionClosed as exc:
            return frames, exc


async def count_events(outbox: Any) -> int:
    rows = await outbox.since(0)
    return len(rows)


def raise_task_error(host: MemoryHost) -> None:
    for task in host.tasks:
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                raise exc
