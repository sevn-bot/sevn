"""Claude runtime over FakeClaudeClient, plus one live turn."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator
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
                    {
                        "name": "Claude",
                        "runtime": "claude",
                        "access": "full",
                        "op_id": mint_id("op_"),
                    },
                )
            )[0]
        )
        await _network_on(client, str(created["id"]))
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
                    {
                        "name": "Claude",
                        "runtime": "claude",
                        "access": "full",
                        "op_id": mint_id("op_"),
                    },
                )
            )[0]
        )
        await _network_on(client, str(created["id"]))
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
                    {
                        "name": "Claude",
                        "runtime": "claude",
                        "access": "full",
                        "op_id": mint_id("op_"),
                    },
                )
            )[0]
        )
        await _network_on(client, str(created["id"]))
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
        stored = " ".join(str(row["parts"]) for row in messages)
        assert "resend" in stored.lower()


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


class _AbortOnInterrupt(FakeClaudeClient):
    """Yield one aborted result after ``interrupt``, and nothing before it."""

    def __init__(self, terminal_reason: str) -> None:
        super().__init__()
        self.terminal_reason = terminal_reason
        self.started = asyncio.Event()
        self._release = asyncio.Event()

    async def interrupt(self) -> None:
        await super().interrupt()
        self._release.set()

    async def receive_response(self) -> AsyncIterator[dict[str, object]]:
        self.started.set()
        await self._release.wait()
        yield {
            "type": "result",
            "terminal_reason": self.terminal_reason,
            "usage": {},
        }


class _PermissionAbort(FakeClaudeClient):
    """Open one tool permission, then end the turn when ``interrupt`` runs.

    The permission callback runs beside ``receive_response``, as the SDK does:
    interrupt cancels that wait, and the turn then yields an aborted result.
    A later ``receive_response`` finishes immediately so a resume cannot hang.
    """

    def __init__(self) -> None:
        super().__init__()
        self._release = asyncio.Event()
        self._permission_task: asyncio.Task[object] | None = None
        self._calls = 0

    async def interrupt(self) -> None:
        await super().interrupt()
        permission = self._permission_task
        if permission is not None and not permission.done():
            permission.cancel()
        self._release.set()

    async def receive_response(self) -> AsyncIterator[dict[str, object]]:
        self._calls += 1
        if self._calls > 1:
            yield {"type": "result", "usage": {}}
            return
        callback = self._can_use_tool
        if not callable(callback):
            raise RuntimeError("claude runtime did not pass can_use_tool")

        async def _ask() -> object:
            outcome: object = callback("Bash", {"command": "ls"}, "req_1")
            if inspect.isawaitable(outcome):
                return await outcome
            return outcome

        self._permission_task = asyncio.create_task(_ask())
        self.permission_started.set()
        await self._release.wait()
        yield {
            "type": "result",
            "terminal_reason": "aborted_tools",
            "usage": {},
        }


def _assistant_text(body: dict[str, Any]) -> str:
    messages = body["messages"]
    assert isinstance(messages, list)
    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        raw_parts = message.get("parts")
        if not isinstance(raw_parts, list):
            continue
        for part in raw_parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts)


_CANCEL_NOTICES = ("turn produced no result", "This turn failed.")


@pytest.mark.parametrize("terminal_reason", ["aborted_streaming", "aborted_tools"])
async def test_cancelled_claude_abort_ends_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_reason: str,
) -> None:
    """turns.cancel stores an aborted Claude result as cancelled, not failed."""
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    fake = _AbortOnInterrupt(terminal_reason)
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "runtime": "claude",
                                "access": "full",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {
                        "bot_id": created["id"],
                        "text": "stop this",
                        "op_id": mint_id("op_"),
                    },
                )
                await asyncio.wait_for(fake.started.wait(), timeout=2)
                turns = await poll_rows(
                    tmp_path,
                    "SELECT id FROM turns",
                    (),
                    lambda rows: bool(rows),
                )
                turn_id = str(turns[0]["id"])
                frame, _earlier = await request(
                    client,
                    "turns.cancel",
                    {"turn_id": turn_id, "op_id": mint_id("op_")},
                )
                ok(frame)
                rows = await poll_rows(
                    tmp_path,
                    "SELECT status FROM turns WHERE id = ?",
                    (turn_id,),
                    lambda found: (
                        bool(found)
                        and found[0]["status"] in {"cancelled", "failed", "done", "interrupted"}
                    ),
                )
                listed, _listed_earlier = await request(
                    client,
                    "messages.list",
                    {"bot_id": created["id"]},
                )
                assistant = _assistant_text(ok(listed))
                status = str(rows[0]["status"])
                leaked = any(notice in assistant for notice in _CANCEL_NOTICES)
                assert status == "cancelled" and not leaked, (
                    terminal_reason,
                    status,
                    assistant,
                )
            finally:
                await worker.aclose()
    finally:
        use_client(None)


_PARTIAL = "kept partial"
_PROVIDER_ECHO = "provider-echo-CANARY-4c1e"


async def test_runtime_error_keeps_streamed_text_and_hides_provider_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Claude error keeps streamed text, stores a fixed notice, and logs the code."""
    from sevn.log import logger
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    fake = FakeClaudeClient(
        script=[
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": _PARTIAL},
                },
            },
            {
                "type": "result",
                "is_error": True,
                "subtype": "rate_limit",
                "errors": [_PROVIDER_ECHO],
                "result": _PROVIDER_ECHO,
                "usage": {},
            },
        ]
    )
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages")
    logged: list[str] = []
    sink_id = logger.add(lambda message: logged.append(str(message)))
    try:
        async with connected(tmp_path, monkeypatch) as (_host, client):
            worker = bind(_host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "runtime": "claude",
                                "access": "full",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {
                        "bot_id": created["id"],
                        "text": "explain the tide",
                        "op_id": mint_id("op_"),
                    },
                )
                await poll_rows(
                    tmp_path,
                    "SELECT status FROM turns",
                    (),
                    lambda rows: bool(rows) and rows[0]["status"] == "failed",
                )
                turns = fetch_all(tmp_path, "SELECT status, model_messages FROM turns")
                jobs = fetch_all(tmp_path, "SELECT status FROM jobs")
                events = fetch_all(tmp_path, "SELECT type, payload FROM events")
                listed, _earlier = await request(
                    client,
                    "messages.list",
                    {"bot_id": created["id"]},
                )
                assistant = _assistant_text(ok(listed))
                stored = json.dumps(
                    {
                        "turns": [dict(row) for row in turns],
                        "jobs": [dict(row) for row in jobs],
                        "events": [dict(row) for row in events],
                        "messages": ok(listed),
                    },
                    default=str,
                )
                log_text = "\n".join(logged)
                raw_messages = turns[0]["model_messages"]
                parsed: object = None if raw_messages is None else json.loads(str(raw_messages))
                assert turns[0]["status"] == "failed"
                assert parsed is None
                assert jobs[0]["status"] == "failed"
                assert assistant == f"{_PARTIAL}\nThis turn failed."
                assert "turn produced no result" not in stored
                assert _PROVIDER_ECHO not in stored
                assert _PROVIDER_ECHO not in log_text
                assert "rate_limit" in log_text
            finally:
                await worker.aclose()
    finally:
        logger.remove(sink_id)
        use_client(None)


