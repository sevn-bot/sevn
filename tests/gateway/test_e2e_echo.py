"""Wave TE-2 echo run-turn delay hook (`specs/17-gateway.md` §2.9)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.api.e2e_echo import (
    SEVN_E2E_ECHO_DELAY_ENV,
    _echo_delay_seconds,
    build_echo_run_turn,
)
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _router(tmp_path: Path, conn: sqlite3.Connection) -> ChannelRouter:
    root = tmp_path / "w"
    root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    return ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
    )


def test_echo_delay_seconds_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var → no artificial delay."""
    monkeypatch.delenv(SEVN_E2E_ECHO_DELAY_ENV, raising=False)
    assert _echo_delay_seconds() == 0.0


def test_echo_delay_seconds_parses_positive_int(monkeypatch: pytest.MonkeyPatch) -> None:
    """``SEVN_E2E_ECHO_DELAY_MS=250`` → 0.25 seconds."""
    monkeypatch.setenv(SEVN_E2E_ECHO_DELAY_ENV, "250")
    assert _echo_delay_seconds() == pytest.approx(0.25)


def test_echo_delay_seconds_rejects_non_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero or negative values fall back to no delay (no `asyncio.sleep`)."""
    monkeypatch.setenv(SEVN_E2E_ECHO_DELAY_ENV, "0")
    assert _echo_delay_seconds() == 0.0
    monkeypatch.setenv(SEVN_E2E_ECHO_DELAY_ENV, "-5")
    assert _echo_delay_seconds() == 0.0


def test_echo_delay_seconds_handles_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-numeric values fall back to no delay rather than raising."""
    monkeypatch.setenv(SEVN_E2E_ECHO_DELAY_ENV, "fast")
    assert _echo_delay_seconds() == 0.0


@pytest.fixture
def allow_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub LLM Guard scanner to allow any inbound text."""

    async def _stub(
        _self: LLMGuardScanner,
        *,
        text: str,
        channel: str,
        user_id: str,
        actor_is_owner: bool,
        source: str,
    ) -> ScanResult:
        _ = text, channel, user_id, actor_is_owner, source
        return ScanResult(
            verdict=ScanVerdict.allow,
            reasons=(),
            scores={},
            provider_used=None,
            details={},
        )

    monkeypatch.setattr(LLMGuardScanner, "scan_inbound", _stub)


@pytest.mark.asyncio
@pytest.mark.usefixtures("allow_scan")
async def test_echo_run_turn_awaits_sleep_when_env_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run-turn calls ``asyncio.sleep(ms/1000)`` before outbound when env is set."""
    monkeypatch.setenv(SEVN_E2E_ECHO_DELAY_ENV, "150")
    conn = _memory_conn()
    router = _router(tmp_path, conn)
    sent_chunks: list[tuple[str, dict[str, Any]]] = []

    class _CaptureAdapter:
        name = "webchat"

        def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
            _ = payload
            return None

        async def send(self, message: Any) -> list[str]:
            sent_chunks.append((message.text, dict(message.metadata)))
            return ["1"]

    router.register_adapter(_CaptureAdapter())  # type: ignore[arg-type]
    sleep_calls: list[float] = []
    original_sleep = asyncio.sleep

    async def _spy_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        await original_sleep(0)

    monkeypatch.setattr("sevn.gateway.api.e2e_echo.asyncio.sleep", _spy_sleep)
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="webchat:alice",
            channel="webchat",
            user_id="alice",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="ping",
            visible_to_llm=1,
            status="sent",
            turn_id="t-test",
        )
        echo = build_echo_run_turn(router, conn)
        await echo(session_id, "cid-1")
    finally:
        conn.close()
    assert any(d == pytest.approx(0.15) for d in sleep_calls)
    assert sent_chunks
    assert sent_chunks[-1][0] == "echo: ping"


@pytest.mark.asyncio
@pytest.mark.usefixtures("allow_scan")
async def test_echo_run_turn_skips_sleep_when_env_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production default — no env var → ``asyncio.sleep`` never invoked from echo."""
    monkeypatch.delenv(SEVN_E2E_ECHO_DELAY_ENV, raising=False)
    conn = _memory_conn()
    router = _router(tmp_path, conn)

    class _NoopAdapter:
        name = "webchat"

        def parse_webhook(self, payload: dict[str, Any]) -> IncomingMessage | None:
            _ = payload
            return None

        async def send(self, message: Any) -> list[str]:
            _ = message
            return ["1"]

    router.register_adapter(_NoopAdapter())  # type: ignore[arg-type]
    sleep_calls: list[float] = []

    async def _spy_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("sevn.gateway.api.e2e_echo.asyncio.sleep", _spy_sleep)
    try:
        session_id = await router.session_manager.ensure_session(
            scope_key="webchat:bob",
            channel="webchat",
            user_id="bob",
        )
        await router.session_manager.add_message(
            session_id,
            role="user",
            kind="message",
            content="hi",
            visible_to_llm=1,
            status="sent",
            turn_id="t-test",
        )
        echo = build_echo_run_turn(router, conn)
        await echo(session_id, "cid-1")
    finally:
        conn.close()
    assert sleep_calls == []
