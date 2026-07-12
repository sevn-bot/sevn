"""Mission Control CLI console API tests (MC W1 §2c)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.api import cli_console as cli_mod
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "test-gw-token"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=False,
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "test-gw-token"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_cli_doctor_json_happy_path(tmp_path: Path) -> None:
    mock_response = cli_mod.CliRunResponse(
        exit_code=0,
        stdout='{"ok": true}',
        stderr="",
        duration_ms=12,
    )
    with _client(tmp_path) as client:
        headers = _headers(client)
        with patch.object(cli_mod, "_run_sevn", new=AsyncMock(return_value=mock_response)):
            resp = client.post(
                "/api/v1/cli/run",
                headers=headers,
                json={"argv": ["doctor", "--json"]},
            )
        assert resp.status_code == 200
        assert resp.json()["exit_code"] == 0


def test_cli_denylisted_without_confirm(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _headers(client)
        resp = client.post(
            "/api/v1/cli/run",
            headers=headers,
            json={"argv": ["secrets", "rm", "demo.key"]},
        )
        assert resp.status_code == 400


def test_cli_unauthenticated(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert (
            client.post(
                "/api/v1/cli/run",
                json={"argv": ["doctor"]},
                headers={"X-Forwarded-For": "203.0.113.1"},
            ).status_code
            == 401
        )
