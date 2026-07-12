"""Mission Control trace fan-out from gateway lifespan (Wave T-0B)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _memory_sqlite_factory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _fanout_client(tmp_path: object) -> TestClient:
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
    return TestClient(app, raise_server_exceptions=True)


def test_gateway_boot_span_in_mission_activity_feed(tmp_path: object) -> None:
    client = _fanout_client(tmp_path)
    with client:
        client.get("/ready")
        state = client.app.state.mission_control_state
        feed = state.get_activity_feed(limit=20)
        boot_rows = [
            row for row in feed if row.get("type") == "gateway" and "boot" in row["detail"]
        ]
        assert boot_rows, feed
