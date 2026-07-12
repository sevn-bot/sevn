"""Tests for LCM assembler budgeting (`specs/15-memory-lcm.md` §4)."""

from __future__ import annotations

import sqlite3

import pytest

from sevn.lcm.assembler import LcmAssembler
from sevn.storage.migrate import apply_migrations


def _seed_conv(conn: sqlite3.Connection) -> int:
    now = "2026-05-12T00:00:00"
    cur = conn.execute(
        """
        INSERT INTO lcm_conversations (
            session_key, channel, group_name, topic, created_at, updated_at
        ) VALUES ('t:s', 'test', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    cid = int(cur.lastrowid)
    for seq, role, tok in (
        (1, "user", 100),
        (2, "assistant", 100),
        (3, "user", 100),
    ):
        conn.execute(
            """
            INSERT INTO lcm_messages (
                conversation_id, seq, role, content, token_count, kind,
                visible_to_llm, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'message', 1, 'sent', ?)
            """,
            (cid, seq, role, "x" * 40, tok, now),
        )
    conn.commit()
    return cid


@pytest.mark.asyncio
async def test_assembler_trims_oldest_tail_when_budget_tight() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _seed_conv(conn)
    asm = LcmAssembler(conn)
    ctx = await asm.assemble(
        conversation_id=cid,
        token_budget=220,
        fresh_tail_count=3,
        system_prompt=None,
    )
    roles = [m["role"] for m in ctx.messages]
    assert roles[-2:] == ["assistant", "user"]
    assert ctx.fresh_tail_n == 2


@pytest.mark.asyncio
async def test_assembler_inserts_summaries_before_tail() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _seed_conv(conn)
    conn.execute(
        """
        INSERT INTO lcm_summaries (
            summary_id, conversation_id, content, depth, token_count,
            summary_kind, created_at
        ) VALUES ('s1', ?, 'older topic', 0, 10, 'compaction', '2026-05-11T00:00:00')
        """,
        (cid,),
    )
    conn.commit()
    asm = LcmAssembler(conn)
    ctx = await asm.assemble(
        conversation_id=cid,
        token_budget=500,
        fresh_tail_count=3,
        system_prompt=None,
    )
    assert any("<summary>" in m["content"] for m in ctx.messages)
    assert ctx.summary_nodes >= 1


@pytest.mark.asyncio
async def test_blocked_rows_never_in_tail() -> None:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    now = "2026-05-12T00:00:00"
    cur = conn.execute(
        """
        INSERT INTO lcm_conversations (
            session_key, channel, group_name, topic, created_at, updated_at
        ) VALUES ('t:s2', 'test', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    cid = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO lcm_messages (
            conversation_id, seq, role, content, token_count, kind,
            visible_to_llm, status, created_at
        ) VALUES (?, 1, 'user', 'visible', 5, 'message', 1, 'sent', ?)
        """,
        (cid, now),
    )
    conn.execute(
        """
        INSERT INTO lcm_messages (
            conversation_id, seq, role, content, token_count, kind,
            visible_to_llm, status, created_at
        ) VALUES (?, 2, 'user', '.llmignore/ref blocked payload', 5, 'blocked', 0, 'sent', ?)
        """,
        (cid, now),
    )
    conn.commit()
    asm = LcmAssembler(conn)
    ctx = await asm.assemble(
        conversation_id=cid,
        token_budget=400,
        fresh_tail_count=10,
        system_prompt=None,
    )
    joined = "\n".join(m["content"] for m in ctx.messages)
    assert "blocked payload" not in joined
