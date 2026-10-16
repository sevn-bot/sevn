"""Queue overflow and tick coalescing (D12)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from support.clock import ManualClock
from support.memory import handshake, memory_host, recv_frame


async def test_slow_consumer_closes_4008(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch, queue_limit=5) as host:
        client, _session = host.open()
        await handshake(client, host.token)

        async def burst() -> None:
            for index in range(6):
                await host.hub.emit("system.ping", "system", {"i": index})

        await asyncio.wait_for(burst(), 2)
        code, reason = await asyncio.wait_for(client.wait_closed(), 2)
        assert code == 4008
        assert reason == "slow consumer"


async def test_ticks_coalesced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = ManualClock()
    async with memory_host(tmp_path, monkeypatch, clock=clock) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        for index in range(10):
            host.hub.tick(
                "turn.delta",
                "k1",
                {"turn": f"t{index}", "text": chr(ord("a") + index)},
            )
            clock.advance(0.001)
        clock.advance(0.05)
        await asyncio.sleep(0)
        frame = await recv_frame(client)
        assert frame["t"] == "tick"
        assert frame["k"] == "turn.delta"
        assert frame["d"]["text"] == "abcdefghij"
        assert frame["d"]["turn"] == "t9"
        with pytest.raises(TimeoutError):
            await recv_frame(client, 0.2)