async def test_failed_claude_turn_keeps_its_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error result reports what the run used; the failed turn stores it."""
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    fake = FakeClaudeClient(
        script=[
            {
                "type": "result",
                "is_error": True,
                "subtype": "error_max_turns",
                "usage": {"input_tokens": 30, "output_tokens": 12},
                "total_cost_usd": 0.03,
                "num_turns": 4,
            },
        ]
    )
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (_host, client):
            worker = bind(_host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "runtime": "claude",
                                "access": "full",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {"bot_id": created["id"], "text": "go long", "op_id": mint_id("op_")},
                )
                rows = await poll_rows(
                    tmp_path,
                    "SELECT status, usage FROM turns",
                    (),
                    lambda found: bool(found) and found[0]["status"] == "failed",
                )
                usage = json.loads(str(rows[0]["usage"]))
                assert usage["requests"] == 4
                assert usage["output_tokens"] == 12
                assert usage["cost_source"] == "subscription"
                assert usage["estimated_usd"] == pytest.approx(0.03)
            finally:
                await worker.aclose()
    finally:
        use_client(None)


async def test_cancelled_claude_turn_closes_open_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """turns.cancel closes a waiting Claude permission and does not run the prompt again."""
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    prompt = "stop this"
    fake = _PermissionAbort()
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "runtime": "claude",
                                "access": "full",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {
                        "bot_id": created["id"],
                        "text": prompt,
                        "op_id": mint_id("op_"),
                    },
                )
                waiting = await poll_rows(
                    tmp_path,
                    "SELECT id, status FROM pending_requests",
                    (),
                    lambda rows: bool(rows) and rows[0]["status"] == "waiting",
                )
                turns = await poll_rows(
                    tmp_path,
                    "SELECT id FROM turns",
                    (),
                    lambda rows: bool(rows),
                )
                turn_id = str(turns[0]["id"])
                pending_id = str(waiting[0]["id"])
                frame, _earlier = await request(
                    client,
                    "turns.cancel",
                    {"turn_id": turn_id, "op_id": mint_id("op_")},
                )
                ok(frame)
                await poll_rows(
                    tmp_path,
                    "SELECT status FROM turns WHERE id = ?",
                    (turn_id,),
                    lambda rows: bool(rows) and rows[0]["status"] == "cancelled",
                )
                pending = fetch_all(
                    tmp_path,
                    "SELECT status FROM pending_requests WHERE id = ?",
                    (pending_id,),
                )
                pending_status = str(pending[0]["status"]) if pending else "absent"
                answered, _answered_earlier = await request(
                    client,
                    "pending.answer",
                    {
                        "pending_id": pending_id,
                        "answer": "approve",
                        "op_id": mint_id("op_"),
                    },
                    timeout_s=5,
                )
                finished = fetch_all(
                    tmp_path,
                    "SELECT status FROM turns WHERE id = ?",
                    (turn_id,),
                )
                turn_status = str(finished[0]["status"])
                queries = list(fake.queries)
                assert (
                    pending_status != "waiting"
                    and queries == [prompt]
                    and turn_status == "cancelled"
                ), (pending_status, queries, turn_status, answered.get("t"))
            finally:
                await worker.aclose()
    finally:
        use_client(None)


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


def _stored_object(value: object) -> dict[str, object]:
    loaded: object = json.loads(value if isinstance(value, str) else json.dumps(value))
    if not isinstance(loaded, dict):
        raise AssertionError(value)
    return {str(key): item for key, item in loaded.items()}


async def test_pending_list_returns_claude_permission_name_and_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pending.list returns the tool name and arguments stored for a Claude permission."""
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
    listed: dict[str, object] = {}
    stored: dict[str, object] = {}
    item: dict[str, Any] = {}
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "runtime": "claude",
                                "access": "full",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {"bot_id": created["id"], "text": "ls", "op_id": mint_id("op_")},
                )
                await asyncio.wait_for(fake.permission_started.wait(), timeout=2)
                rows = await poll_rows(
                    tmp_path,
                    "SELECT id, payload FROM pending_requests WHERE status = 'waiting'",
                    (),
                    lambda found: bool(found),
                )
                frame, _earlier = await request(client, "pending.list", {})
                pending = ok(frame)["pending"]
                raw_item = pending[0]
                if isinstance(raw_item, dict):
                    item = raw_item
                stored = _stored_object(rows[0]["payload"])
                listed = {"name": item.get("name"), "args": item.get("args")}
            finally:
                await worker.aclose()
    finally:
        use_client(None)
    assert (
        listed
        == {"name": stored.get("name"), "args": stored.get("args")}
        == {
            "name": "Bash",
            "args": {"command": "ls"},
        }
    ), item


