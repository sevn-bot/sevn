"""PR #9 review round 2: memory and agent tools stay inside the caller's bot,
memory search returns what pin and forget need, and a failed op can be retried."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from support.botcore import arm_configured, upgrade_home
from support.chat import fetch_all, mint_id


async def _two_bots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    return await BotService().create("Owner"), await BotService().create("Other")


async def _committed(bot_id: str, text: str, *, tier: str = "recall") -> Any:
    from sevn.memory.store import MemoryStore

    store = MemoryStore()
    turn_id = mint_id("turn_")
    record = await store.save(bot_id, text, tier=tier, turn_id=turn_id)
    await store.commit(turn_id)
    return record


async def test_forget_refuses_another_bots_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.errors import DomainError
    from sevn.memory.store import MemoryStore

    owner, other = await _two_bots(tmp_path, monkeypatch)
    record = await _committed(owner.id, "the owner's fact")
    store = MemoryStore()
    turn_id = mint_id("turn_")
    with pytest.raises(DomainError) as caught:
        await store.stage_delete(other.id, record.id, turn_id=turn_id)
    assert caught.value.code == "not_found"
    await store.commit(turn_id)
    assert fetch_all(tmp_path, "SELECT id FROM memories WHERE id = ?", (record.id,))


async def test_pin_refuses_another_bots_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.memory.tools import memory_toolset
    from sevn.tools.registry import TurnDeps

    owner, other = await _two_bots(tmp_path, monkeypatch)
    record = await _committed(owner.id, "the owner's fact")
    turn_id = mint_id("turn_")
    tools = memory_toolset(TurnDeps(bot_id=other.id, agent_id="agent_x", turn_id=turn_id))
    assert isinstance(tools, dict)
    answer = await tools["memory.pin"](record.id, record.revision)
    assert answer == "not_found"
    from sevn.memory.store import MemoryStore

    await MemoryStore().commit(turn_id)
    rows = fetch_all(tmp_path, "SELECT tier FROM memories WHERE id = ?", (record.id,))
    assert rows[0]["tier"] == "recall"


async def test_search_and_save_return_what_pin_and_forget_need(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.memory.store import MemoryStore
    from sevn.memory.tools import memory_toolset
    from sevn.tools.registry import TurnDeps

    owner, _other = await _two_bots(tmp_path, monkeypatch)
    record = await _committed(owner.id, "lunch is at noon")
    turn_id = mint_id("turn_")
    tools = memory_toolset(TurnDeps(bot_id=owner.id, agent_id="agent_x", turn_id=turn_id))
    assert isinstance(tools, dict)
    found = await tools["memory.search"]("lunch")
    assert record.id in found
    assert "revision 1" in found
    assert "recall" in found
    assert "lunch is at noon" in found
    saved = await tools["memory.save"]("the desk faces the window")
    assert saved.startswith("mem_")
    assert "revision 1" in saved
    pinned = await tools["memory.pin"](record.id, 1)
    assert pinned == record.id
    await MemoryStore().commit(turn_id)
    rows = fetch_all(tmp_path, "SELECT tier FROM memories WHERE id = ?", (record.id,))
    assert rows[0]["tier"] == "pinned"


async def test_agent_read_refuses_another_bots_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.tools.agents import agents_toolset
    from sevn.tools.registry import TurnDeps

    owner, other = await _two_bots(tmp_path, monkeypatch)
    foreign = await AgentService().spawn(owner.id, title="Secret plan")
    mine = await AgentService().spawn(other.id, title="My lane")
    tools = agents_toolset(TurnDeps(bot_id=other.id, agent_id=mine.id, turn_id="turn_x"))
    assert isinstance(tools, dict)
    shown = await tools["agent.read"](foreign.id)
    assert shown == "not_found"
    assert "Secret plan" not in shown
    own = await tools["agent.read"](mine.id)
    assert "My lane" in own


async def test_failed_op_can_be_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.contracts.errors import ProtocolError
    from support.memory import memory_host

    async with memory_host(tmp_path, monkeypatch) as host:
        calls = 0

        async def failing() -> dict[str, object]:
            nonlocal calls
            calls += 1
            await host.hub.emit("system.ping", "ping", {"note": "before the failure"})
            raise ProtocolError("invalid_params", "bad input")

        async def working() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"ok": True}

        with pytest.raises(ProtocolError) as first:
            await host.hub.claim_op("op_retry", "system.ping", "hash", failing)
        assert first.value.code == "invalid_params"
        again = await host.hub.claim_op("op_retry", "system.ping", "hash", working)
        assert again == {"ok": True}
        assert calls == 2
        replay = await host.hub.claim_op("op_retry", "system.ping", "hash", working)
        assert replay == {"ok": True}
        assert calls == 2
