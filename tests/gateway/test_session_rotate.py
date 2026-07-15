"""``/new`` session rotation (`plan/operator-experience-wave-plan.md` Wave 2)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.onboarding.first_session import intro_state_for_scope, mark_intro_state
from sevn.gateway.session_manager import SessionManager, format_lcm_status_lines, load_session_row
from sevn.skills.browser_session import CloseBrowserResult
from sevn.storage.migrate import apply_migrations


async def _seed(scope: str = "telegram:1:general") -> tuple[SessionManager, str]:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    sm = SessionManager(conn)
    sid = await sm.ensure_session(scope_key=scope, channel="telegram", user_id="1")
    return sm, sid


def test_rotate_session_mints_new_id_and_archives_scope() -> None:
    sm, old_id = asyncio.run(_seed())
    new_id = asyncio.run(sm.rotate_session(old_id))
    assert new_id != old_id
    old_row = load_session_row(sm.connection, old_id)
    assert old_row is not None
    assert "::archived::" in old_row.scope_key
    new_row = load_session_row(sm.connection, new_id)
    assert new_row is not None
    assert new_row.scope_key == "telegram:1:general"
    live = sm.connection.execute(
        "SELECT session_id FROM gateway_sessions WHERE scope_key = ?",
        ("telegram:1:general",),
    ).fetchone()
    assert live is not None
    assert str(live[0]) == new_id


def test_ensure_session_after_rotate_returns_new_id() -> None:
    sm, old_id = asyncio.run(_seed())
    new_id = asyncio.run(sm.rotate_session(old_id))
    again = asyncio.run(
        sm.ensure_session(scope_key="telegram:1:general", channel="telegram", user_id="1"),
    )
    assert again == new_id
    assert again != old_id


def test_session_mirror_separate_jsonl_per_session(tmp_path: Path) -> None:
    from sevn.gateway.session.session_mirror import mirror_gateway_message

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    content_root = tmp_path / "ws"
    content_root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        gateway={
            "session_mirror": {"enabled": True},
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    )
    sm = SessionManager(conn, content_root=content_root, workspace=ws)
    scope = "telegram:99:general"

    async def _run() -> tuple[str, str]:
        s1 = await sm.ensure_session(scope_key=scope, channel="telegram", user_id="99")
        mirror_gateway_message(
            content_root=content_root,
            workspace=ws,
            session_id=s1,
            scope_key=scope,
            channel="telegram",
            user_id="99",
            message_id=1,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            created_at="2026-05-22T10:00:00",
            extras_json=None,
        )
        s2 = await sm.rotate_session(s1)
        mirror_gateway_message(
            content_root=content_root,
            workspace=ws,
            session_id=s2,
            scope_key=scope,
            channel="telegram",
            user_id="99",
            message_id=2,
            role="user",
            kind="message",
            content="after new",
            visible_to_llm=1,
            status="sent",
            created_at="2026-05-22T10:01:00",
            extras_json=None,
        )
        return s1, s2

    s1, s2 = asyncio.run(_run())
    # D7: positive chat_id (private-style scope) stays ID-only even after W3.
    base = content_root / "sessions" / "telegram" / "chats" / "99" / "general"
    p1 = base / f"{s1}.jsonl"
    p2 = base / f"{s2}.jsonl"
    assert p1.is_file()
    assert p2.is_file()
    assert p1 != p2


def test_session_mirror_separate_jsonl_per_session_group_enriched_path(tmp_path: Path) -> None:
    """W1.6: supergroup ``/new`` rotation writes under name-enriched chat folder."""
    import inspect

    from sevn.gateway.session.session_mirror import mirror_gateway_message

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    content_root = tmp_path / "ws"
    content_root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        gateway={
            "session_mirror": {"enabled": True},
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    )
    sm = SessionManager(conn, content_root=content_root, workspace=ws)
    scope = "telegram:-1001234567890:general"
    conn.execute(
        "INSERT INTO telegram_chat_names (chat_id, name, updated_at) VALUES (?, ?, datetime('now'))",
        (-1001234567890, "Ops Team"),
    )
    conn.commit()
    mirror_kwargs: dict[str, object] = {}
    sig = inspect.signature(mirror_gateway_message)
    for param_name in ("name_resolver", "resolver", "conn"):
        if param_name in sig.parameters:
            mirror_kwargs[param_name] = conn
            break
    else:
        pytest.fail("mirror_gateway_message has no conn/resolver parameter (green after W3)")

    async def _run() -> tuple[str, str]:
        s1 = await sm.ensure_session(scope_key=scope, channel="telegram", user_id="42")
        mirror_gateway_message(
            content_root=content_root,
            workspace=ws,
            session_id=s1,
            scope_key=scope,
            channel="telegram",
            user_id="42",
            message_id=1,
            role="user",
            kind="message",
            content="hello",
            visible_to_llm=1,
            status="sent",
            created_at="2026-05-22T10:00:00",
            extras_json=None,
            **mirror_kwargs,
        )
        s2 = await sm.rotate_session(s1)
        mirror_gateway_message(
            content_root=content_root,
            workspace=ws,
            session_id=s2,
            scope_key=scope,
            channel="telegram",
            user_id="42",
            message_id=2,
            role="user",
            kind="message",
            content="after new",
            visible_to_llm=1,
            status="sent",
            created_at="2026-05-22T10:01:00",
            extras_json=None,
            **mirror_kwargs,
        )
        return s1, s2

    s1, s2 = asyncio.run(_run())
    base = content_root / "sessions" / "telegram" / "chats" / "Ops_Team--1001234567890" / "general"
    p1 = base / f"{s1}.jsonl"
    p2 = base / f"{s2}.jsonl"
    assert p1.is_file()
    assert p2.is_file()
    assert p1 != p2


def test_format_lcm_status_lines_reports_ingest_and_compaction() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    conn.execute(
        "INSERT INTO lcm_conversations (session_key, channel, created_at, updated_at) "
        "VALUES (?, ?, ?, ?)",
        ("sess1", "telegram", "2026-05-22T00:00:00", "2026-05-22T00:00:00"),
    )
    conv_id = int(conn.execute("SELECT id FROM lcm_conversations").fetchone()[0])
    conn.execute(
        """
        INSERT INTO lcm_messages (
            conversation_id, seq, role, content, kind, visible_to_llm, status, created_at
        ) VALUES (?, 1, 'user', 'hi', 'message', 1, 'sent', ?)
        """,
        (conv_id, "2026-05-22T00:00:01"),
    )
    conn.execute(
        """
        INSERT INTO lcm_summaries (
            summary_id, conversation_id, content, depth, summary_kind, created_at
        ) VALUES (?, ?, ?, 0, 'compaction', ?)
        """,
        ("sum1", conv_id, "summary", "2026-05-22T00:05:00"),
    )
    conn.commit()
    ws = WorkspaceConfig(
        schema_version=1,
        lcm={"enabled": True},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    lines = format_lcm_status_lines(conn, "sess1", workspace=ws)
    assert lines[0] == "LCM: on"
    assert "LCM messages ingested: 1" in lines
    assert "2026-05-22T00:05:00" in "\n".join(lines)


def test_rotate_clears_intro_when_bootstrap_incomplete(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    content_root = tmp_path / "ws"
    content_root.mkdir()
    (content_root / "USER.md").write_text(
        "<!-- sevn-bootstrap:user-incomplete -->\nName: _(your name)_\n",
        encoding="utf-8",
    )
    sm = SessionManager(conn, content_root=content_root)
    sid = asyncio.run(
        sm.ensure_session(scope_key="telegram:u1", channel="telegram", user_id="u1"),
    )
    mark_intro_state(conn, sid, "done")
    assert intro_state_for_scope(conn, "telegram", "u1") == "done"
    asyncio.run(sm.rotate_session(sid, content_root=content_root))
    assert intro_state_for_scope(conn, "telegram", "u1") == "pending"


def test_rotate_session_closes_browser(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    content_root = tmp_path / "ws"
    content_root.mkdir()
    sm = SessionManager(conn, content_root=content_root)
    old_id = asyncio.run(
        sm.ensure_session(scope_key="telegram:rot", channel="telegram", user_id="rot"),
    )
    with patch(
        "sevn.skills.browser_session.close_browser_session",
        return_value=CloseBrowserResult(ok=True, code="CLOSED", message="terminated"),
    ) as mock_close:
        asyncio.run(sm.rotate_session(old_id, content_root=content_root))
        mock_close.assert_called_once_with(content_root, old_id)


def test_rotate_preserves_intro_when_bootstrap_complete(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    content_root = tmp_path / "ws"
    content_root.mkdir()
    (content_root / "USER.md").write_text("Name: Alex\n", encoding="utf-8")
    sm = SessionManager(conn, content_root=content_root)
    sid = asyncio.run(
        sm.ensure_session(scope_key="telegram:u2", channel="telegram", user_id="u2"),
    )
    mark_intro_state(conn, sid, "done")
    asyncio.run(sm.rotate_session(sid, content_root=content_root))
    assert intro_state_for_scope(conn, "telegram", "u2") == "done"
