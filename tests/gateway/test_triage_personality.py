"""Gateway LCM ingest + Triager personality (`plan/gateway-agent-glue-wave-plan.md` Wave 8)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sevn.agent.triager.context import RegistrySnapshot
from sevn.agent.triager.prompt import build_triager_prompt_segments
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.lcm_ingest import ingest_gateway_message_row
from sevn.gateway.triage_context import (
    load_workspace_personality,
    triage_context_from_session,
)
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def test_load_workspace_personality_reads_soul_user_memory(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "SOUL.md").write_text("Be concise.", encoding="utf-8")
    (root / "IDENTITY.md").write_text("Name: Sevn", encoding="utf-8")
    (root / "USER.md").write_text("Alex builds bots.", encoding="utf-8")
    (root / "MEMORY.md").write_text("Project: sevn.bot", encoding="utf-8")

    bundle, version = load_workspace_personality(root)

    assert bundle is not None
    assert "SOUL.md" in bundle
    assert "IDENTITY.md" in bundle
    assert "USER.md" in bundle
    assert "MEMORY.md" in bundle
    assert "Be concise." in bundle
    assert version > 0


def test_triage_context_includes_personality_and_lcm_stub(tmp_path: Path) -> None:
    conn = _memory_conn()
    root = tmp_path / "ws"
    root.mkdir()
    (root / "SOUL.md").write_text("voice", encoding="utf-8")
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "workspace_root": ".",
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)

    session_id = "sess-lcm-1"
    now = "2026-05-21T12:00:00"
    conn.execute(
        """
        INSERT INTO lcm_conversations (
            session_key, channel, group_name, topic, created_at, updated_at
        ) VALUES (?, 'telegram', NULL, NULL, ?, ?)
        """,
        (session_id, now, now),
    )
    cid = int(conn.execute("SELECT id FROM lcm_conversations").fetchone()[0])
    conn.execute(
        """
        INSERT INTO lcm_summaries (
            summary_id, conversation_id, content, depth, token_count,
            summary_kind, created_at
        ) VALUES ('sum-1', ?, 'Earlier we discussed deployment.', 0, 12, 'compaction', ?)
        """,
        (cid, now),
    )
    conn.commit()

    ctx = triage_context_from_session(conn, session_id, ws, "hello", layout=layout)

    assert ctx.personality_markdown is not None
    assert "SOUL.md" in ctx.personality_markdown
    assert ctx.personality_version > 0
    assert "deployment" in ctx.lcm_summary_stub

    _static, _registry, personality, suffix = build_triager_prompt_segments(
        registry_snapshot=RegistrySnapshot(registry_version=1),
        triage_context=ctx,
    )
    assert personality
    assert "[lcm_stub]" in suffix
    assert "deployment" in suffix


@pytest.mark.asyncio
async def test_ingest_gateway_message_row_persists_lcm_message(tmp_path: Path) -> None:
    conn = _memory_conn()
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    root = tmp_path / "ws"
    root.mkdir()
    session_id = "sess-ingest-1"

    mid = await ingest_gateway_message_row(
        conn=conn,
        workspace=ws,
        content_root=root,
        trace=None,
        session_id=session_id,
        channel="telegram",
        role="user",
        content="ping",
    )

    assert mid is not None
    row = conn.execute("SELECT role, content FROM lcm_messages WHERE id = ?", (mid,)).fetchone()
    assert row is not None
    assert row[0] == "user"
    assert row[1] == "ping"
    conv = conn.execute(
        "SELECT session_key FROM lcm_conversations WHERE session_key = ?",
        (session_id,),
    ).fetchone()
    assert conv is not None


@pytest.mark.asyncio
async def test_ingest_skips_when_lcm_disabled(tmp_path: Path) -> None:
    conn = _memory_conn()
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "lcm": {"enabled": False},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    root = tmp_path / "ws"
    root.mkdir()

    mid = await ingest_gateway_message_row(
        conn=conn,
        workspace=ws,
        content_root=root,
        trace=None,
        session_id="sess-off",
        channel="webchat",
        role="user",
        content="hi",
    )

    assert mid is None
    count = conn.execute("SELECT COUNT(*) FROM lcm_messages").fetchone()[0]
    assert count == 0
