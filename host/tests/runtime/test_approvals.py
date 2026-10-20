"""Deferred-tool approvals for the Pydantic AI runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fakes.models import function_model
from support.canary import model_request_payloads, reset_model_requests
from support.chat import (
    assert_prefixed_id,
    connected,
    error_body,
    fetch_all,
    job_done_statuses,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)


def _script() -> object:
    return function_model(
        [
            [{"kind": "tool", "name": "shell", "args": {"command": "echo hi"}}],
            [{"kind": "text", "text": "done"}],
        ]
    )


async def _bot(client: object) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "bots.create",
        {"name": "Nimbus", "access": "full", "op_id": mint_id("op_")},
    )
    return ok(frame)


async def _arm(host: object) -> None:
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    reset_model_requests()
    use_model(_script())
    bind(host.hub)  # type: ignore[attr-defined]


async def _wait_pending(home: Path, client: object) -> dict[str, object]:
    await poll_rows(
        home,
        "SELECT id FROM pending_requests WHERE status = 'waiting'",
        (),
        lambda rows: bool(rows),
    )
    frame, _earlier = await request(client, "pending.list", {})
    body = ok(frame)
    pending = body["pending"]
    assert isinstance(pending, list) and pending
    item = pending[0]
    assert isinstance(item, dict)
    return item


async def test_deferred_tool_creates_pending_and_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        item = await _wait_pending(tmp_path, client)
        assert item["kind"] == "approval"
        assert_prefixed_id(item["id"], "pend_")
        turns = fetch_all(tmp_path, "SELECT status FROM turns")
        assert turns[0]["status"] == "waiting"
        stored = await host.outbox.since(0)
        assert any(row.type == "pending.created" for row in stored)


async def test_approve_resumes_and_runs_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        item = await _wait_pending(tmp_path, client)
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": item["id"], "answer": "approve", "op_id": mint_id("op_")},
        )
        ok(frame)
        await poll_rows(
            tmp_path,
            "SELECT status FROM turns",
            (),
            lambda rows: bool(rows) and rows[0]["status"] == "done",
        )
        stored = await host.outbox.since(0)
        assert any(row.type == "pending.resolved" for row in stored)
        payloads = model_request_payloads()
        assert len(payloads) >= 2
        blob = json.dumps(payloads[-1]["messages"])
        assert "tool-return" in blob or "tool_return" in blob
        assert '"outcome": "denied"' not in blob and '"outcome":"denied"' not in blob


async def test_deny_returns_denied_to_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        item = await _wait_pending(tmp_path, client)
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": item["id"], "answer": "deny", "op_id": mint_id("op_")},
        )
        ok(frame)
        await poll_rows(
            tmp_path,
            "SELECT status FROM turns",
            (),
            lambda rows: bool(rows) and rows[0]["status"] == "done",
        )
        payloads = model_request_payloads()
        assert len(payloads) >= 2
        blob = json.dumps(payloads[-1]["messages"])
        assert '"denied"' in blob or "tool-denied" in blob


async def test_waiting_turn_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.recovery import recover
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        item = await _wait_pending(tmp_path, client)
        worker = bind(host.hub)
        await worker.aclose()
        still = fetch_all(
            tmp_path,
            "SELECT id FROM pending_requests WHERE id = ?",
            (item["id"],),
        )
        assert still
        await recover()
        listed, _earlier = await request(client, "pending.list", {})
        pending = ok(listed)["pending"]
        assert isinstance(pending, list)
        assert any(entry["id"] == item["id"] for entry in pending)
        bind(host.hub)
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": item["id"], "answer": "approve", "op_id": mint_id("op_")},
        )
        ok(frame)
        await poll_rows(
            tmp_path,
            "SELECT status FROM turns",
            (),
            lambda rows: bool(rows) and rows[0]["status"] == "done",
        )


async def test_answer_twice_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        item = await _wait_pending(tmp_path, client)
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": item["id"], "answer": "approve", "op_id": mint_id("op_")},
        )
        ok(frame)
        await poll_rows(
            tmp_path,
            "SELECT status FROM pending_requests WHERE id = ?",
            (item["id"],),
            lambda rows: bool(rows) and rows[0]["status"] == "resolved",
        )
        again, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": item["id"], "answer": "approve", "op_id": mint_id("op_")},
        )
        assert error_body(again)["code"] == "pending_resolved"


async def test_message_during_approval_stays_queued_until_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A send while an approval is open stays on that agent and runs after the answer."""
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    follow_up = "queued-while-waiting"
    reset_model_requests()
    use_model(
        function_model(
            [
                [{"kind": "tool", "name": "shell", "args": {"command": "echo hi"}}],
                [{"kind": "text", "text": "approved"}],
                [{"kind": "text", "text": "later"}],
            ]
        )
    )
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        bind(host.hub)
        bot = await _bot(client)
        first_frame, _earlier = await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        first = ok(first_frame)
        item = await _wait_pending(tmp_path, client)
        calls_while_waiting = len(model_request_payloads())
        second_frame, _earlier = await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": follow_up, "op_id": mint_id("op_")},
        )
        second = ok(second_frame)
        assert second["agent_id"] == first["agent_id"]
        agents = fetch_all(tmp_path, "SELECT id FROM agents")
        assert len(agents) == 1
        deadline = asyncio.get_running_loop().time() + 0.5
        while asyncio.get_running_loop().time() < deadline:
            queued = fetch_all(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (second["job_id"],),
            )
            assert queued[0]["status"] == "queued"
            assert len(model_request_payloads()) == calls_while_waiting
            await asyncio.sleep(0.02)
        frame, _earlier = await request(
            client,
            "pending.answer",
            {"pending_id": item["id"], "answer": "approve", "op_id": mint_id("op_")},
        )
        ok(frame)
        await poll_rows(
            tmp_path,
            "SELECT id, status FROM jobs ORDER BY created_at",
            (),
            lambda rows: len(rows) == 2 and all(row["status"] == "done" for row in rows),
        )
        payloads = model_request_payloads()
        assert len(payloads) > calls_while_waiting
        blob = json.dumps(payloads[-1]["messages"])
        assert "run it" in blob
        assert follow_up in blob


