"""Deferred-tool approvals for the Pydantic AI runtime."""

from __future__ import annotations

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
        {"name": "Nimbus", "op_id": mint_id("op_")},
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
