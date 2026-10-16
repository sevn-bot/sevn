"""Mutating op_id behaviour (D11, D13). Green after W4."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from support.memory import count_events, handshake, memory_host, recv_frame, send_req

pytestmark = pytest.mark.xfail(strict=False, reason="green after W4")


async def _ping(
    client: object, op_id: str, note: str
) -> tuple[dict[str, object], dict[str, object]]:
    await send_req(client, op_id, "system.ping", {"op_id": op_id, "note": note})
    response = await recv_frame(client)
    event = await recv_frame(client)
    return response, event


async def test_repeat_op_id_returns_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        before = await count_events(host.outbox)
        first, event = await _ping(client, "op-same", "hi")
        assert first["t"] == "res"
        assert event["t"] == "evt"
        assert await count_events(host.outbox) == before + 1
        await send_req(client, "op-same-again", "system.ping", {"op_id": "op-same", "note": "hi"})
        second = await recv_frame(client)
        assert second["r"] == first["r"]
        assert await count_events(host.outbox) == before + 1
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.recv_text(), 0.2)


async def test_mutating_without_op_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        await send_req(client, "no-op", "system.ping", {"note": "hi"})
        frame = await recv_frame(client)
        assert frame["e"]["code"] == "op_id_required"


async def test_response_carries_caused_seq(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        response, event = await _ping(client, "op-seq", "hi")
        assert response["r"]["seq"] == event["s"]
        assert event["k"] == "system.ping"
        assert event["d"]["note"] == "hi"