async def test_cancel_persisted_waiting_approval_releases_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """turns.cancel of an already stored waiting approval ends that turn and frees the agent."""
    follow_up = "after cancel"
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        sent, _earlier = await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        first = ok(sent)
        item = await _wait_pending(tmp_path, client)
        waiting = fetch_all(tmp_path, "SELECT id, status FROM turns")
        assert len(waiting) == 1 and waiting[0]["status"] == "waiting"
        turn_id = str(waiting[0]["id"])
        job_id = str(first["job_id"])
        started = fetch_all(
            tmp_path,
            "SELECT status FROM jobs WHERE id = ?",
            (job_id,),
        )
        assert started[0]["status"] == "started"
        frame, _earlier = await request(
            client,
            "turns.cancel",
            {"turn_id": turn_id, "op_id": mint_id("op_")},
        )
        reported_status = str(ok(frame)["status"])
        assert reported_status == "cancelled"
        later, _earlier = await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": follow_up, "op_id": mint_id("op_")},
        )
        follow = ok(later)
        deadline = asyncio.get_running_loop().time() + 2
        turn_status = ""
        pending_status = ""
        job_status = ""
        later_status = ""
        while asyncio.get_running_loop().time() < deadline:
            turn_rows = fetch_all(
                tmp_path,
                "SELECT status FROM turns WHERE id = ?",
                (turn_id,),
            )
            pending_rows = fetch_all(
                tmp_path,
                "SELECT status FROM pending_requests WHERE id = ?",
                (str(item["id"]),),
            )
            job_rows = fetch_all(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (job_id,),
            )
            later_rows = fetch_all(
                tmp_path,
                "SELECT status FROM jobs WHERE id = ?",
                (str(follow["job_id"]),),
            )
            turn_status = str(turn_rows[0]["status"])
            pending_status = str(pending_rows[0]["status"])
            job_status = str(job_rows[0]["status"])
            later_status = str(later_rows[0]["status"])
            if (
                turn_status == "cancelled"
                and pending_status != "waiting"
                and job_status != "started"
                and later_status == "done"
            ):
                break
            await asyncio.sleep(0.02)
        assert turn_status == "cancelled", (
            reported_status,
            turn_status,
            pending_status,
            job_status,
            later_status,
        )
        assert pending_status != "waiting", pending_status
        assert job_status != "started", job_status
        assert later_status == "done", later_status
        assert follow["agent_id"] == first["agent_id"]
        agents = fetch_all(tmp_path, "SELECT id FROM agents")
        assert len(agents) == 1
        still = fetch_all(
            tmp_path,
            "SELECT status FROM turns WHERE id = ?",
            (turn_id,),
        )
        assert still[0]["status"] == "cancelled"
        payloads = model_request_payloads()
        blob = json.dumps(payloads[-1]["messages"])
        assert follow_up in blob


async def test_cancel_persisted_waiting_emits_job_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling a stored waiting turn emits a durable job.done for that job."""
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        sent, _earlier = await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        first = ok(sent)
        await _wait_pending(tmp_path, client)
        waiting = fetch_all(tmp_path, "SELECT id, status FROM turns")
        assert len(waiting) == 1 and waiting[0]["status"] == "waiting"
        turn_id = str(waiting[0]["id"])
        job_id = str(first["job_id"])
        frame, _earlier = await request(
            client,
            "turns.cancel",
            {"turn_id": turn_id, "op_id": mint_id("op_")},
        )
        assert str(ok(frame)["status"]) == "cancelled"
        await poll_rows(
            tmp_path,
            "SELECT status FROM turns WHERE id = ?",
            (turn_id,),
            lambda rows: bool(rows) and rows[0]["status"] == "cancelled",
        )
        stored = await host.outbox.since(0)
        done = job_done_statuses(stored, job_id)
        types = [str(getattr(row, "type", "")) for row in stored]
        proof = (
            f"job.done={types.count('job.done')} "
            f"turn.finished={types.count('turn.finished')} "
            f"{','.join(types)}"
        )
        assert done == ["cancelled"], proof


def _stored_object(value: object) -> dict[str, object]:
    loaded: object = json.loads(value if isinstance(value, str) else json.dumps(value))
    if not isinstance(loaded, dict):
        raise AssertionError(value)
    return {str(key): item for key, item in loaded.items()}


async def test_pending_list_returns_deferred_tool_name_and_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pending.list returns the tool name and arguments stored on the pending row."""
    load_modules("sevn.api.bots", "sevn.api.messages", "sevn.api.pending")
    async with connected(tmp_path, monkeypatch) as (host, client):
        await _arm(host)
        bot = await _bot(client)
        await request(
            client,
            "messages.send",
            {"bot_id": bot["id"], "text": "run it", "op_id": mint_id("op_")},
        )
        item = await _wait_pending(tmp_path, client)
        rows = fetch_all(
            tmp_path,
            "SELECT payload FROM pending_requests WHERE id = ?",
            (item["id"],),
        )
        payload = _stored_object(rows[0]["payload"])
        listed = {"name": item.get("name"), "args": item.get("args")}
        stored = {"name": payload.get("name"), "args": payload.get("args")}
        assert listed == stored == {"name": "shell", "args": {"command": "echo hi"}}, item
