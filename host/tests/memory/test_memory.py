"""Bot memory store, user-turn block, and capture hint."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home
from support.canary import model_request_payloads, reset_model_requests
from support.chat import connected, fetch_all, load_modules, mint_id, poll_rows


async def _bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    return bot.id


def _hint_lines(payload: object) -> list[str]:
    return [
        line
        for line in str(payload).splitlines()
        if "memory.save" in line and "consider" in line.lower()
    ]


async def test_save_and_search_fts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.memory.store import MemoryStore

    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    turn_id = mint_id("turn_")
    await store.save(
        bot_id,
        "morning meetings are better",
        tier="recall",
        origin="bot",
        turn_id=turn_id,
    )
    assert await store.search(bot_id, "morning") == []
    await store.commit(turn_id)
    found = await store.search(bot_id, "morning")
    assert [item.text for item in found] == ["morning meetings are better"]
    assert await store.search(bot_id, "zzz-absent") == []
    cafe = mint_id("turn_")
    await store.save(bot_id, "café au lait on Fridays", turn_id=cafe)
    await store.commit(cafe)
    accented = await store.search(bot_id, "café")
    assert any("café" in item.text for item in accented)


async def test_pinned_block_in_user_turn_not_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakes.fake_jev import FakeJev
    from fakes.models import function_model
    from sevn.decisions.jev import use_client
    from sevn.memory.store import MemoryStore
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    reset_model_requests()
    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    turn_id = mint_id("turn_")
    await store.save(
        bot_id,
        "always open with the date",
        tier="pinned",
        origin="user",
        turn_id=turn_id,
    )
    await store.commit(turn_id)
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(
        FakeJev(
            answers={
                "message.intent": ("new_request", 0.95),
                "message.target_agent": ("none", 0.9),
            }
        )
    )
    use_model(function_model([{"kind": "text", "text": "ok"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            from support.chat import ok, request

            frame, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot_id, "text": "draft the note", "op_id": mint_id("op_")},
            )
            sent = ok(frame)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
    finally:
        use_client(None)
        use_model(None)
    payloads = model_request_payloads()
    assert payloads
    instructions = str(payloads[0].get("instructions") or "")
    messages = str(payloads[0].get("messages") or "")
    assert "<sevn_memories>" not in instructions
    assert "<sevn_memories>" in messages
    assert "untrusted" in messages.lower()
    assert "always open with the date" in messages


async def test_pinned_memory_reaches_every_turn_of_a_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The block is saved in the turn's history, so a later turn's diff has a base."""
    from fakes.fake_jev import FakeJev
    from fakes.models import function_model
    from sevn.decisions.jev import use_client
    from sevn.memory.store import MemoryStore
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    reset_model_requests()
    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    turn_id = mint_id("turn_")
    await store.save(
        bot_id, "always open with the date", tier="pinned", origin="user", turn_id=turn_id
    )
    await store.commit(turn_id)
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(
        FakeJev(
            answers={
                "message.intent": ("new_request", 0.95),
                "message.target_agent": ("none", 0.9),
            }
        )
    )
    use_model(function_model([{"kind": "text", "text": "ok"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            from support.chat import ok, request

            first = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot_id, "text": "draft the note", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (first["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            second = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {
                            "bot_id": bot_id,
                            "agent_id": first["agent_id"],
                            "text": "now shorten it",
                            "op_id": mint_id("op_"),
                        },
                    )
                )[0]
            )
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (second["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
    finally:
        use_client(None)
        use_model(None)
    payloads = model_request_payloads()
    assert len(payloads) >= 2
    assert ["always open with the date" in str(item.get("messages")) for item in payloads] == [
        True
    ] * len(payloads)
    histories = fetch_all(
        tmp_path,
        "SELECT model_messages FROM turns WHERE agent_id = ? ORDER BY started_at",
        (first["agent_id"],),
    )
    assert len(histories) == 2
    assert all("always open with the date" in str(row["model_messages"]) for row in histories)


async def test_pinned_budget_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.errors import DomainError
    from sevn.memory.store import MemoryStore

    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    filled = mint_id("turn_")
    saved = await store.save(bot_id, "p" * 4096, tier="pinned", origin="user", turn_id=filled)
    await store.commit(filled)
    assert saved.tier == "pinned"
    with pytest.raises(DomainError) as exc:
        await store.save(bot_id, "x", tier="pinned", origin="user", turn_id=mint_id("turn_"))
    assert exc.value.code == "pinned_budget"


async def test_changes_commit_only_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.memory.store import MemoryStore

    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    failed = mint_id("turn_")
    await store.save(bot_id, "do not keep this", turn_id=failed)
    await store.rollback(failed)
    assert await store.search(bot_id, "keep") == []
    assert fetch_all(tmp_path, "SELECT id FROM memories") == []
    kept = mint_id("turn_")
    await store.save(bot_id, "keep the receipt", turn_id=kept)
    await store.commit(kept)
    assert [item.text for item in await store.search(bot_id, "receipt")] == ["keep the receipt"]


async def test_writes_serialized_per_bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.memory.store import MemoryStore, bot_write_lock

    bot_id = await _bot(tmp_path, monkeypatch)
    from sevn.domain.bots import BotService

    other_bot = await BotService().create("Other")
    entered = 0
    peak = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold(target: str) -> None:
        nonlocal entered, peak
        async with bot_write_lock(target):
            entered += 1
            peak = max(peak, entered)
            if target == bot_id and not started.is_set():
                started.set()
                await release.wait()
            entered -= 1

    first = asyncio.create_task(hold(bot_id))
    await started.wait()
    second = asyncio.create_task(hold(bot_id))
    await asyncio.sleep(0.05)
    assert peak == 1
    assert entered == 1
    release.set()
    await first
    await second
    assert peak == 1

    overlap = 0
    overlap_peak = 0
    both = asyncio.Event()

    async def hold_open(target: str) -> None:
        nonlocal overlap, overlap_peak
        async with bot_write_lock(target):
            overlap += 1
            overlap_peak = max(overlap_peak, overlap)
            if overlap == 2:
                both.set()
            await both.wait()
            overlap -= 1

    left = asyncio.create_task(hold_open(bot_id))
    right = asyncio.create_task(hold_open(other_bot.id))
    await asyncio.wait_for(both.wait(), timeout=1)
    assert overlap_peak == 2
    await left
    await right

    store = MemoryStore()
    alpha = mint_id("turn_")
    beta = mint_id("turn_")
    await asyncio.gather(
        store.save(bot_id, "alpha fact", turn_id=alpha),
        store.save(bot_id, "beta fact", turn_id=beta),
    )
    await store.commit(alpha)
    await store.commit(beta)
    texts = {item.text for item in await store.search(bot_id, "fact")}
    assert texts == {"alpha fact", "beta fact"}


async def test_bot_cannot_change_user_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.errors import DomainError
    from sevn.memory.store import MemoryStore

    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    turn_id = mint_id("turn_")
    record = await store.save(
        bot_id,
        "keep this pinned",
        tier="pinned",
        origin="user",
        turn_id=turn_id,
    )
    await store.commit(turn_id)
    with pytest.raises(DomainError) as locked:
        await store.set_tier(record.id, "recall", actor="bot", revision=record.revision)
    assert locked.value.code == "memory_locked"
    with pytest.raises(DomainError) as stale:
        await store.set_tier(record.id, "recall", actor="user", revision=record.revision + 9)
    assert stale.value.code == "revision_conflict"
    updated = await store.set_tier(record.id, "recall", actor="user", revision=record.revision)
    assert updated.tier == "recall"
    assert updated.revision == record.revision + 1


async def test_memory_block_labelled_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.memory.context import render_user_block
    from sevn.memory.store import MemoryStore

    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    turn_id = mint_id("turn_")
    await store.save(bot_id, "the desk faces the window", tier="pinned", turn_id=turn_id)
    await store.commit(turn_id)
    block = await render_user_block(bot_id, prior=False)
    assert "<sevn_memories>" in block
    assert "untrusted" in block.lower()
    assert "the desk faces the window" in block


async def test_diff_sent_on_later_turns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.memory.context import render_user_block
    from sevn.memory.store import MemoryStore

    bot_id = await _bot(tmp_path, monkeypatch)
    store = MemoryStore()
    first = mint_id("turn_")
    await store.save(bot_id, "first fact", turn_id=first)
    await store.commit(first)
    opening = await render_user_block(bot_id, prior=False)
    assert "<sevn_memories>" in opening
    second = mint_id("turn_")
    await store.save(bot_id, "second fact", turn_id=second)
    await store.commit(second)
    diff = await render_user_block(bot_id, prior=True)
    assert "<sevn_memories_diff>" in diff
    assert "<sevn_memories>" not in diff
    assert "second fact" in diff


async def test_capture_hint_after_high_noul(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakes.fake_jev import FakeJev
    from fakes.models import function_model
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind
    from support.chat import ok, request

    reset_model_requests()
    await _bot(tmp_path, monkeypatch)
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(
        FakeJev(
            answers={
                "message.intent": ("new_request", 0.95),
                "message.target_agent": ("none", 0.9),
                "memory.capture": 0.91,
            }
        )
    )
    use_model(function_model([{"kind": "text", "text": "noted"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            from sevn.domain.bots import BotService

            bot = (await BotService().list())[0]
            first, _earlier = await request(
                client,
                "messages.send",
                {
                    "bot_id": bot.id,
                    "text": "I always take tea at four",
                    "op_id": mint_id("op_"),
                },
            )
            sent = ok(first)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            follow, _frames = await request(
                client,
                "messages.send",
                {
                    "bot_id": bot.id,
                    "text": "and add a biscuit",
                    "agent_id": sent["agent_id"],
                    "op_id": mint_id("op_"),
                },
            )
            nxt = ok(follow)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (nxt["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
    finally:
        use_client(None)
        use_model(None)
    payloads = model_request_payloads()
    assert len(payloads) >= 2
    assert _hint_lines(payloads[0]) == []
    assert len(_hint_lines(payloads[1])) == 1
    assert fetch_all(tmp_path, "SELECT id FROM memories") == []


async def test_capture_below_threshold_has_no_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fakes.fake_jev import FakeJev
    from fakes.models import function_model
    from sevn.decisions.jev import use_client
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind
    from support.chat import ok, request

    reset_model_requests()
    await _bot(tmp_path, monkeypatch)
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_client(
        FakeJev(
            answers={
                "message.intent": ("new_request", 0.95),
                "message.target_agent": ("none", 0.9),
                "memory.capture": 0.5,
            }
        )
    )
    use_model(function_model([{"kind": "text", "text": "noted"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            from sevn.domain.bots import BotService

            bot = (await BotService().list())[0]
            first, _earlier = await request(
                client,
                "messages.send",
                {"bot_id": bot.id, "text": "hello there", "op_id": mint_id("op_")},
            )
            sent = ok(first)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (sent["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
            follow, _frames = await request(
                client,
                "messages.send",
                {
                    "bot_id": bot.id,
                    "text": "again",
                    "agent_id": sent["agent_id"],
                    "op_id": mint_id("op_"),
                },
            )
            nxt = ok(follow)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (nxt["job_id"],),
                lambda rows: bool(rows) and rows[0]["status"] == "done",
            )
    finally:
        use_client(None)
        use_model(None)
    payloads = model_request_payloads()
    assert len(payloads) >= 2
    assert _hint_lines(payloads[0]) == []
    assert _hint_lines(payloads[1]) == []
