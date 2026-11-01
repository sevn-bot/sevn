"""PR9 lifecycle regressions: cancellation, retry identity and commit ordering."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel
from sevn.domain.agents import AgentService
from sevn.domain.bots import BotService
from sevn.domain.jobs import JobService
from sevn.domain.session import open_session
from sevn.runtime.models import use_model
from sevn.runtime.worker import bind
from sevn.store.db import utcnow
from sevn.store.models import Message, Turn
from support.botcore import arm_configured, upgrade_home
from support.chat import connected, fetch_all, mint_id, poll_rows


async def test_cancel_lane_stops_queued_followups(tmp_path: Path, monkeypatch) -> None:
    from sevn.domain.routing import _cancel_agent

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Cancel")
    agent = await AgentService().spawn(bot.id)
    started, hold = asyncio.Event(), asyncio.Event()
    calls = 0

    async def respond(_messages, _info):
        nonlocal calls
        calls += 1
        started.set()
        await hold.wait()
        return ModelResponse(parts=[TextPart("done")])

    use_model(FunctionModel(respond))
    try:
        async with connected(tmp_path, monkeypatch) as (host, _client):
            worker = bind(host.hub)
            for job_id in ("job_first", "job_followup"):
                await JobService().enqueue(job_id, bot.id, agent.id, job_id)
            worker.kick(agent.id)
            await asyncio.wait_for(started.wait(), 5)
            await _cancel_agent(agent.id)
            await worker.settle(agent.id)
            assert calls == 1
            assert [r["status"] for r in fetch_all(tmp_path, "SELECT status FROM jobs")] == [
                "cancelled",
                "cancelled",
            ]
            assert (await AgentService().get(agent.id)).status == "done"
    finally:
        hold.set()
        use_model(None)


async def test_crash_retry_reuses_original_user_message(tmp_path: Path, monkeypatch) -> None:
    from sevn.runtime.recovery import recover

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Recovery")
    agent = await AgentService().spawn(bot.id)
    job_id, turn_id, message_id = (mint_id(prefix) for prefix in ("job_", "turn_", "msg_"))
    await JobService().enqueue(job_id, bot.id, agent.id, "retry once", status="started")
    now = utcnow()
    async with open_session() as session:
        session.add(
            Turn(
                id=turn_id,
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_ids=[job_id],
                status="running",
                model=bot.model,
                usage={},
                model_messages=None,
                started_at=now,
                finished_at=None,
            )
        )
        await session.flush()
        session.add(
            Message(
                id=message_id,
                thread_id=agent.thread_id,
                turn_id=turn_id,
                agent_id=agent.id,
                role="user",
                author="user",
                parts=[{"type": "text", "text": "retry once"}],
                created_at=now,
            )
        )
        await session.commit()
    use_model(FunctionModel(lambda _m, _i: ModelResponse(parts=[TextPart("done")])))
    try:
        async with connected(tmp_path, monkeypatch) as (host, _client):
            recovery = await recover()
            assert recovery.kick == (agent.id,)
            worker = bind(host.hub)
            worker.kick(agent.id)
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id=?",
                (job_id,),
                lambda rows: rows[0]["status"] == "done",
            )
            messages = fetch_all(tmp_path, "SELECT * FROM messages WHERE role='user'")
            assert len(messages) == 1
            assert messages[0]["id"] == message_id
            assert messages[0]["turn_id"] != turn_id
            assert (
                fetch_all(tmp_path, "SELECT status FROM turns WHERE id=?", (turn_id,))[0]["status"]
                == "failed"
            )
    finally:
        use_model(None)


async def test_failed_bot_delete_commit_preserves_files(tmp_path: Path, monkeypatch) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Keep")
    agent = await AgentService().spawn(bot.id)
    workspace = Path(bot.workspace_path)
    checkout = tmp_path / "worktrees" / agent.id
    checkout.mkdir(parents=True)
    for folder in (workspace, checkout):
        (folder / "keep.txt").write_text("uncommitted data")

    async def fail_commit(_session):
        raise RuntimeError("commit blocked")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit blocked"):
        await BotService().delete(bot.id, purge=True)
    assert fetch_all(tmp_path, "SELECT id FROM bots WHERE id=?", (bot.id,))
    for folder in (workspace, checkout):
        assert (folder / "keep.txt").read_text() == "uncommitted data"


@pytest.mark.parametrize("error", [ModelHTTPError(503, "fake"), OSError("offline")])
async def test_compaction_provider_failure_keeps_request(monkeypatch, error) -> None:
    from sevn.runtime import compaction

    async def respond(_messages, _info):
        raise error

    async def cheap():
        return FunctionModel(respond)

    monkeypatch.setattr(compaction, "_cheap_model", cheap)
    messages = [ModelRequest(parts=[UserPromptPart("original message")]) for _ in range(8)]
    context = SimpleNamespace(model=SimpleNamespace(context_window=1), messages=messages)
    assert await compaction.Compaction().before_model_request(None, context) is context
    assert context.messages is messages


async def test_background_turn_does_not_inherit_request_op(tmp_path: Path, monkeypatch) -> None:
    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    async with connected(tmp_path, monkeypatch) as (host, _client):
        op_id = mint_id("op_")

        async def work():
            await asyncio.create_task(host.hub.emit("job.started", "job_test", {}))
            assert await host.hub.oplog.lookup(op_id) is None
            return {"status": "done"}

        assert await host.hub.claim_op(op_id, "test", "hash", work) == {"status": "done"}
        assert (await host.hub.oplog.lookup(op_id)).result == {"status": "done"}


async def test_cancel_lane_excludes_jobs_moved_after_snapshot(tmp_path: Path, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from sevn.domain.jobs import job_lock, park_job
    from sevn.runtime import worker as worker_module

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Move")
    source = await AgentService().spawn(bot.id)
    target = await AgentService().spawn(bot.id)
    job_id = mint_id("job_")
    await JobService().enqueue(job_id, bot.id, source.id, "move me")

    @asynccontextmanager
    async def move_before_lock(selected):
        await park_job(selected, target.id)
        async with job_lock(selected):
            yield

    monkeypatch.setattr(worker_module, "job_lock", move_before_lock)
    async with connected(tmp_path, monkeypatch) as (host, _client):
        worker = bind(host.hub)
        await worker.cancel_agent(source.id)
        row = fetch_all(tmp_path, "SELECT agent_id,status FROM jobs WHERE id=?", (job_id,))[0]
        assert row["agent_id"] == target.id
        assert row["status"] == "queued"


async def test_resume_loaded_before_cancel_cannot_restart_turn(tmp_path: Path, monkeypatch) -> None:
    from sevn.runtime import turn

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Resume")
    agent = await AgentService().spawn(bot.id)
    job_id, turn_id = mint_id("job_"), mint_id("turn_")
    await JobService().enqueue(job_id, bot.id, agent.id, "resume", status="started")
    async with open_session() as session:
        session.add(
            Turn(
                id=turn_id,
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_ids=[job_id],
                status="waiting",
                model=bot.model,
                usage={},
                model_messages=[],
                started_at=utcnow(),
                finished_at=None,
            )
        )
        await session.commit()
    loaded, release = asyncio.Event(), asyncio.Event()
    original = turn._load_resume
    first = True
    calls = 0

    async def pause(selected):
        nonlocal first
        result = await original(selected)
        if first:
            first = False
            loaded.set()
            await release.wait()
        return result

    async def respond(_messages, _info):
        nonlocal calls
        calls += 1
        return ModelResponse(parts=[TextPart("must not execute")])

    monkeypatch.setattr(turn, "_load_resume", pause)
    use_model(FunctionModel(respond))
    try:
        async with connected(tmp_path, monkeypatch) as (host, _client):
            worker = bind(host.hub)
            task = asyncio.create_task(worker.resume(agent.id, turn_id, ()))
            await asyncio.wait_for(loaded.wait(), 5)
            assert await worker.cancel(turn_id) == "cancelled"
            release.set()
            await asyncio.wait_for(task, 5)
            assert calls == 0
            assert (
                fetch_all(tmp_path, "SELECT status FROM turns WHERE id=?", (turn_id,))[0]["status"]
                == "cancelled"
            )
    finally:
        release.set()
        use_model(None)
