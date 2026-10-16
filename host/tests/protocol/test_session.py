"""Handshake, dispatch errors, and session scope (D5-D7, D14). Green after W4."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from support.memory import (
    collect_until_close,
    handshake,
    hello_frame,
    memory_host,
    recv_frame,
    send_frame,
    send_req,
)

pytestmark = pytest.mark.xfail(strict=False, reason="green after W4")


async def test_hello_welcome_with_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from support.memory import count_events

    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        welcome = await handshake(client, host.token)
        assert welcome["t"] == "welcome"
        assert welcome["proto"] == 1
        assert welcome["host_seq"] == await count_events(host.outbox) == 0


async def test_bad_token_closes_4001(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await send_frame(client, hello_frame())
        await send_frame(client, {"t": "auth", "token": "not-the-token"})
        frames, exc = await collect_until_close(client)
        assert exc.code == 4001
        assert exc.reason == "unauthorized"
        assert all(frame.get("t") != "welcome" for frame in frames)


async def test_req_before_auth_is_protocol_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await send_frame(client, hello_frame())
        await send_req(client, "early", "system.info", {})
        frame = await recv_frame(client)
        assert frame["t"] == "res"
        assert frame["e"]["code"] == "protocol_error"


async def test_no_version_overlap_closes_4002(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await send_frame(client, hello_frame(proto=[2, 3]))
        frames, exc = await collect_until_close(client)
        assert exc.code == 4002
        assert exc.reason == "update sevn: host speaks 1..1"
        assert frames == []


async def test_unknown_method(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        await send_req(client, "missing", "no.such", {})
        frame = await recv_frame(client)
        assert frame["e"]["code"] == "method_not_found"


async def test_invalid_params_lists_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        await send_req(client, "bad-seq", "sync.since", {"seq": "x"})
        frame = await recv_frame(client)
        assert frame["e"]["code"] == "invalid_params"
        assert frame["e"]["data"]["errors"][0]["loc"] == ["seq"]


async def test_token_session_is_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async with memory_host(tmp_path, monkeypatch) as host:
        client, session = host.open()
        await handshake(client, host.token)
        assert session.scope == "owner"


async def test_owner_only_method_refuses_member() -> None:
    from pydantic import BaseModel
    from sevn.contracts.errors import ProtocolError
    from sevn.contracts.frames import parse
    from sevn.protocol.registry import dispatch, method
    from sevn.protocol.session import Session

    class Params(BaseModel):
        pass

    class Result(BaseModel):
        ok: bool

    called: list[bool] = []

    @method("test.owner_only", params=Params, result=Result, mutating=False, scope="owner")
    async def _owner_only(_ctx: object, _params: Params) -> Result:
        called.append(True)
        return Result(ok=True)

    session = Session.for_test(scope="member")
    req = parse('{"id":"1","m":"test.owner_only","p":{},"t":"req"}')
    try:
        outcome: Any = await dispatch(session, req)
    except ProtocolError as exc:
        assert exc.code == "forbidden"
    else:
        error = outcome.e if hasattr(outcome, "e") else outcome["e"]
        code = error.code if hasattr(error, "code") else error["code"]
        assert code == "forbidden"
    assert called == []
