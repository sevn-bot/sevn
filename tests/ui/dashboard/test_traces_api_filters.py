"""Eval-slicing filters on ``GET /api/v1/traces`` (`specs/24-dashboard.md` §10.10)."""

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
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query import ensure_trace_connection
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
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
    tier: str = "B",
    kind: str = "b_turn",
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
            tier,
            kind,
            ts_start_ns,
            ts_start_ns + 10,
            "ok",
            json.dumps(attrs or {}),
        ),
    )


def _seed_eval_slice_rows(client: TestClient) -> None:
    path = traces_sqlite_path(client.app.state.layout.dot_sevn)
    conn = ensure_trace_connection(path)
    try:
        _insert_span(
            conn,
            span_id="b-per-token",
            parent_span_id=None,
            tier="B",
            ts_start_ns=300,
            attrs={
                "budget_regime": "PER_TOKEN",
                "model_id": "anthropic/claude-sonnet-4-6",
            },
        )
        _insert_span(
            conn,
            span_id="c-subscription",
            parent_span_id=None,
            tier="C",
            ts_start_ns=200,
            attrs={
                "budget_regime": "SUBSCRIPTION",
                "model_id": "openai/gpt-4o",
            },
        )
        _insert_span(
            conn,
            span_id="d-free-local",
            parent_span_id=None,
            tier="D",
            ts_start_ns=100,
            attrs={
                "budget_regime": "FREE_LOCAL",
                "model_id": "ollama/llama3",
            },
        )
        conn.commit()
    finally:
        conn.close()


def test_traces_api_filters_budget_regime(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        _seed_eval_slice_rows(client)

        resp = client.get("/api/v1/traces?budget_regime=PER_TOKEN")
        assert resp.status_code == 200
        ids = {row["span_id"] for row in resp.json()["items"]}
        assert ids == {"b-per-token"}


def test_traces_api_filters_model_id(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        _seed_eval_slice_rows(client)

        resp = client.get("/api/v1/traces?model_id=openai/gpt-4o")
        assert resp.status_code == 200
        ids = {row["span_id"] for row in resp.json()["items"]}
        assert ids == {"c-subscription"}


def test_traces_api_filters_tier(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        _seed_eval_slice_rows(client)

        resp = client.get("/api/v1/traces?tier=D")
        assert resp.status_code == 200
        ids = {row["span_id"] for row in resp.json()["items"]}
        assert ids == {"d-free-local"}


def test_traces_api_filters_combined_regime_model_tier(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        _seed_eval_slice_rows(client)

        resp = client.get("/api/v1/traces?budget_regime=SUBSCRIPTION&model_id=openai/gpt-4o&tier=C")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["span_id"] == "c-subscription"
