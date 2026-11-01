"""Owner-only allow_all mode."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest
from support.chat import connected, error_body, fetch_all, load_modules, mint_id, ok, request


def _stream(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


class _Proc:
    returncode = 0
    pid = 0

    def __init__(self) -> None:
        self.stdout = _stream(b"ok")
        self.stderr = _stream(b"")

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"ok", b""

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        return None


def _record_exec(monkeypatch: pytest.MonkeyPatch, recorded: list[tuple[object, ...]]) -> None:
    async def fake_exec(*args: object, **_kwargs: object) -> _Proc:
        recorded.append(args)
        return _Proc()

    def fake_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded.append(args)
        command = args[0] if args else []
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    def refuse(*args: object, **_kwargs: object) -> object:
        raise AssertionError(f"refusing to exec {args!r}")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(os, "system", refuse)


def _saw_rm(recorded: list[tuple[object, ...]]) -> bool:
    flat = " ".join(str(part) for args in recorded for part in args)
    return "rm" in flat and "-rf" in flat


async def _mode(client: object, mode: str, confirm: str) -> dict[str, object]:
    frame, _earlier = await request(
        client,
        "host.set_sandbox_mode",
        {"mode": mode, "confirm": confirm, "op_id": mint_id("op_")},
    )
    return frame


async def test_allow_all_requires_owner_and_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.contracts.frames import Req
    from sevn.protocol.registry import dispatch
    from sevn.protocol.session import Session

    load_modules("sevn.sandbox.policy")
    member = Session.for_test(scope="member")
    refused = await dispatch(
        member,
        Req(
            t="req",
            id="member",
            m="host.set_sandbox_mode",
            p={"mode": "allow_all", "confirm": "I understand", "op_id": mint_id("op_")},
        ),
    )
    assert refused.e is not None
    assert refused.e.code == "forbidden"
    assert refused.e.message == "forbidden"
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame = await _mode(client, "allow_all", "nope")
        body = error_body(frame)
        assert body["code"] == "confirm_required"
        assert "I understand" in str(body["message"])


async def test_allow_all_runs_without_pending_and_emits_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.tools.shell import execute

    load_modules("sevn.sandbox.policy", "sevn.api.bots")
    recorded: list[tuple[object, ...]] = []
    _record_exec(monkeypatch, recorded)
    enabled = False
    async with connected(tmp_path, monkeypatch) as (_host, client):
        try:
            turned = await _mode(client, "allow_all", "I understand")
            assert ok(turned)["mode"] == "allow_all"
            enabled = True
            audits = fetch_all(tmp_path, "SELECT payload FROM events WHERE type = 'audit'")
            assert audits
            assert "allow_all" in str(audits[0]["payload"])
            bot = await BotService().create("Nimbus", access="workspace", approval_policy="ask")
            agent = await AgentService().spawn(bot.id)
            result = await execute(bot.id, agent.id, "rm -rf /")
            assert result.executed is True
            assert result.pending_id is None
            assert _saw_rm(recorded)
            assert fetch_all(tmp_path, "SELECT id FROM pending_requests") == []
        finally:
            if enabled:
                await _mode(client, "enforced", "I understand")


async def test_allow_all_off_restores_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService
    from sevn.tools.shell import execute

    load_modules("sevn.sandbox.policy", "sevn.api.bots")
    recorded: list[tuple[object, ...]] = []
    _record_exec(monkeypatch, recorded)
    enabled = False
    async with connected(tmp_path, monkeypatch) as (_host, client):
        try:
            bot = await BotService().create("Nimbus", access="full", approval_policy="ask")
            agent = await AgentService().spawn(bot.id)
            turned = await _mode(client, "allow_all", "I understand")
            assert ok(turned)["mode"] == "allow_all"
            enabled = True
            skipped = await execute(bot.id, agent.id, "rm -rf /")
            assert skipped.pending_id is None
            assert skipped.executed is True
            restored = await _mode(client, "enforced", "I understand")
            assert ok(restored)["mode"] == "enforced"
            enabled = False
            stored = fetch_all(tmp_path, "SELECT access FROM bots WHERE id = ?", (bot.id,))
            assert stored[0]["access"] == "full"
            recorded.clear()
            asked = await execute(bot.id, agent.id, "rm -rf /")
            assert asked.executed is False
            assert asked.pending_id
            assert not _saw_rm(recorded)
        finally:
            if enabled:
                await _mode(client, "enforced", "I understand")


async def test_system_info_reports_allow_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.sandbox.policy", "sevn.system")
    enabled = False
    async with connected(tmp_path, monkeypatch) as (_host, client):
        try:
            before, _earlier = await request(client, "system.info", {})
            caps = ok(before)["caps"]
            assert isinstance(caps, dict)
            assert caps["allow_all"] is False
            turned = await _mode(client, "allow_all", "I understand")
            assert ok(turned)["mode"] == "allow_all"
            enabled = True
            during, _mid = await request(client, "system.info", {})
            assert ok(during)["caps"]["allow_all"] is True
            restored = await _mode(client, "enforced", "I understand")
            assert ok(restored)["mode"] == "enforced"
            enabled = False
            after, _late = await request(client, "system.info", {})
            assert ok(after)["caps"]["allow_all"] is False
        finally:
            if enabled:
                await _mode(client, "enforced", "I understand")
