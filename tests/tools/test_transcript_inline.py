"""Inline bounded ``history`` / ``read_transcript`` rows (Wave W2).

Ensures session recall tools return compact rows under the spill threshold so the
executor never needs to ``read`` spilled session history payloads.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sevn.config.defaults import TOOL_LARGE_RESULT_THRESHOLD_BYTES
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.transcript import _PREVIEW_CONTENT_CHARS


@pytest.fixture
def history_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Workspace with a session containing many long messages."""
    root = tmp_path / "ws"
    root.mkdir()
    dot_sevn = root / ".sevn"
    dot_sevn.mkdir()
    session_id = "c" * 32
    conn = sqlite3.connect(str(sevn_db_path(dot_sevn)))
    apply_migrations(conn)
    now = "2026-05-30T12:00:00"
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, 'web:owner', 'web', 'owner', ?, ?)
        """,
        (session_id, now, now),
    )
    long_body = "recall-marker-" + ("x" * 2500)
    for index in range(30):
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status, created_at
            ) VALUES (?, ?, 'message', ?, 1, 'sent', ?)
            """,
            (session_id, "user" if index % 2 == 0 else "assistant", f"{long_body}-{index}", now),
        )
    conn.commit()
    conn.close()
    return root, session_id


@pytest.fixture
def ctx(history_workspace: tuple[Path, str]) -> ToolContext:
    workspace, session_id = history_workspace
    return ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="history-inline-wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_history_large_session_returns_bounded_inline_rows(
    ctx: ToolContext,
    history_workspace: tuple[Path, str],
) -> None:
    """``history`` with ``limit=10`` stays inline under the spill threshold."""
    _workspace, session_id = history_workspace
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="history", arguments={"session_id": session_id, "limit": 10}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert "spill_path" not in data
    messages = data["messages"]
    assert isinstance(messages, list)
    assert len(messages) <= 10
    assert len(raw.encode("utf-8")) < TOOL_LARGE_RESULT_THRESHOLD_BYTES
    for row in messages:
        assert {"id", "role", "content", "ts"} <= set(row.keys())
        assert row.get("truncated") is True
        assert len(str(row["content"])) <= _PREVIEW_CONTENT_CHARS


@pytest.mark.asyncio
async def test_history_full_returns_untruncated_content_up_to_limit(
    ctx: ToolContext,
    history_workspace: tuple[Path, str],
) -> None:
    """``full=True`` disables per-row truncation while honouring ``limit``."""
    _workspace, session_id = history_workspace
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="history",
            arguments={"session_id": session_id, "limit": 3, "full": True},
        ),
    )
    data = json.loads(raw)["data"]
    messages = data["messages"]
    assert len(messages) == 3
    for row in messages:
        assert "truncated" not in row
        assert len(str(row["content"])) > _PREVIEW_CONTENT_CHARS


def test_history_tool_registered() -> None:
    """``history`` is available on the default session registry."""
    exe, _ = build_session_registry(registry_version=1)
    names = {definition.name for definition in exe.definitions()}
    assert "history" in names


@pytest.fixture
def dated_workspace(tmp_path: Path) -> tuple[Path, str]:
    """Workspace with messages spanning two UTC days for date-filter tests."""
    root = tmp_path / "ws"
    root.mkdir()
    dot_sevn = root / ".sevn"
    dot_sevn.mkdir()
    session_id = "e" * 32
    conn = sqlite3.connect(str(sevn_db_path(dot_sevn)))
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions (session_id, scope_key, channel, user_id, created_at, updated_at)
        VALUES (?, 'web:owner', 'web', 'owner', '2026-07-02 12:00:00', '2026-07-02 12:00:00')
        """,
        (session_id,),
    )
    for content, created in (
        ("yesterday-alpha", "2026-07-02T12:00:00+00:00"),
        ("today-beta", "2026-07-03T09:00:00+00:00"),
    ):
        conn.execute(
            """
            INSERT INTO gateway_messages (session_id, role, kind, content, visible_to_llm, status, created_at)
            VALUES (?, 'user', 'message', ?, 1, 'sent', ?)
            """,
            (session_id, content, created),
        )
    conn.commit()
    conn.close()
    return root, session_id


@pytest.mark.asyncio
async def test_history_since_until_filters_single_session(
    dated_workspace: tuple[Path, str],
) -> None:
    """``since``/``until`` narrow a session's messages to the given UTC day."""
    workspace, session_id = dated_workspace
    ctx = ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="history",
            arguments={
                "session_id": session_id,
                "since": "2026-07-02",
                "until": "2026-07-02",
            },
        ),
    )
    data = json.loads(raw)["data"]
    assert [m["content"] for m in data["messages"]] == ["yesterday-alpha"]


@pytest.mark.asyncio
async def test_history_date_only_lists_sessions(
    dated_workspace: tuple[Path, str],
) -> None:
    """A date range with no query returns the sessions active in that window."""
    workspace, session_id = dated_workspace
    ctx = ToolContext(
        session_id="f" * 32,  # different caller session; owner-visible
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="history", arguments={"since": "2026-07-02", "until": "2026-07-02"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is True
    data = envelope["data"]
    assert "sessions" in data
    assert any(s["session_id"] == session_id for s in data["sessions"])


@pytest.mark.asyncio
async def test_history_bad_when_is_validation_error(
    dated_workspace: tuple[Path, str],
) -> None:
    """An unknown relative token surfaces as a clean validation error."""
    workspace, session_id = dated_workspace
    ctx = ToolContext(
        session_id=session_id,
        workspace_path=workspace,
        workspace_id="wid",
        registry_version=1,
        permissions=AllowAllPermissionPolicy(),
    )
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="history", arguments={"when": "someday"}),
    )
    envelope = json.loads(raw)
    assert envelope["ok"] is False
    assert "unknown relative range" in envelope["error"]
