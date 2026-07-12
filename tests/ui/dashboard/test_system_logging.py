"""Mission Control logging retention API (`specs/24-dashboard.md` §10.7 Wave 4)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    LoggingWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
)
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "logging": {"retention_days": 10, "archive_mode": "copy"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
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
        logging=LoggingWorkspaceConfig(retention_days=10, archive_mode="copy"),
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


def test_system_logging_get_returns_defaults(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.get("/api/v1/system/logging", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["retention_days"] == 10
        assert body["archive_mode"] == "copy"
        assert body["archive_destination"] == "logs/archive"


def test_system_logging_put_writes_sevn_json_and_sweeps(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "gateway-20260101T000000Z.log"
    old.write_text("old\n", encoding="utf-8")
    aged = time.time() - 86400
    os.utime(old, (aged, aged))

    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.put(
            "/api/v1/system/logging",
            headers=headers,
            json={
                "retention_days": 0,
                "archive_mode": "delete",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["retention_days"] == 0
        assert body["archive_mode"] == "delete"
        assert body["sweep"]["archived"] == 1
        assert not old.exists()

    on_disk = json.loads((tmp_path / "sevn.json").read_text(encoding="utf-8"))
    assert on_disk["logging"]["retention_days"] == 0
    assert on_disk["logging"]["archive_mode"] == "delete"


def test_system_logging_put_requires_cloud_bucket_ref(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.put(
            "/api/v1/system/logging",
            headers=headers,
            json={"archive_mode": "r2"},
        )
        assert resp.status_code == 422


def test_system_logging_put_copy_archives_backdated_file(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    old = logs / "proxy-20260101T000000Z.log"
    old.write_text("proxy\n", encoding="utf-8")
    os.utime(old, (time.time() - 86400, time.time() - 86400))

    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.put(
            "/api/v1/system/logging",
            headers=headers,
            json={
                "retention_days": 0,
                "archive_mode": "copy",
                "archive_destination": "logs/archive",
            },
        )
        assert resp.status_code == 200
        archived = tmp_path / "logs" / "archive" / old.name
        assert archived.is_file()
        assert not old.exists()


def test_gateway_lifespan_runs_log_sweeper_on_boot(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "logging": {"retention_days": 10, "archive_mode": "delete"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
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
        logging=LoggingWorkspaceConfig(retention_days=10, archive_mode="delete"),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    with patch("sevn.gateway.http_server.sweep_rotated_service_logs") as mocked:
        mocked.return_value = type(
            "R",
            (),
            {"scanned": 0, "archived": 0, "skipped_cloud": 0},
        )()
        app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
        with TestClient(app, raise_server_exceptions=True):
            pass
        assert mocked.call_count >= 1
