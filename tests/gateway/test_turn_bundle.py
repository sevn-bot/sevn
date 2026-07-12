"""Tests for post-turn turn bundle writer + index (W1)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.agent.tracing.traces_migrate import apply_traces_migrations
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.post_turn_hooks import (
    PostTurnContext,
    clear_post_turn_hooks,
    register_post_turn_hook,
    run_post_turn_hooks,
)
from sevn.gateway.turn_bundle import (
    bundle_paths,
    collect_turn_bundle_records,
    compute_has_error,
    load_turn_bundle_index,
    resolve_turn_bundle_file,
    upsert_turn_bundle_index_entry,
    write_turn_bundle,
)
from sevn.gateway.turn_bundle_hooks import _post_turn_turn_bundle
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.workspace.layout import WorkspaceLayout

TURN_ID = "telegram:user=1:session=abc:msg=deadbeef"


@pytest.fixture(autouse=True)
def _hooks() -> None:
    clear_post_turn_hooks()
    register_post_turn_hook("turn_bundle", _post_turn_turn_bundle, priority=50)
    yield
    clear_post_turn_hooks()


def _sevn_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    apply_migrations(conn)
    conn.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "sess-1",
            "telegram:1",
            "telegram",
            "1",
            "2026-06-16T00:00:00+00:00",
            "2026-06-16T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO gateway_messages (
            session_id, turn_id, role, kind, content, status, created_at
        ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
        """,
        ("sess-1", TURN_ID, "hello bundle", "2026-06-16T00:00:01+00:00"),
    )
    conn.commit()
    return conn


def _seed_trace(layout: WorkspaceLayout, *, status: str = "ok") -> sqlite3.Connection:
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    traces_path = traces_sqlite_path(layout.dot_sevn)
    conn = sqlite3.connect(traces_path)
    apply_traces_migrations(conn)
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "span-1",
            "sess-1",
            TURN_ID,
            "B",
            "b_turn",
            1_700_000_000_000_000_000,
            1_700_000_000_000_000_001,
            status,
            "{}",
        ),
    )
    conn.commit()
    return conn


def _write_gateway_log(content_root: Path, *, body: str) -> None:
    log_dir = content_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "gateway.log").write_text(body, encoding="utf-8")


def test_collect_turn_bundle_record_shape(tmp_path: Path) -> None:
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    sevn_conn = _sevn_conn()
    trace_conn = _seed_trace(layout)
    _write_gateway_log(
        tmp_path,
        body=(f"2026-06-16 00:00:02.000+00:00 | INFO  | ctx | path:1 fn | turn_id='{TURN_ID}'\n"),
    )
    records, has_error = collect_turn_bundle_records(
        sevn_conn,
        trace_conn,
        session_id="sess-1",
        turn_id=TURN_ID,
        terminal_status="ok",
        content_root=tmp_path,
        created_at="2026-06-16T00:00:00+00:00",
    )
    streams = {row["stream"] for row in records}
    assert records[0]["stream"] == "meta"
    assert streams >= {"meta", "message", "trace", "log"}
    assert has_error is False
    sevn_conn.close()
    trace_conn.close()


def test_write_turn_bundle_creates_day_folder_index_and_jsonl(tmp_path: Path) -> None:
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    sevn_conn = _sevn_conn()
    trace_conn = _seed_trace(layout)
    paths = write_turn_bundle(
        sevn_conn,
        trace_conn,
        content_root=tmp_path,
        session_id="sess-1",
        turn_id=TURN_ID,
        terminal_status="ok",
    )
    assert paths.day_slug == "160626"
    assert paths.bundles_dir == layout.turn_bundles_dir / "160626"
    assert paths.bundle_path.is_file()
    lines = paths.bundle_path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["stream"] == "meta"
    index = load_turn_bundle_index(paths.index_path)
    assert len(index["turns"]) == 1
    assert index["turns"][0]["turn_id"] == TURN_ID
    assert index["turns"][0]["processed"] is False
    sevn_conn.close()
    trace_conn.close()


