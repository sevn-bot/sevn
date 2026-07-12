"""Mission Control real-data gate tests (`specs/24-dashboard.md` Wave 9 Agent 9C)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
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
from sevn.ui.dashboard.query import (
    budget_summary_from_traces,
    ensure_trace_connection,
    search_trace_events,
)
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_COOKIE_NAME,
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
)
from sevn.workspace.layout import WorkspaceLayout

pytestmark = pytest.mark.xdist_group("dashboard_real_data")


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


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


def _seed_traces(client: TestClient) -> None:
    import asyncio

    from tests._helpers.provider_trace_emit import emit_provider_call_rows

    path = traces_sqlite_path(client.app.state.layout.dot_sevn)
    asyncio.run(
        emit_provider_call_rows(
            path,
            session_id="sess-a",
            turn_id="t1",
            model_id="anthropic/claude-sonnet-4-6",
            regime="SUBSCRIPTION",
            tokens_in=100,
            tokens_out=50,
            subscription_window_remaining=73,
            subscription_window_id="win-1",
        ),
    )
    conn = ensure_trace_connection(path)
    try:
        conn.execute(
            """INSERT INTO trace_events (
                span_id, parent_span_id, session_id, turn_id, tier, kind,
                ts_start_ns, ts_end_ns, status, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "t1",
                None,
                "sess-a",
                "t1",
                "B",
                "tool.invoke",
                90,
                95,
                "ok",
                json.dumps({"tool": "ripgrep-find"}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_login_sets_httponly_session_and_csrf_cookies(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        assert client.cookies.get(DASHBOARD_COOKIE_NAME)
        assert client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
        assert login.json().get("csrf_token")


def _seed_replayable_turn(client: TestClient) -> None:
    """Seed trace + gateway user message so dashboard replay accepts the turn."""
    _seed_traces(client)
    db: sqlite3.Connection = client.app.state.sqlite_conn
    db.execute(
        """
        INSERT INTO gateway_sessions (
            session_id, scope_key, channel, user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("sess-a", "webchat:sess-a", "webchat", "owner", "2026-01-01", "2026-01-01"),
    )
    db.execute(
        """
        INSERT INTO gateway_messages (
            session_id, role, kind, content, visible_to_llm, status,
            extras_json, created_at, turn_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("sess-a", "user", "message", "hello replay", 1, "sent", "{}", "2026-01-01", "t1"),
    )
    db.commit()


def test_replay_requires_csrf_double_submit(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        _seed_replayable_turn(client)
        # CSRF gate only — do not schedule real replay work (TestClient waits on bg tasks).
        client.app.state.replay_worker = None
        blocked = client.post(
            "/api/v1/sessions/sess-a/turns/t1/replay",
            json={"confirmed": True},
        )
        assert blocked.status_code == 403
        allowed = client.post(
            "/api/v1/sessions/sess-a/turns/t1/replay",
            json={"confirmed": True},
            headers=_csrf_headers(client),
        )
        assert allowed.status_code == 202


def test_unified_search_uses_fts5(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        _seed_traces(client)
        hits = client.get("/api/v1/search?q=ripgrep")
        assert hits.status_code == 200
        span_ids = [row["span_id"] for row in hits.json()["items"]]
        assert "t1" in span_ids


def test_budget_summary_empty_without_provider_traces(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        summary = client.get("/api/v1/budget/summary")
        assert summary.status_code == 200
        assert summary.json()["by_regime"] == []


def test_budget_summary_returns_regime_and_subscription_window(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        _seed_traces(client)
        summary = client.get("/api/v1/budget/summary")
        assert summary.status_code == 200
        body = summary.json()
        regimes = {row["regime"] for row in body["by_regime"]}
        assert "SUBSCRIPTION" in regimes
        windows = body["subscription_windows"]
        assert any(w["model_id"] == "anthropic/claude-sonnet-4-6" for w in windows)
        assert any(w.get("window_remaining") == 73 for w in windows)


def test_budget_and_search_query_helpers(tmp_path: Path) -> None:
    path = tmp_path / "traces.db"
    conn = ensure_trace_connection(path)
    try:
        conn.execute(
            """INSERT INTO trace_events (
                span_id, parent_span_id, session_id, turn_id, tier, kind,
                ts_start_ns, ts_end_ns, status, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("x1", None, "s", "t", "B", "tool.invoke", 1, 2, "ok", '{"needle":"haystack"}'),
        )
        conn.commit()
        search = search_trace_events(conn, query="haystack", limit=5)
        assert search["items"]
        summary = budget_summary_from_traces(conn)
        assert "by_regime" in summary
    finally:
        conn.close()


def test_traces_and_session_api_calls_return_seeded_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        _seed_traces(client)
        traces = client.get("/api/v1/traces/query?limit=10")
        assert traces.status_code == 200
        assert len(traces.json()["items"]) >= 2
        calls = client.get("/api/v1/sessions/sess-a/api-calls?limit=10")
        assert calls.status_code == 200
        assert calls.json()["items"][0]["kind"] == "provider.call"
