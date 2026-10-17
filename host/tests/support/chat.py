"""In-process protocol session helpers for the chat RED suite."""

from __future__ import annotations

import asyncio
import importlib
import json
import secrets
import sqlite3
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from support.memory import handshake, memory_host, recv_frame, send_req

_CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def arm_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """Point the host at ``home`` and keep workspaces out of the user profile."""
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_WORKSPACES", str(home / "workspaces"))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_DEV", raising=False)
    monkeypatch.delenv("SEVN_OLLAMA_URL", raising=False)
    monkeypatch.delenv("SEVN_TEST_MODEL", raising=False)
    config = home / "config.toml"
    if not config.exists():
        config.write_text('[secrets]\nbackend = "age-file"\n', encoding="utf-8")


def load_modules(*names: str) -> None:
    for name in names:
        importlib.import_module(name)


def mint_id(prefix: str) -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    body = "".join(secrets.choice(alphabet) for _ in range(26))
    return prefix + body


def assert_prefixed_id(value: object, prefix: str) -> str:
    assert isinstance(value, str), value
    assert value.startswith(prefix), value
    body = value[len(prefix) :]
    assert len(body) == 26, value
    assert set(body.upper()) <= _CROCKFORD, value
    return value


def ok(frame: Mapping[str, Any]) -> dict[str, Any]:
    assert frame.get("t") == "res", frame
    assert "e" not in frame, frame
    body = frame.get("r")
    assert isinstance(body, dict), frame
    return body


def error_body(frame: Mapping[str, Any]) -> dict[str, Any]:
    assert frame.get("t") == "res", frame
    error = frame.get("e")
    assert isinstance(error, dict), frame
    return error


@asynccontextmanager
async def connected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[Any, Any]]:
    """Open one authenticated session against a disposable home."""
    arm_home(monkeypatch, tmp_path)
    async with memory_host(tmp_path, monkeypatch) as host:
        client, _session = host.open()
        await handshake(client, host.token)
        yield host, client


async def request(
    client: Any,
    method: str,
    params: dict[str, Any],
    *,
    timeout_s: float = 2,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Send one call and return ``(res, earlier_frames)``."""
    req_id = secrets.token_hex(8)
    await send_req(client, req_id, method, params)
    earlier: list[dict[str, Any]] = []
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError(f"no res for {method}")
        frame = await recv_frame(client, remaining)
        if frame.get("t") == "res" and frame.get("id") == req_id:
            return frame, earlier
        earlier.append(frame)


async def drain(client: Any, *, first: float = 0.3, rest: float = 0.05) -> list[dict[str, Any]]:
    """Read queued frames until the client goes quiet."""
    frames: list[dict[str, Any]] = []
    timeout = first
    while True:
        try:
            frames.append(await recv_frame(client, timeout))
        except TimeoutError:
            return frames
        timeout = rest


def db_path(home: Path) -> Path:
    return home / "sevn.db"


def fetch_all(home: Path, sql: str, args: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    database = db_path(home)
    assert database.is_file(), database
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        return list(connection.execute(sql, args))


def dumps(value: object) -> str:
    return json.dumps(value, default=str)


async def insert_job(
    home: Path,
    *,
    bot_id: str,
    agent_id: str,
    text: str,
    status: str = "queued",
    job_id: str | None = None,
) -> str:
    """Insert one ``jobs`` row. The model is created in W2."""
    from datetime import UTC, datetime

    from sevn.store.db import async_engine
    from sevn.store.models import Job
    from sqlalchemy.ext.asyncio import async_sessionmaker

    chosen = mint_id("job_") if job_id is None else job_id
    now = datetime.now(UTC)
    engine = async_engine(f"sqlite+aiosqlite:///{db_path(home)}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            session.add(
                Job(
                    id=chosen,
                    to_bot_id=bot_id,
                    agent_id=agent_id,
                    route_decision_id=None,
                    origin="user",
                    text=text,
                    attachments=[],
                    reply_to=None,
                    expects_reply=False,
                    hop=0,
                    status=status,
                    created_at=now,
                    started_at=now if status == "started" else None,
                    finished_at=None,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return chosen


async def insert_turn(
    home: Path,
    *,
    agent_id: str,
    thread_id: str,
    job_id: str,
    status: str,
    model_messages: object = None,
) -> str:
    """Insert one ``turns`` row. ``model_messages`` left null means no committed result."""
    from datetime import UTC, datetime

    from sevn.store.db import async_engine
    from sevn.store.models import Turn
    from sqlalchemy.ext.asyncio import async_sessionmaker

    turn_id = mint_id("turn_")
    now = datetime.now(UTC)
    engine = async_engine(f"sqlite+aiosqlite:///{db_path(home)}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            session.add(
                Turn(
                    id=turn_id,
                    agent_id=agent_id,
                    thread_id=thread_id,
                    job_ids=[job_id],
                    status=status,
                    model="anthropic",
                    usage={},
                    model_messages=model_messages,
                    started_at=now,
                    finished_at=None,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return turn_id


async def poll_rows(
    home: Path,
    sql: str,
    args: tuple[object, ...],
    predicate: Any,
    *,
    timeout_s: float = 2,
) -> list[sqlite3.Row]:
    """Re-read ``sql`` until ``predicate(rows)`` is true."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: list[sqlite3.Row] = []
    while asyncio.get_running_loop().time() < deadline:
        if db_path(home).is_file():
            last = fetch_all(home, sql, args)
            if predicate(last):
                return last
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {sql}: {list(map(dict, last))}")
