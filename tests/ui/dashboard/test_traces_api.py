"""Tests for dashboard trace browse APIs (`specs/24-dashboard.md` §10.10)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy
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
from sevn.ui.dashboard.query import ensure_trace_connection, get_span_with_children
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


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
    session_id: str = "sess-a",
    turn_id: str = "turn-1",
    kind: str = "b_turn",
    ts_start_ns: int,
    ts_end_ns: int | None = None,
    status: str = "ok",
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
            session_id,
            turn_id,
            "B",
            kind,
            ts_start_ns,
            ts_end_ns,
            status,
            json.dumps(attrs or {}),
        ),
    )


def _seed_out_of_order_tree(client: TestClient) -> None:
    path = traces_sqlite_path(client.app.state.layout.dot_sevn)
    conn = ensure_trace_connection(path)
    try:
        _insert_span(
            conn, span_id="child", parent_span_id="root", kind="tool.invoke", ts_start_ns=200
        )
        _insert_span(
            conn, span_id="root", parent_span_id=None, kind="b_turn", ts_start_ns=100, ts_end_ns=250
        )
        _insert_span(
            conn,
            span_id="grandchild",
            parent_span_id="child",
            kind="provider.after",
            ts_start_ns=220,
        )
        _insert_span(
            conn,
            span_id="other-session",
            parent_span_id=None,
            session_id="sess-b",
            kind="gateway.boot",
            ts_start_ns=50,
        )
        conn.commit()
    finally:
        conn.close()


def test_span_tree_assembly_out_of_order(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _seed_out_of_order_tree(client)
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            tree = get_span_with_children(
                conn,
                "root",
                policy=TraceRedactionPolicy.from_defaults(),
            )
        finally:
            conn.close()
    assert tree is not None
    assert tree["span_id"] == "root"
    assert len(tree["children"]) == 1
    child = tree["children"][0]
    assert child["span_id"] == "child"
    assert len(child["children"]) == 1
    assert child["children"][0]["span_id"] == "grandchild"


def test_traces_list_filters_kind_status_and_time_range(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            _insert_span(
                conn, span_id="a", parent_span_id=None, kind="b_turn", ts_start_ns=100, status="ok"
            )
            _insert_span(
                conn,
                span_id="b",
                parent_span_id=None,
                kind="tool.invoke",
                ts_start_ns=200,
                status="error",
            )
            _insert_span(
                conn, span_id="c", parent_span_id=None, kind="b_turn", ts_start_ns=300, status="ok"
            )
            conn.commit()
        finally:
            conn.close()

        by_kind = client.get("/api/v1/traces?kind=b_turn")
        assert by_kind.status_code == 200
        assert {row["span_id"] for row in by_kind.json()["items"]} == {"a", "c"}

        by_status = client.get("/api/v1/traces?status=error")
        assert by_status.status_code == 200
        assert [row["span_id"] for row in by_status.json()["items"]] == ["b"]

        by_range = client.get("/api/v1/traces?ts_from=150&ts_to=250")
        assert by_range.status_code == 200
        assert [row["span_id"] for row in by_range.json()["items"]] == ["b"]


def test_trace_detail_returns_nested_children(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        _seed_out_of_order_tree(client)
        resp = client.get("/api/v1/traces/root")
        assert resp.status_code == 200
        root = resp.json()["span"]
        assert root["span_id"] == "root"
        assert root["children"][0]["span_id"] == "child"
        assert root["children"][0]["children"][0]["span_id"] == "grandchild"


def test_trace_detail_not_found(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/traces/missing-span")
        assert resp.status_code == 404


def test_traces_read_path_redaction(tmp_path: Path) -> None:
    redaction = TraceRedactionConfig(
        enabled=True,
        deny_keys=["authorization", "api_key"],
        deny_value_patterns=["sk-[A-Za-z0-9]{20,}"],
    )
    with _client(tmp_path, redaction=redaction) as client:
        _login(client)
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
        try:
            _insert_span(
                conn,
                span_id="secret-span",
                parent_span_id=None,
                kind="provider.after",
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

        detail = client.get("/api/v1/traces/secret-span")
        assert detail.status_code == 200
        detail_attrs = detail.json()["span"]["attrs"]
        assert detail_attrs["api_key"] == "<redacted>"
        assert detail_attrs["note"] == "<redacted>"


def test_traces_query_alias_still_works(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/traces/query")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_cursor": None, "has_more": False}
