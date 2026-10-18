"""Claude runtime over FakeClaudeClient, plus one live turn."""

from __future__ import annotations

import asyncio
import inspect
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
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
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
                                "op_id": mint_id("op_"),
                            },
                        )
                    )[0]
                )
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
