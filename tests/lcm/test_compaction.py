"""Compaction scheduler tests with a stub ``Transport``.

Retry/idempotency guarantees exercised here match ``specs/15-memory-lcm.md`` §11
(Wave F): persistence runs only after a non-empty completion; failures before
that leave eligibility unchanged so a later retry can proceed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sevn.config.llm_params import LLM_PARAMS_FILENAME
from sevn.lcm.compaction import CompactionScheduler
from sevn.storage.migrate import apply_migrations


class _StubTransport:
    name = "chat_completions"
    last_request: dict[str, object] | None = None

    def __init__(self, reply: str = "summary text") -> None:
        self._reply = reply

    async def complete(self, request: dict[str, object]) -> dict[str, Any]:
        self.last_request = dict(request)
        return {
            "choices": [{"message": {"content": self._reply}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    def tokens_used(self, response: dict[str, object]) -> tuple[int, int]:
        return (10, 5)

    def auth_header(self, model_id: str) -> dict[str, str]:
        _ = model_id
        return {}

    def cache_breakpoints(
        self, prompt_segments: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        return list(prompt_segments)


class _FlakyTransport(_StubTransport):
    """Fails the first ``complete`` call; succeeds afterward."""

    def __init__(self, reply: str = "summary text") -> None:
        super().__init__(reply)
        self.calls = 0

    async def complete(self, request: dict[str, object]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            msg = "simulated transport failure before persist"
            raise RuntimeError(msg)
        return await super().complete(request)


def _conv_with_messages(conn: Any, n: int = 8) -> int:
    import sqlite3

    assert isinstance(conn, sqlite3.Connection)
    now = "2026-05-12T00:00:00"
    cur = conn.execute(
        """
        INSERT INTO lcm_conversations (
            session_key, channel, group_name, topic, created_at, updated_at
        ) VALUES ('c:t', 'test', NULL, NULL, ?, ?)
        """,
        (now, now),
    )
    cid = int(cur.lastrowid)
    for i in range(n):
        conn.execute(
            """
            INSERT INTO lcm_messages (
                conversation_id, seq, role, content, token_count, kind,
                visible_to_llm, status, created_at
            ) VALUES (?, ?, 'user', ?, 20, 'message', 1, 'sent', ?)
            """,
            (cid, i + 1, f"msg{i}", now),
        )
    conn.commit()
    return cid


@pytest.mark.asyncio
async def test_leaf_compaction_inserts_summary_edges() -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _conv_with_messages(conn, 8)
    sched = CompactionScheduler(conn)
    res = await sched.run_incremental(
        conversation_id=cid,
        fresh_tail_count=4,
        incremental_max_depth=0,
        transport=_StubTransport(),
        model_id="stub-model",
        leaf_min_fanout=8,
        leaf_chunk_tokens=99999,
        condensed_min_fanout=99,
        leaf_target_chars=200,
        condensed_target_chars=200,
        dedup_overlap_threshold=1.0,
        smart_collapse_enabled=False,
        summary_language="off",
    )
    assert res.summaries_created >= 1
    row = conn.execute(
        "SELECT COUNT(*) FROM lcm_summaries WHERE conversation_id = ?",
        (cid,),
    ).fetchone()
    assert int(row[0]) >= 1
    row2 = conn.execute(
        "SELECT COUNT(*) FROM lcm_summary_messages sm JOIN lcm_summaries s ON s.summary_id = sm.summary_id "
        "WHERE s.conversation_id = ?",
        (cid,),
    ).fetchone()
    assert int(row2[0]) >= 8


@pytest.mark.asyncio
async def test_dedup_marks_subsumed_summary() -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _conv_with_messages(conn, 8)
    conn.execute(
        """
        INSERT INTO lcm_summaries (
            summary_id, conversation_id, content, depth, token_count,
            summary_kind, created_at
        ) VALUES ('prior', ?, 'alpha beta gamma delta epsilon', 0, 50, 'compaction', '2026-05-11T00:00:00')
        """,
        (cid,),
    )
    conn.commit()
    sched = CompactionScheduler(conn)
    await sched.run_incremental(
        conversation_id=cid,
        fresh_tail_count=4,
        incremental_max_depth=0,
        transport=_StubTransport(
            reply="alpha beta gamma delta epsilon zeta eta theta iota kappa",
        ),
        model_id="stub-model",
        leaf_min_fanout=8,
        leaf_chunk_tokens=99999,
        condensed_min_fanout=99,
        leaf_target_chars=200,
        condensed_target_chars=200,
        dedup_overlap_threshold=0.5,
        smart_collapse_enabled=False,
        summary_language="off",
    )
    sub = conn.execute(
        "SELECT subsumed_by FROM lcm_summaries WHERE summary_id = 'prior'",
    ).fetchone()
    assert sub is not None
    assert sub[0] is not None


@pytest.mark.asyncio
async def test_leaf_compaction_empty_completion_raises_without_summary_rows() -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _conv_with_messages(conn, 8)
    sched = CompactionScheduler(conn)
    with pytest.raises(RuntimeError, match="empty model output"):
        await sched.run_incremental(
            conversation_id=cid,
            fresh_tail_count=4,
            incremental_max_depth=0,
            transport=_StubTransport(reply="   "),
            model_id="stub-model",
            leaf_min_fanout=8,
            leaf_chunk_tokens=99999,
            condensed_min_fanout=99,
            leaf_target_chars=200,
            condensed_target_chars=200,
            dedup_overlap_threshold=1.0,
            smart_collapse_enabled=False,
            summary_language="off",
        )
    row = conn.execute(
        "SELECT COUNT(*) FROM lcm_summaries WHERE conversation_id = ?",
        (cid,),
    ).fetchone()
    assert int(row[0]) == 0
    row2 = conn.execute(
        "SELECT COUNT(*) FROM lcm_summary_messages sm JOIN lcm_summaries s ON s.summary_id = sm.summary_id "
        "WHERE s.conversation_id = ?",
        (cid,),
    ).fetchone()
    assert int(row2[0]) == 0


@pytest.mark.asyncio
async def test_leaf_compaction_retry_after_transport_failure_is_consistent() -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _conv_with_messages(conn, 8)
    sched = CompactionScheduler(conn)
    flaky = _FlakyTransport()
    with pytest.raises(RuntimeError, match="simulated transport failure"):
        await sched.run_incremental(
            conversation_id=cid,
            fresh_tail_count=4,
            incremental_max_depth=0,
            transport=flaky,
            model_id="stub-model",
            leaf_min_fanout=8,
            leaf_chunk_tokens=99999,
            condensed_min_fanout=99,
            leaf_target_chars=200,
            condensed_target_chars=200,
            dedup_overlap_threshold=1.0,
            smart_collapse_enabled=False,
            summary_language="off",
        )
    assert flaky.calls == 1
    zero = conn.execute(
        "SELECT COUNT(*) FROM lcm_summaries WHERE conversation_id = ?",
        (cid,),
    ).fetchone()
    assert int(zero[0]) == 0

    res = await sched.run_incremental(
        conversation_id=cid,
        fresh_tail_count=4,
        incremental_max_depth=0,
        transport=flaky,
        model_id="stub-model",
        leaf_min_fanout=8,
        leaf_chunk_tokens=99999,
        condensed_min_fanout=99,
        leaf_target_chars=200,
        condensed_target_chars=200,
        dedup_overlap_threshold=1.0,
        smart_collapse_enabled=False,
        summary_language="off",
    )
    assert flaky.calls == 2
    assert res.summaries_created >= 1
    linked = conn.execute(
        "SELECT COUNT(*) FROM lcm_summary_messages sm JOIN lcm_summaries s ON s.summary_id = sm.summary_id "
        "WHERE s.conversation_id = ?",
        (cid,),
    ).fetchone()
    assert int(linked[0]) >= 8


@pytest.mark.asyncio
async def test_compaction_uses_workspace_sampling_params(tmp_path: Path) -> None:
    import sqlite3

    (tmp_path / LLM_PARAMS_FILENAME).write_text(
        json.dumps({"lcm": {"temperature": 0.77}}),
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    cid = _conv_with_messages(conn, 8)
    transport = _StubTransport()
    sched = CompactionScheduler(conn)
    await sched.run_incremental(
        conversation_id=cid,
        fresh_tail_count=4,
        incremental_max_depth=0,
        transport=transport,
        model_id="stub-model",
        leaf_min_fanout=8,
        leaf_chunk_tokens=99999,
        condensed_min_fanout=99,
        leaf_target_chars=200,
        condensed_target_chars=200,
        dedup_overlap_threshold=1.0,
        smart_collapse_enabled=False,
        summary_language="off",
        content_root=tmp_path,
    )
    assert transport.last_request is not None
    assert transport.last_request["temperature"] == pytest.approx(0.77)
