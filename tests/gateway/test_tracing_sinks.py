"""Gateway trace sink wiring (`specs/04-tracing.md` §10.7 + `specs/17-gateway.md`)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TraceSinkEntry,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _memory_sqlite_factory() -> sqlite3.Connection:
    conn_local = sqlite3.connect(":memory:", check_same_thread=False)
    conn_local.execute("PRAGMA journal_mode=WAL")
    conn_local.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn_local)
    return conn_local


def _client_with_trace_sinks(
    tmp_path: Path,
    *,
    sinks: list[TraceSinkEntry],
) -> tuple[TestClient, WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        tracing=TracingConfig(sinks=sinks),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=_memory_sqlite_factory,
    )
    return TestClient(app, raise_server_exceptions=True), layout, workspace_cfg


def test_gateway_multi_sink_boot_writes_sqlite_and_jsonl(tmp_path: Path) -> None:
    jsonl_rel = ".sevn/boot-traces.jsonl"
    client, layout, _cfg = _client_with_trace_sinks(
        tmp_path,
        sinks=[
            TraceSinkEntry.model_validate({"type": "sqlite"}),
            TraceSinkEntry.model_validate({"type": "jsonl_file", "path": jsonl_rel}),
        ],
    )
    with client:
        client.get("/health")

    db_path = layout.dot_sevn / "traces.db"
    assert db_path.is_file()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT kind FROM trace_events WHERE kind = ?",
            ("harness.snapshot.gc_orphan",),
        ).fetchone()
        assert row is not None
    finally:
        conn.close()

    jsonl_path = (layout.content_root / jsonl_rel).resolve()
    assert jsonl_path.is_file()
    kinds = [
        json.loads(line)["kind"]
        for line in jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    ]
    assert "harness.snapshot.gc_orphan" in kinds


def test_gateway_without_tracing_skips_trace_db(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=_memory_sqlite_factory,
    )
    with TestClient(app, raise_server_exceptions=True) as client:
        client.get("/health")

    traces_db = layout.dot_sevn / "traces.db"
    assert not traces_db.exists()


def test_only_deferred_sink_types_use_null_sink(tmp_path: Path) -> None:
    client, layout, _cfg = _client_with_trace_sinks(
        tmp_path,
        sinks=[TraceSinkEntry.model_validate({"type": "otel"})],
    )
    with client:
        client.get("/health")

    assert not (layout.dot_sevn / "traces.db").exists()
