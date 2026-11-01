"""Publication and model-boundary regressions from review 5727983753."""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from sevn.domain.bots import BotService
from sevn.runtime.models import use_model
from sevn.runtime.worker import bind
from support.botcore import arm_configured, upgrade_home
from support.chat import connected, fetch_all, load_modules, mint_id, ok, poll_rows, request


@pytest.mark.parametrize(
    "tool,args",
    [
        ("read_file", {"path": "fixture.txt"}),
        ("grep", {"pattern": "fixture", "path": "fixture.txt"}),
        ("shell", {"command": "cat fixture.txt"}),
    ],
)
async def test_registered_secret_never_enters_tool_return_or_history(
    tmp_path, monkeypatch, tool, args
):
    from sevn.secrets.registry import register

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof", approval_policy="auto")
    canary = secrets.token_urlsafe(32)
    register("review_canary", canary)
    await asyncio.to_thread(
        Path(bot.workspace_path, "fixture.txt").write_text, f"fixture {canary}\n"
    )
    returns = []
    captured = []

    async def respond(messages, _info):
        captured.append(str(messages))
        found = [
            part
            for msg in messages
            for part in msg.parts
            if isinstance(part, ToolReturnPart) and part.tool_name == tool
        ]
        if not found:
            return ModelResponse(parts=[ToolCallPart(tool, args, tool_call_id="call_fixture")])
        returns.extend(found)
        return ModelResponse(parts=[TextPart("done")])

    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            sent = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot.id, "text": "read fixture", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id=?",
                (sent["job_id"],),
                lambda rows: rows[0]["status"] == "done",
            )
    finally:
        use_model(None)
    assert returns
    assert "fixture" in str(returns)
    assert canary not in str(captured)
    for table in ("turns", "messages", "events", "op_log"):
        assert canary not in str(fetch_all(tmp_path, f"SELECT * FROM {table}"))  # noqa: S608


async def test_pump_cannot_claim_job_before_message_attachment(tmp_path, monkeypatch):
    from sevn.domain import routing

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Proof")
    first_started, finish_first, attaching, attach = (asyncio.Event() for _ in range(4))
    calls = 0

    async def respond(_messages, _info):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await finish_first.wait()
        return ModelResponse(parts=[TextPart("done")])

    original = routing._attach_user_message

    async def pause(*args, **kwargs):
        attaching.set()
        await attach.wait()
        return await original(*args, **kwargs)

    use_model(FunctionModel(respond))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            sent = ok(
                (
                    await request(
                        client,
                        "messages.send",
                        {"bot_id": bot.id, "text": "first", "op_id": mint_id("op_")},
                    )
                )[0]
            )
            await asyncio.wait_for(first_started.wait(), 5)
            monkeypatch.setattr(routing, "_attach_user_message", pause)
            following = asyncio.create_task(
                request(
                    client,
                    "messages.send",
                    {
                        "bot_id": bot.id,
                        "agent_id": sent["agent_id"],
                        "text": "second",
                        "op_id": mint_id("op_"),
                    },
                )
            )
            await asyncio.wait_for(attaching.wait(), 5)
            finish_first.set()
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs WHERE id=?",
                (sent["job_id"],),
                lambda rows: rows[0]["status"] == "done",
            )
            await asyncio.sleep(0.1)
            assert calls == 1
            attach.set()
            ok((await following)[0])
            await worker.settle(sent["agent_id"])
            await poll_rows(
                tmp_path,
                "SELECT status FROM jobs",
                (),
                lambda rows: all(row["status"] == "done" for row in rows),
            )
    finally:
        finish_first.set()
        attach.set()
        use_model(None)
    users = fetch_all(tmp_path, "SELECT parts FROM messages WHERE role='user'")
    assert len(users) == 2
    assert sum("second" in json.dumps(row["parts"]) for row in users) == 1
    assert not fetch_all(tmp_path, "SELECT id FROM turns WHERE status='queued'")
