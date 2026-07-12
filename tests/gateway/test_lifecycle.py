"""Gateway lifecycle / boot wiring tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from sevn.agent.harness.snapshots import HarnessBootSweepResult
from sevn.config.workspace_config import (
    GatewayConfig,
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.paths import sevn_db_path, traces_sqlite_path
from sevn.storage.sqlite import open_sevn_sqlite
from sevn.workspace.layout import WorkspaceLayout


def _memory_sqlite_factory() -> sqlite3.Connection:
    conn_local = sqlite3.connect(":memory:", check_same_thread=False)
    conn_local.execute("PRAGMA journal_mode=WAL")
    conn_local.execute("PRAGMA foreign_keys=ON")
    from sevn.storage.migrate import apply_migrations

    apply_migrations(conn_local)
    return conn_local


def _lifecycle_client(tmp_path: object) -> tuple[TestClient, WorkspaceLayout]:
    from pathlib import Path

    root = Path(str(tmp_path))
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=[TraceSinkEntry.model_validate({"type": "sqlite"})]),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=_memory_sqlite_factory,
    )
    return TestClient(app, raise_server_exceptions=True), layout


def test_gateway_boot_and_shutdown_spans(tmp_path: object) -> None:
    client, layout = _lifecycle_client(tmp_path)
    with client:
        client.get("/ready")
    db_path = traces_sqlite_path(layout.dot_sevn)
    conn = sqlite3.connect(db_path)
    try:
        kinds = {
            str(row[0])
            for row in conn.execute("SELECT kind FROM trace_events WHERE kind LIKE 'gateway.%'")
        }
        assert "gateway.boot" in kinds
        assert "gateway.shutdown" in kinds
    finally:
        conn.close()


def test_boot_sweep_invoked(tmp_workspace: tuple[object, object]) -> None:
    ws, layout = tmp_workspace
    stub = HarnessBootSweepResult(gc_deleted_count=0, owner_prompt_runs=(), auto_resumed_tier_b=())
    with patch(
        "sevn.gateway.http_server.run_harness_boot_sweep", new=AsyncMock(return_value=stub)
    ) as sweep:
        app = create_app(workspace=ws, layout=layout)
        with TestClient(app):
            pass
        assert sweep.await_count == 1


def test_adapter_stop_on_shutdown(tmp_workspace: tuple[object, object]) -> None:
    ws, layout = tmp_workspace
    app = create_app(workspace=ws, layout=layout)
    mock_stop: AsyncMock | None = None
    with TestClient(app) as client:
        adapter = client.app.state.gateway_router.adapter_named("telegram")
        assert adapter is not None
        mock_stop = AsyncMock(wraps=adapter.stop)
        adapter.stop = mock_stop  # type: ignore[method-assign]
    assert mock_stop is not None
    mock_stop.assert_awaited()


def test_dispatcher_callbacks_ttl_prune_at_boot(tmp_workspace: tuple[object, object]) -> None:
    ws, layout = tmp_workspace
    conn = open_sevn_sqlite(layout.dot_sevn)
    old = (datetime.now(tz=UTC) - timedelta(days=3)).replace(tzinfo=None).isoformat()
    fresh = (datetime.now(tz=UTC) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    conn.execute(
        "INSERT INTO dispatcher_callbacks(callback_query_id, created_at) VALUES (?, ?)",
        ("cq-old", old),
    )
    conn.execute(
        "INSERT INTO dispatcher_callbacks(callback_query_id, created_at) VALUES (?, ?)",
        ("cq-fresh", fresh),
    )
    conn.commit()
    conn.close()

    ws2 = ws.model_copy(
        update={
            "gateway": GatewayConfig(
                dispatcher_callbacks_ttl_s=86_400, token="${SECRET:keychain:sevn.gateway.token}"
            )
        }
    )
    app = create_app(workspace=ws2, layout=layout)
    with TestClient(app):
        pass
    conn2 = sqlite3.connect(sevn_db_path(layout.dot_sevn), check_same_thread=False)
    try:
        ids = {
            str(r[0]) for r in conn2.execute("SELECT callback_query_id FROM dispatcher_callbacks")
        }
        assert "cq-old" not in ids
        assert "cq-fresh" in ids
    finally:
        conn2.close()


def test_shutdown_closes_gateway_browsers(tmp_workspace: tuple[object, object]) -> None:
    ws, layout = tmp_workspace
    with patch(
        "sevn.gateway.http_server.close_all_gateway_browsers",
        return_value=2,
    ) as mock_close:
        app = create_app(workspace=ws, layout=layout)
        with TestClient(app):
            pass
        mock_close.assert_called_once()


def test_boot_outbound_sweep_pending_to_sent(tmp_workspace: tuple[object, object]) -> None:
    ws, layout = tmp_workspace
    conn = open_sevn_sqlite(layout.dot_sevn)
    now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
    conn.execute(
        """
        INSERT INTO gateway_sessions(
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("sess-retry", "telegram:retry-scope", "telegram", "77", now, now),
    )
    conn.execute(
        """
        INSERT INTO gateway_messages(
            session_id, role, kind, content, visible_to_llm, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("sess-retry", "assistant", "message", "stored-reply", 1, "pending", now),
    )
    conn.commit()
    conn.close()

    app = create_app(workspace=ws, layout=layout)
    with TestClient(app):
        pass
    conn2 = sqlite3.connect(sevn_db_path(layout.dot_sevn), check_same_thread=False)
    try:
        st = conn2.execute(
            "SELECT status FROM gateway_messages WHERE content = 'stored-reply'",
        ).fetchone()
        assert st is not None
        assert str(st[0]) == "sent"
    finally:
        conn2.close()
