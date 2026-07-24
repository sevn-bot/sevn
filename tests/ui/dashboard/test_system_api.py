"""Mission Control system/admin API (`specs/24-dashboard.md` §10.5 Wave O)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

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
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
)
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


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_config_validate_and_write_roundtrip(tmp_path: Path) -> None:
    doc = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    }
    with _client(tmp_path) as client:
        headers = _login(client)
        valid = client.post("/api/v1/config/validate", json=doc, headers=headers)
        assert valid.status_code == 200
        assert valid.json()["ok"] is True
        write = client.put("/api/v1/config", json=doc, headers=headers)
        assert write.status_code == 200
        assert write.json()["ok"] is True
        on_disk = (tmp_path / "sevn.json").read_text(encoding="utf-8")
        assert '"schema_version": 1' in on_disk


def test_migrate_preview_describes_schema(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.post("/api/v1/migrate/preview", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "changed" in body
        assert body["current"] == 1


def test_proxy_restart_delegates_to_service_manager(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        with patch(
            "sevn.ui.dashboard.api.system.control_unit",
            return_value="proxy restart: ok",
        ) as mocked:
            first = client.post("/api/v1/proxy/restart", headers=headers)
            second = client.post("/api/v1/proxy/restart", headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["status"] == "ok"
        assert mocked.call_count == 2


def test_proxy_restart_502_on_service_manager_error(tmp_path: Path) -> None:
    from sevn.cli.service_manager import ServiceManagerError

    with _client(tmp_path) as client:
        headers = _login(client)
        with patch(
            "sevn.ui.dashboard.api.system.control_unit",
            side_effect=ServiceManagerError("unit missing"),
        ):
            resp = client.post("/api/v1/proxy/restart", headers=headers)
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "proxy_restart_failed"


def test_proxy_logs_tail_redacts_secrets(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "proxy.log").write_text("ok line\ntoken=supersecret\n", encoding="utf-8")
    with _client(tmp_path) as client:
        headers = _login(client)
        _ = headers
        resp = client.get("/api/v1/proxy/logs")
        assert resp.status_code == 200
        body = resp.json()
        assert "supersecret" not in "\n".join(body["lines"])
        assert "<redacted>" in "\n".join(body["lines"])


def test_oauth_reauth_returns_handoff_without_secrets(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        with patch(
            "sevn.ui.dashboard.api.system.secrets_chain_from_workspace",
        ) as factory:
            chain = factory.return_value

            async def _fake_get(_key: str) -> None:
                return None

            chain.get = _fake_get
            resp = client.post(
                "/api/v1/providers/openai/oauth/reauth",
                headers=headers,
            )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "handoff"
        assert body["provider_id"] == "openai"
        assert body["has_existing_token"] is False
        assert "supersecret" not in str(body)


def test_upgrade_restart_pauses_runs_and_restarts_gateway(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        conn.execute(
            """INSERT INTO active_run_snapshots (
                run_id, session_id, tier, plan_state, in_flight_tools,
                excerpt, status, created_at_ns, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("r1", "s1", "C", "{}", "[]", "active", "active", 1, 2),
        )
        conn.commit()
        with patch(
            "sevn.ui.dashboard.api.system.control_unit",
            return_value="gateway restart: ok",
        ) as mocked:
            resp = client.post(
                "/api/v1/system/upgrade-restart",
                json={"consent": True, "apply_schema_upgrade": False},
                headers=headers,
            )
        assert resp.status_code == 200
        assert resp.json()["paused_runs"] == 1
        mocked.assert_called_once()


def test_replay_turn_404_without_trace_history(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.post(
            "/api/v1/sessions/s1/turns/t1/replay",
            json={"confirmed": True},
            headers=headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "turn_snapshot_not_found"


def test_replay_turn_happy_path_with_trace_seed(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        db: sqlite3.Connection = client.app.state.sqlite_conn
        db.execute(
            """
            INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s1", "webchat:s1", "webchat", "owner", "2026-01-01", "2026-01-01"),
        )
        db.execute(
            """
            INSERT INTO gateway_messages (
                session_id, role, kind, content, visible_to_llm, status,
                extras_json, created_at, turn_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s1", "user", "message", "hello replay", 1, "sent", "{}", "2026-01-01", "t1"),
        )
        db.commit()
        path = traces_sqlite_path(client.app.state.layout.dot_sevn)
        conn = ensure_trace_connection(path)
        try:
            conn.execute(
                """INSERT INTO trace_events (
                    span_id, parent_span_id, session_id, turn_id, tier, kind,
                    ts_start_ns, ts_end_ns, status, attrs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("span-r", None, "s1", "t1", "B", "b_turn", 1, 2, "ok", "{}"),
            )
            conn.commit()
        finally:
            conn.close()
        # Queue acceptance only — do not run a live agent turn (avoids xdist
        # SIGSEGV from concurrent SQLite teardown during TestClient exit).
        worker = getattr(client.app.state, "replay_worker", None)
        if worker is not None:
            with patch.object(worker, "schedule"):
                first = client.post(
                    "/api/v1/sessions/s1/turns/t1/replay",
                    json={"confirmed": True},
                    headers=headers,
                )
                second = client.post(
                    "/api/v1/sessions/s1/turns/t1/replay",
                    json={"confirmed": True},
                    headers=headers,
                )
        else:
            first = client.post(
                "/api/v1/sessions/s1/turns/t1/replay",
                json={"confirmed": True},
                headers=headers,
            )
            second = client.post(
                "/api/v1/sessions/s1/turns/t1/replay",
                json={"confirmed": True},
                headers=headers,
            )
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["replay_job_id"] == second.json()["replay_job_id"]
