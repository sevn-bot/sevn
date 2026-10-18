"""Durable replay and ticks that are not replayed (D10, D12)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from support.clock import ManualClock
from support.memory import handshake, memory_host, recv_frame, send_req


async def _ping(client: object, op_id: str) -> None:
    await send_req(client, op_id, "system.ping", {"op_id": op_id, "note": op_id})
    response = await recv_frame(client)
    event = await recv_frame(client)
    assert response["t"] == "res"
    assert event["t"] == "evt"
    assert response["r"]["seq"] == event["s"]


async def test_sync_since_replays_missed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client_a, _session_a = host.open()
        welcome = await handshake(client_a, host.token)
        start = welcome["host_seq"]
        for index in range(3):
            await _ping(client_a, f"op-{index}")
        client_b, _session_b = host.open()
        await handshake(client_b, host.token, last_seq=start)
        await send_req(client_b, "sync", "sync.since", {"seq": start})
        frames: list[dict[str, object]] = []
        deadline = asyncio.get_running_loop().time() + 2
        while asyncio.get_running_loop().time() < deadline:
            timeout = deadline - asyncio.get_running_loop().time()
            try:
                frames.append(await recv_frame(client_b, timeout))
            except TimeoutError:
                break
            events = [frame for frame in frames if frame["t"] == "evt"]
            responses = [frame for frame in frames if frame.get("id") == "sync"]
            if len(events) >= 3 and responses:
                break
        events = [frame for frame in frames if frame["t"] == "evt"]
        assert [frame["s"] for frame in events] == [start + 1, start + 2, start + 3]
        assert len(events) == 3
        assert all(frame["t"] != "tick" for frame in frames)


async def test_ticks_not_replayed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = ManualClock()
    async with memory_host(tmp_path, monkeypatch, clock=clock) as host:
        client_a, _session_a = host.open()
        await handshake(client_a, host.token)
        host.hub.tick("turn.delta", "k1", {"turn": "t", "text": "zz"})
        clock.advance(0.05)
        await asyncio.sleep(0)
        tick = await recv_frame(client_a)
        assert tick["t"] == "tick"
        client_b, _session_b = host.open()
        await handshake(client_b, host.token, last_seq=0)
        await send_req(client_b, "sync", "sync.since", {"seq": 0})
        frames: list[dict[str, object]] = []
        try:
            while len(frames) < 4:
                frames.append(await recv_frame(client_b, 0.5))
        except TimeoutError:
            pass
        assert frames
        assert all(frame["t"] != "tick" for frame in frames)


async def test_resync_required_when_pruned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        for index in range(4):
            await host.hub.emit("system.ping", "system", {"i": index})
            event = await recv_frame(client)
            assert event["t"] == "evt"
        await host.outbox.prune(max_age=timedelta(days=7), max_rows=2)
        await send_req(client, "sync", "sync.since", {"seq": 0})
        response = await recv_frame(client)
        assert response["e"]["code"] == "resync_required"
        assert isinstance(response["e"]["data"]["min_seq"], int)
        assert response["e"]["data"]["min_seq"] >= 1


async def test_sync_since_pages_and_reports_the_real_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        for index in range(3):
            await host.hub.emit("system.ping", "system", {"i": index})
            assert (await recv_frame(client))["t"] == "evt"
        await send_req(client, "page", "sync.since", {"seq": 0, "limit": 1})
        response = await recv_frame(client)
        assert response["r"]["more"] is True
        assert response["r"]["next_seq"] == 1
        assert response["r"]["host_seq"] == 3
        event = await recv_frame(client)
        assert event["s"] == 1
        await send_req(client, "ahead", "sync.since", {"seq": 99})
        ahead = await recv_frame(client)
        assert ahead["r"]["host_seq"] == 3
        assert ahead["r"]["next_seq"] == 3
        assert ahead["r"]["more"] is False
        await send_req(client, "huge", "sync.since", {"seq": 2**70})
        invalid = await recv_frame(client)
        assert invalid["e"]["code"] == "invalid_params"
