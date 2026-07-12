"""Read-path redaction on dashboard trace APIs (`specs/04-tracing.md` §2.5)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TraceRedactionConfig,
    TracingConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query import ensure_trace_connection
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(
    tmp_path: Path, *, redaction: TraceRedactionConfig | None = None
) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    tracing = TracingConfig(redaction=redaction) if redaction is not None else None
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        tracing=tracing,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"password": "pw"})
    assert resp.status_code == 200


def _insert_span(
    conn: sqlite3.Connection,
    *,
    span_id: str,
    parent_span_id: str | None,
    kind: str = "provider.after",
    ts_start_ns: int,
    attrs: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO trace_events (
            span_id, parent_span_id, session_id, turn_id, tier, kind,
            ts_start_ns, ts_end_ns, status, attrs_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            span_id,
            parent_span_id,
            "sess-a",
            "turn-1",
            "B",
            kind,
            ts_start_ns,
            ts_start_ns + 10,
            "ok",
            json.dumps(attrs or {}),
        ),
    )


def test_traces_list_strips_deny_keys(tmp_path: Path) -> None:
    redaction = TraceRedactionConfig(
        enabled=True,
        deny_keys=["authorization", "api_key"],
        deny_value_patterns=["sk-[A-Za-z0-9]{20,}"],
    )
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    with _client(tmp_path, redaction=redaction) as client:
        _login(client)
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            _insert_span(
                conn,
                span_id="secret-span",
                parent_span_id=None,
                ts_start_ns=100,
                attrs={"api_key": secret, "note": secret, "safe": "visible"},
            )
            conn.commit()
        finally:
            conn.close()

        listed = client.get("/api/v1/traces?kind=provider.after")
        assert listed.status_code == 200
        attrs = listed.json()["items"][0]["attrs"]
        assert attrs["api_key"] == "<redacted>"
        assert attrs["note"] == "<redacted>"
        assert attrs["safe"] == "visible"


def test_trace_detail_strips_deny_keys_in_tree(tmp_path: Path) -> None:
    redaction = TraceRedactionConfig(
        enabled=True,
        deny_keys=["authorization", "api_key"],
        deny_value_patterns=[],
    )
    with _client(tmp_path, redaction=redaction) as client:
        _login(client)
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            _insert_span(
                conn,
                span_id="root",
                parent_span_id=None,
                kind="b_turn",
                ts_start_ns=100,
                attrs={"safe": "root"},
            )
            _insert_span(
                conn,
                span_id="child",
                parent_span_id="root",
                kind="tool.invoke",
                ts_start_ns=110,
                attrs={"api_key": "leak", "safe": "child"},
            )
            conn.commit()
        finally:
            conn.close()

        detail = client.get("/api/v1/traces/root")
        assert detail.status_code == 200
        root = detail.json()["span"]
        assert root["attrs"]["safe"] == "root"
        child = root["children"][0]
        assert child["attrs"]["api_key"] == "<redacted>"
        assert child["attrs"]["safe"] == "child"
