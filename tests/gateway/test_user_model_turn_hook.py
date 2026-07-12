"""Tests for user-model post-turn extraction hook (Batch D lane #6)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.sections.memory import MemoryWorkspaceSectionConfig, UserModelWorkspaceConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.post_turn_hooks import PostTurnContext
from sevn.gateway.turn_metadata import record_turn_start
from sevn.gateway.user_model_turn import (
    lookup_user_text_for_turn,
    maybe_schedule_user_model_extraction_after_turn,
)
from sevn.storage.migrate import apply_migrations


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("s1", "telegram:1", "telegram", "1", "now", "now"),
    )
    conn.commit()
    return conn


class _FakeTransport:
    name = "chat_completions"

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "facts": [
                                    {
                                        "topic": "language",
                                        "value": "Prefers Python",
                                        "confidence": "high",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }

    async def stream(self, request: dict[str, object]):
        if False:
            yield {}

    def auth_header(self, model_id: str) -> dict[str, str]:
        return {}

    def tokens_used(self, response: dict[str, object]) -> tuple[int, int]:
        return (0, 0)

    def cache_breakpoints(
        self, prompt_segments: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        return list(prompt_segments)


def _workspace(*, enabled: bool = True) -> WorkspaceConfig:
    return WorkspaceConfig.minimal(
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": "openai/gpt-4o-mini"},
        },
        memory=MemoryWorkspaceSectionConfig(
            user_model=UserModelWorkspaceConfig(enabled=enabled, trigger_tiers=["B", "C", "D"]),
        ),
    )


def _ctx(conn: sqlite3.Connection, workspace: WorkspaceConfig, root: Path) -> PostTurnContext:
    router = MagicMock()
    router._workspace = workspace
    router._content_root = root
    router._owner_ids = frozenset({"1"})
    return PostTurnContext(
        router=router,
        conn=conn,
        trace=NullTraceSink(),
        session_id="s1",
        correlation_id="t1",
        terminal_status="ok",
        turn_wall_ns=1,
    )


def test_lookup_user_text_for_turn() -> None:
    conn = _memory_conn()
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        ("s1", "t1", "hello world", "now"),
    )
    conn.commit()
    assert lookup_user_text_for_turn(conn, session_id="s1", turn_id="t1") == "hello world"


@pytest.mark.asyncio
async def test_extraction_populates_user_model_json(tmp_path: Path) -> None:
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t1",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=0.9,
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        ("s1", "t1", "I prefer dark mode", "now"),
    )
    conn.commit()
    ws = _workspace(enabled=True)
    ctx = _ctx(conn, ws, tmp_path)
    with patch(
        "sevn.gateway.user_model_turn.resolve_model",
        return_value=("openai/gpt-4o-mini", _FakeTransport()),
    ):
        await maybe_schedule_user_model_extraction_after_turn(ctx)
        await asyncio.sleep(0.05)
    profile_path = tmp_path / ".sevn" / "user_model.json"
    assert profile_path.is_file()
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    assert len(raw.get("facts", [])) >= 1


@pytest.mark.asyncio
async def test_disabled_skips_file(tmp_path: Path) -> None:
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t1",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=0.9,
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        ("s1", "t1", "hello", "now"),
    )
    conn.commit()
    ctx = _ctx(conn, _workspace(enabled=False), tmp_path)
    await maybe_schedule_user_model_extraction_after_turn(ctx)
    await asyncio.sleep(0.02)
    assert not (tmp_path / ".sevn").exists()


@pytest.mark.asyncio
async def test_tier_a_skips_extraction(tmp_path: Path) -> None:
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t1",
        session_id="s1",
        intent="GREETING",
        tier="A",
        confidence=1.0,
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        ("s1", "t1", "hi", "now"),
    )
    conn.commit()
    ctx = _ctx(conn, _workspace(enabled=True), tmp_path)
    with patch(
        "sevn.gateway.user_model_turn.resolve_model",
        return_value=("openai/gpt-4o-mini", _FakeTransport()),
    ):
        await maybe_schedule_user_model_extraction_after_turn(ctx)
        await asyncio.sleep(0.02)
    assert not (tmp_path / ".sevn").exists()


@pytest.mark.asyncio
async def test_non_ok_terminal_skips_extraction(tmp_path: Path) -> None:
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t1",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=0.9,
    )
    base = _ctx(conn, _workspace(enabled=True), tmp_path)
    ctx = PostTurnContext(
        router=base.router,
        conn=base.conn,
        trace=base.trace,
        session_id=base.session_id,
        correlation_id=base.correlation_id,
        terminal_status="error",
        turn_wall_ns=base.turn_wall_ns,
    )
    await maybe_schedule_user_model_extraction_after_turn(ctx)
    await asyncio.sleep(0.02)
    assert not (tmp_path / ".sevn").exists()


@pytest.mark.asyncio
async def test_extraction_emits_user_model_spans(tmp_path: Path) -> None:
    conn = _memory_conn()
    record_turn_start(
        conn,
        turn_id="t1",
        session_id="s1",
        intent="NEW_REQUEST",
        tier="B",
        confidence=0.9,
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        ("s1", "t1", "I prefer dark mode", "now"),
    )
    conn.commit()
    events: list[str] = []

    class _CollectSink(NullTraceSink):
        async def emit(self, event) -> None:  # type: ignore[no-untyped-def]
            events.append(str(event.kind))

    base = _ctx(conn, _workspace(enabled=True), tmp_path)
    ctx = PostTurnContext(
        router=base.router,
        conn=base.conn,
        trace=_CollectSink(),
        session_id=base.session_id,
        correlation_id=base.correlation_id,
        terminal_status=base.terminal_status,
        turn_wall_ns=base.turn_wall_ns,
    )
    with patch(
        "sevn.gateway.user_model_turn.resolve_model",
        return_value=("openai/gpt-4o-mini", _FakeTransport()),
    ):
        await maybe_schedule_user_model_extraction_after_turn(ctx)
        await asyncio.sleep(0.05)
    assert "user_model.extract" in events
    assert "user_model.update" in events
