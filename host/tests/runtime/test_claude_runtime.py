"""Claude runtime over FakeClaudeClient, plus one live turn (green after W5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_claude import FakeClaudeClient
from support.chat import (
    connected,
    fetch_all,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)

pytestmark = pytest.mark.xfail(reason="green after W5", strict=False)

_HI = [
    {"type": "system", "subtype": "init", "session_id": "sess_1"},
    {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "hi"},
        },
    },
    {
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "hmm"},
        },
    },
    {
        "type": "assistant",
        "block": {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
    },
    {"type": "result", "usage": {"output_tokens": 2}},
]


async def _claude_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any]:
    from sevn.domain.agents import AgentService

    load_modules("sevn.api.bots")
    context = connected(tmp_path, monkeypatch)
    entered = await context.__aenter__()
    host, client = entered
    try:
        created = ok(
            (
                await request(
                    client,
                    "bots.create",
                    {"name": "Claude", "runtime": "claude", "op_id": mint_id("op_")},
                )
            )[0]
        )
        agent = await AgentService().spawn(bot_id=str(created["id"]))
    except Exception:
        await context.__aexit__(None, None, None)
        raise
    created["agent"] = agent
    created["_context"] = context
    return host, client, created


async def _close(created: dict[str, Any]) -> None:
    await created["_context"].__aexit__(None, None, None)


async def _consume(runtime: Any, agent: Any, text: str = "hi") -> list[Any]:
    from sevn.runtime.base import TurnContext

    await runtime.open(agent)
    events: list[Any] = []
    async for event in runtime.run_turn(
        TurnContext(agent=agent, text=text, turn_id=mint_id("turn_"))
    ):
        events.append(event)
    return events


async def test_turn_maps_events_to_runtime_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.runtimes.claude import ClaudeRuntime

    _host, _client, created = await _claude_agent(tmp_path, monkeypatch)
    try:
        fake = FakeClaudeClient(script=_HI)
        events = await _consume(ClaudeRuntime(client=fake), created["agent"])
        by_kind: dict[str, list[Any]] = {}
        for event in events:
            by_kind.setdefault(event.kind, []).append(event)
        assert by_kind["text_delta"][0].text == "hi"
        assert by_kind["thinking_delta"][0].text == "hmm"
        assert by_kind["tool_call_started"][0].name == "Bash"
        assert by_kind["session_bound"][0].session_ref == "sess_1"
        assert "turn_finished" in by_kind
    finally:
        await _close(created)


async def test_session_ref_saved_and_used_for_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.runtimes.claude import ClaudeRuntime

    _host, _client, created = await _claude_agent(tmp_path, monkeypatch)
    try:
        fake = FakeClaudeClient(
            script=[
                {"type": "system", "subtype": "init", "session_id": "sess_1"},
                {"type": "result", "usage": {}},
            ]
        )
        runtime = ClaudeRuntime(client=fake)
        agent = created["agent"]
        await _consume(runtime, agent)
        rows = fetch_all(
            tmp_path,
            "SELECT runtime_session_ref FROM agents WHERE id = ?",
            (agent.id,),
        )
        assert rows[0]["runtime_session_ref"] == "sess_1"
        loaded = await AgentService().get(agent.id)
        await runtime.open(loaded)
        assert fake.connects[-1]["resume"] == "sess_1"
    finally:
        await _close(created)


async def test_can_use_tool_creates_pending_and_blocks_until_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    fake = FakeClaudeClient(
        script=[
            {
                "kind": "permission",
                "tool": "Bash",
                "args": {"command": "ls"},
                "request_id": "req_1",
            },
            {"type": "result", "usage": {}},
        ]
    )
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        created = ok(
            (
                await request(
                    client,
                    "bots.create",
                    {"name": "Claude", "runtime": "claude", "op_id": mint_id("op_")},
                )
            )[0]
        )
        await request(
            client,
            "messages.send",
            {"bot_id": created["id"], "text": "ls", "op_id": mint_id("op_")},
        )
        await asyncio.wait_for(fake.permission_started.wait(), timeout=2)
        pending = await poll_rows(
            tmp_path,
            "SELECT id FROM pending_requests WHERE status = 'waiting'",
            (),
            lambda rows: bool(rows),
        )
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": pending[0]["id"], "answer": "approve", "op_id": mint_id("op_")},
        )
        ok(frame)
        assert fake.permission_results
        await poll_rows(
            tmp_path,
            "SELECT status FROM jobs",
            (),
            lambda rows: bool(rows) and rows[0]["status"] == "done",
        )


async def test_restart_marks_waiting_claude_turn_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.recovery import recover
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    fake = FakeClaudeClient(
        script=[
            {
                "kind": "permission",
                "tool": "Bash",
                "args": {"command": "ls"},
                "request_id": "req_1",
            }
        ]
    )
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        worker = bind(host.hub)
        created = ok(
            (
                await request(
                    client,
                    "bots.create",
                    {"name": "Claude", "runtime": "claude", "op_id": mint_id("op_")},
                )
            )[0]
        )
        await request(
            client,
            "messages.send",
            {"bot_id": created["id"], "text": "ls", "op_id": mint_id("op_")},
        )
        await asyncio.wait_for(fake.permission_started.wait(), timeout=2)
        await poll_rows(
            tmp_path,
            "SELECT id FROM pending_requests WHERE status = 'waiting'",
            (),
            lambda rows: bool(rows),
        )
        await worker.aclose()
        await recover()
        turns = fetch_all(tmp_path, "SELECT status FROM turns")
        assert turns[0]["status"] == "interrupted"
        messages = fetch_all(tmp_path, "SELECT parts FROM messages")
        assert "resend" in repr(messages).lower()


async def test_interrupt_calls_client_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.runtimes.claude import ClaudeRuntime

    _host, _client, created = await _claude_agent(tmp_path, monkeypatch)
    task: asyncio.Task[list[Any]] | None = None
    try:
        fake = FakeClaudeClient(
            script=[
                {
                    "kind": "permission",
                    "tool": "Bash",
                    "args": {"command": "ls"},
                    "request_id": "req_1",
                }
            ]
        )
        runtime = ClaudeRuntime(client=fake)
        task = asyncio.create_task(_consume(runtime, created["agent"]))
        await asyncio.wait_for(fake.permission_started.wait(), timeout=2)
        await runtime.interrupt(created["agent"].id)
        assert fake.interrupts == 1
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await _close(created)


async def test_cwd_is_bot_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.runtimes.claude import ClaudeRuntime

    _host, _client, created = await _claude_agent(tmp_path, monkeypatch)
    try:
        fake = FakeClaudeClient(script=[{"type": "result", "usage": {}}])
        await _consume(ClaudeRuntime(client=fake), created["agent"], text="hi")
        assert fake.connects
        assert Path(str(fake.connects[0]["cwd"])) == Path(str(created["workspace_path"]))
    finally:
        await _close(created)


@pytest.mark.live
async def test_live_claude_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.runtimes.claude import ClaudeRuntime

    _host, _client, created = await _claude_agent(tmp_path, monkeypatch)
    try:
        texts: list[str] = []
        async with asyncio.timeout(90):
            events = await _consume(
                ClaudeRuntime(),
                created["agent"],
                text="Reply with the single word pong.",
            )
        for event in events:
            if event.kind == "text_delta" and event.text:
                texts.append(event.text)
        assert "".join(texts).strip()
    finally:
        await _close(created)
