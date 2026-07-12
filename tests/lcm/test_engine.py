"""LCM engine integration tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sevn.config.workspace_config import parse_workspace_config
from sevn.lcm.engine import InboundLcmMessage, LcmEngine, SessionView
from sevn.storage.migrate import apply_migrations


@pytest.mark.asyncio
async def test_workspace_config_lcm_section_roundtrip() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "lcm": {"fresh_tail_count": 40, "leaf_min_fanout": 3},
            "memory": {"pre_compaction_flush": {"enabled": False, "model": None}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert cfg.lcm is not None
    assert cfg.lcm.fresh_tail_count == 40
    assert cfg.lcm.leaf_min_fanout == 3
    assert cfg.memory is not None
    assert cfg.memory.pre_compaction_flush is not None
    assert cfg.memory.pre_compaction_flush.enabled is False


@pytest.mark.asyncio
async def test_ingest_blocked_without_stub_rejected(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    eng = LcmEngine(conn, workspace_root=tmp_path)
    sid = SessionView(session_key="k:a", conversation_id=0, channel="web")
    msg = InboundLcmMessage(
        role="user",
        content="secret",
        kind="blocked",
        visible_to_llm=False,
        status="sent",
    )
    with pytest.raises(ValueError, match=r"\.llmignore"):
        await eng.ingest(sid, msg)


@pytest.mark.asyncio
async def test_search_session_summaries_keyword(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    now = "2026-05-12T00:00:00"
    conn.execute(
        """
        INSERT INTO lcm_conversations (
            session_key, channel, group_name, topic, created_at, updated_at
        ) VALUES ('k:b', 'web', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    row = conn.execute(
        "SELECT id FROM lcm_conversations WHERE session_key = 'k:b'",
    ).fetchone()
    assert row is not None
    cid = int(row[0])
    conn.execute(
        """
        INSERT INTO lcm_summaries (
            summary_id, conversation_id, content, depth, token_count,
            summary_kind, created_at
        ) VALUES ('sess1', ?, 'Discussed caching strategy with operator', 0, 40,
                  'session_end', ?)
        """,
        (cid, now),
    )
    conn.commit()
    eng = LcmEngine(
        conn,
        workspace_root=tmp_path,
        workspace_cfg=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
    )
    sv = SessionView(session_key="k:b", conversation_id=cid, channel="web")
    hits = await eng.search_session_summaries(
        query="caching",
        date_from=None,
        date_to=None,
        limit=5,
        scope="conversation",
        scope_session=sv,
    )
    assert len(hits) == 1
    assert "caching" in hits[0].excerpt.lower()


@pytest.mark.asyncio
async def test_flush_apply_memory_writes(tmp_path: Path) -> None:
    from sevn.lcm.flush import MemoryWrite, MemoryWrites

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    eng = LcmEngine(conn, workspace_root=tmp_path)
    batch = MemoryWrites(
        writes=[MemoryWrite(path="USER.md", operation="replace", content="# u")],
    )
    out = await eng.apply_memory_writes_to_workspace(batch, utc_flush_day=(2026, 5, 12))
    assert out == "applied"
    assert (tmp_path / "USER.md").read_text(encoding="utf-8") == "# u"


@pytest.mark.asyncio
async def test_after_turn_requires_transport(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    eng = LcmEngine(conn, workspace_root=tmp_path)
    sv = SessionView(session_key="k:c", conversation_id=1, channel="web")
    with pytest.raises(NotImplementedError, match="transport"):
        await eng.after_turn(session=sv, summary_model_id="m")


def test_engine_import_surface() -> None:
    from sevn import lcm

    assert lcm.LcmEngine is LcmEngine
    assert lcm.MemoryWrites.__name__ == "MemoryWrites"