def test_resolve_turn_bundle_file_legacy_flat_layout(tmp_path: Path) -> None:
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    legacy_dir = layout.turn_bundles_dir
    legacy_dir.mkdir(parents=True)
    bundle_name = "telegram_user_1_session_abc_msg_deadbeef.jsonl"
    bundle_path = legacy_dir / bundle_name
    bundle_path.write_text(
        json.dumps(
            {
                "stream": "meta",
                "turn_id": TURN_ID,
                "session_id": "sess-1",
                "channel": "telegram",
                "terminal_status": "ok",
                "created_at": "2026-06-16T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    upsert_turn_bundle_index_entry(
        legacy_dir / "index.json",
        {
            "turn_id": TURN_ID,
            "file": bundle_name,
            "session_id": "sess-1",
            "channel": "telegram",
            "terminal_status": "ok",
            "has_error": False,
            "processed": False,
            "created_at": "2026-06-16T00:00:00+00:00",
        },
    )
    resolved_path, entry = resolve_turn_bundle_file(tmp_path, TURN_ID)
    assert resolved_path == bundle_path
    assert entry["turn_id"] == TURN_ID


def test_resolve_turn_bundle_file_prefers_day_partition(tmp_path: Path) -> None:
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    day_paths = bundle_paths(tmp_path, TURN_ID, first_seen_at="2026-06-16T00:00:00+00:00")
    day_paths.bundles_dir.mkdir(parents=True)
    day_paths.bundle_path.write_text(
        json.dumps(
            {
                "stream": "meta",
                "turn_id": TURN_ID,
                "session_id": "sess-1",
                "channel": "telegram",
                "terminal_status": "ok",
                "created_at": "2026-06-16T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    upsert_turn_bundle_index_entry(
        day_paths.index_path,
        {
            "turn_id": TURN_ID,
            "file": day_paths.bundle_path.name,
            "session_id": "sess-1",
            "channel": "telegram",
            "terminal_status": "ok",
            "has_error": False,
            "processed": False,
            "created_at": "2026-06-16T00:00:00+00:00",
        },
    )
    legacy_dir = layout.turn_bundles_dir
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_bundle = legacy_dir / day_paths.bundle_path.name
    legacy_bundle.write_text('{"stream":"meta","turn_id":"legacy"}\n', encoding="utf-8")
    upsert_turn_bundle_index_entry(
        legacy_dir / "index.json",
        {
            "turn_id": TURN_ID,
            "file": legacy_bundle.name,
            "session_id": "sess-1",
            "channel": "telegram",
            "terminal_status": "ok",
            "has_error": False,
            "processed": False,
            "created_at": "2026-06-16T00:00:00+00:00",
        },
    )
    resolved_path, _entry = resolve_turn_bundle_file(tmp_path, TURN_ID)
    assert resolved_path == day_paths.bundle_path


def test_index_upsert_preserves_processed_and_created_at(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    created_at = "2026-06-16T00:00:00+00:00"
    base = {
        "turn_id": TURN_ID,
        "file": "first.jsonl",
        "session_id": "sess-1",
        "channel": "telegram",
        "terminal_status": "ok",
        "has_error": False,
        "processed": True,
        "created_at": created_at,
    }
    upsert_turn_bundle_index_entry(index_path, base)
    refreshed = {
        **base,
        "file": "second.jsonl",
        "terminal_status": "error",
        "has_error": True,
        "processed": False,
        "created_at": "2026-06-16T01:00:00+00:00",
    }
    upsert_turn_bundle_index_entry(index_path, refreshed)
    index = load_turn_bundle_index(index_path)
    assert len(index["turns"]) == 1
    row = index["turns"][0]
    assert row["file"] == "second.jsonl"
    assert row["has_error"] is True
    assert row["processed"] is True
    assert row["created_at"] == created_at


def test_compute_has_error_cases() -> None:
    assert compute_has_error(terminal_status="ok") is False
    assert compute_has_error(terminal_status="error") is True
    assert compute_has_error(terminal_status="ok", trace_statuses=["failed"]) is True
    assert (
        compute_has_error(
            terminal_status="ok",
            log_lines=["ERROR | x | y | executor_no_answer tier=B"],
        )
        is True
    )


@pytest.mark.asyncio
async def test_post_turn_hook_writes_bundle_when_enabled(tmp_path: Path) -> None:
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    _seed_trace(layout).close()
    sevn_conn = _sevn_conn()
    router = MagicMock()
    router._content_root = layout.content_root
    router._workspace = WorkspaceConfig.minimal(
        diagnostics={"turn_bundles": {"enabled": True}},
    )
    ctx = PostTurnContext(
        router=router,
        conn=sevn_conn,
        trace=MagicMock(),
        session_id="sess-1",
        correlation_id=TURN_ID,
        terminal_status="ok",
        turn_wall_ns=1_000_000_000,
    )
    with (
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock),
        patch("sevn.gateway.post_turn_hooks.record_turn_finished"),
    ):
        await run_post_turn_hooks(ctx)
    paths = layout.turn_bundles_dir
    bundle_file = paths / "160626" / "telegram_user_1_session_abc_msg_deadbeef.jsonl"
    assert bundle_file.is_file()
    index = load_turn_bundle_index(paths / "160626" / "index.json")
    assert index["turns"][0]["turn_id"] == TURN_ID
    sevn_conn.close()


@pytest.mark.asyncio
async def test_post_turn_hook_noop_when_disabled(tmp_path: Path) -> None:
    layout = WorkspaceLayout(sevn_json_path=tmp_path / "sevn.json", content_root=tmp_path)
    sevn_conn = _sevn_conn()
    router = MagicMock()
    router._content_root = layout.content_root
    router._workspace = WorkspaceConfig.minimal()
    ctx = PostTurnContext(
        router=router,
        conn=sevn_conn,
        trace=MagicMock(),
        session_id="sess-1",
        correlation_id=TURN_ID,
        terminal_status="ok",
        turn_wall_ns=1_000_000_000,
    )
    with (
        patch("sevn.gateway.agent_turn._emit_gateway_span", new_callable=AsyncMock),
        patch("sevn.gateway.post_turn_hooks.record_turn_finished"),
    ):
        await run_post_turn_hooks(ctx)
    assert not layout.turn_bundles_dir.exists()
    sevn_conn.close()