async def test_claude_turn_presents_bot_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Claude turn presents the bot's instructions on connect or in the prompt.

    The pydantic_ai A.2.5 layout stays as it is. This test only requires the
    instruction text to reach FakeClaudeClient.
    """
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    instructions = "Count purple urchins before you answer."
    fake = FakeClaudeClient(script=[{"type": "result", "usage": {}}])
    use_client(fake)
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "title": "Tide guide",
                                "scope": "Rocky shore",
                                "instructions": instructions,
                                "runtime": "claude",
                                "access": "full",
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {
                        "bot_id": created["id"],
                        "text": "hello from the shore",
                        "op_id": mint_id("op_"),
                    },
                )
                await poll_rows(
                    tmp_path,
                    "SELECT status FROM jobs",
                    (),
                    lambda rows: bool(rows) and rows[0]["status"] == "done",
                )
            finally:
                await worker.aclose()
    finally:
        use_client(None)
    recorded = {"connects": fake.connects, "queries": list(fake.queries)}
    assert instructions in json.dumps(recorded, default=str), recorded


@pytest.mark.parametrize("policy", ["auto", "allow_all"])
async def test_claude_non_ask_policy_waits_for_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
) -> None:
    """Bot policies auto and allow_all wait for a tool answer, the same as ask."""
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
    status = ""
    waiting: list[dict[str, object]] = []
    results: list[object] = []
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            worker = bind(host.hub)
            try:
                created = ok(
                    (
                        await request(
                            client,
                            "bots.create",
                            {
                                "name": "Claude",
                                "runtime": "claude",
                                "access": "full",
                                "approval_policy": policy,
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
                await _network_on(client, str(created["id"]))
                await request(
                    client,
                    "messages.send",
                    {"bot_id": created["id"], "text": "ls", "op_id": mint_id("op_")},
                )
                deadline = asyncio.get_running_loop().time() + 2
                while asyncio.get_running_loop().time() < deadline:
                    jobs = [dict(row) for row in fetch_all(tmp_path, "SELECT status FROM jobs")]
                    waiting = [
                        dict(row)
                        for row in fetch_all(
                            tmp_path,
                            "SELECT id, status FROM pending_requests WHERE status = 'waiting'",
                        )
                    ]
                    status = str(jobs[0]["status"]) if jobs else ""
                    results = list(fake.permission_results)
                    if waiting and results == []:
                        break
                    await asyncio.sleep(0.02)
            finally:
                await worker.aclose()
    finally:
        use_client(None)
    assert waiting and results == [] and status != "done", (
        policy,
        status,
        waiting,
        results,
        fake.permission_started.is_set(),
    )


def test_blanked_env_keeps_path_and_blanks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/Users/sevn")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secretvalue")
    monkeypatch.setenv("SEVN_SECRET_TOKEN", "supersecretvalue")
    from sevn.runtime.runtimes.claude import blanked_env

    env = blanked_env()
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/Users/sevn"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["SEVN_SECRET_TOKEN"] == ""
    assert "sk-ant-secretvalue" not in env.values()
    assert "supersecretvalue" not in env.values()


@pytest.mark.parametrize(
    ("access", "network"),
    [("workspace", "off"), ("workspace", "on"), ("isolated", "on"), ("full", "off")],
)
async def test_claude_refuses_unsupported_confinement_before_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, access: str, network: str
) -> None:
    from sevn.domain.bots import BotService
    from sevn.runtime.errors import TurnError
    from sevn.runtime.runtimes.claude import ClaudeRuntime

    _host, _client, created = await _claude_agent(tmp_path, monkeypatch)
    try:
        await BotService().update(
            created["id"], access=access, network=network, fields={"access", "network"}
        )
        fake = FakeClaudeClient(script=_HI)
        with pytest.raises(TurnError, match="Claude requires full access and network on"):
            await ClaudeRuntime(client=fake).open(created["agent"])
        assert fake.connects == []
        assert fake.queries == []
    finally:
        await _close(created)


def test_claude_env_blanks_host_agent_socket_and_xdg_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.runtime.runtimes.claude import blanked_env

    keys = ("SSH_AUTH_SOCK", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")
    for key in keys:
        monkeypatch.setenv(key, "fixture-value")
    env = blanked_env()
    assert all(env[key] == "" for key in keys)


async def _network_on(client: object, bot_id: str) -> None:
    ok(
        (
            await request(
                client, "bots.update", {"bot_id": bot_id, "network": "on", "op_id": mint_id("op_")}
            )
        )[0]
    )
