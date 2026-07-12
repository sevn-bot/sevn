"""Integration: Dreaming reads SQLite without LCM deletes (`specs/31-memory-dreaming.md` §9)."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.memory.dreaming.engine import DreamingEngine
from sevn.storage.migrate import apply_migrations


@pytest.mark.asyncio
async def test_engine_auto_promote_no_lcm_delete(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    dot = root / ".sevn"
    dot.mkdir()
    conn = sqlite3.connect(dot / "db.sqlite")
    apply_migrations(conn)
    conn.execute("DELETE FROM lcm_summaries")
    conn.execute("DELETE FROM lcm_messages")
    conn.execute("DELETE FROM lcm_conversations")
    conn.execute(
        "INSERT INTO lcm_conversations (session_key, channel, created_at, updated_at) "
        "VALUES ('dm:x', 'private', 't0', 't0')",
    )
    conv_id = int(conn.execute("SELECT id FROM lcm_conversations").fetchone()[0])
    conn.execute(
        "INSERT INTO lcm_summaries (summary_id, conversation_id, content, depth, created_at) "
        "VALUES ('s1', ?, 'summary fact about cheese', 0, '2099-01-01')",
        (conv_id,),
    )
    conn.execute(
        "INSERT INTO memory (key, session_id, content, tags, created_at, metadata) "
        "VALUES ('k1', 'dm:owner', 'likes blue', '', '2099-01-02', NULL)",
    )
    conn.commit()

    raw = WorkspaceConfig(
        schema_version=1,
        memory={"dreaming": {"enabled": True, "threshold": 0.01, "max_promotions_per_run": 5}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    trace = NullTraceSink()
    lock = asyncio.Lock()
    eng = DreamingEngine(conn, trace, lock, transport=None)
    res = await eng.run_scheduled(workspace_root=root, ws=raw)
    assert res is not None
    assert len(res.promoted) >= 1
    assert (root / "MEMORY.md").is_file()
    n = int(conn.execute("SELECT COUNT(*) FROM lcm_messages").fetchone()[0])
    assert n == 0
    conn.close()
