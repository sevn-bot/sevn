"""Tests for ``.sevn/tool_results`` GC (`specs/11-tools-registry.md` §3.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sevn.tools.spill_gc import prune_orphan_tool_result_dirs


def test_prune_removes_orphan_session_dirs(tmp_path: Path) -> None:
    content = tmp_path / "ws"
    stale = content / ".sevn" / "tool_results" / "gone-session"
    stale.mkdir(parents=True)
    (stale / "big.json").write_text('{"x":1}', encoding="utf-8")
    kept = content / ".sevn" / "tool_results" / "live-session"
    kept.mkdir(parents=True)
    (kept / "keep.json").write_text('{"y":2}', encoding="utf-8")

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO gateway_sessions (session_id) VALUES ('live-session')")
    conn.commit()

    n = prune_orphan_tool_result_dirs(content_root=content, conn=conn)
    assert n == 1
    assert not stale.exists()
    assert (kept / "keep.json").is_file()


def test_prune_noop_when_tool_results_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE gateway_sessions (session_id TEXT PRIMARY KEY)")
    conn.commit()
    assert prune_orphan_tool_result_dirs(content_root=tmp_path, conn=conn) == 0
