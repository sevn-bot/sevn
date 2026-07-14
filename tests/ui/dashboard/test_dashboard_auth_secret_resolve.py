"""Dashboard auth resolves ``${SECRET:…}`` login passwords at gateway boot."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from starlette.testclient import TestClient

if TYPE_CHECKING:
    import pytest

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    GatewayConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.dashboard_password import DASHBOARD_LOGIN_PASSWORD_CONFIG_REF
from sevn.workspace.layout import WorkspaceLayout

_RESOLVED_GATEWAY_TOKEN = "g" * 64
_RESOLVED_DASHBOARD_PASSWORD = "dashboard-owner-password"


@contextmanager
def _client(
    tmp_path: Path,
    *,
    login_password: str | None = DASHBOARD_LOGIN_PASSWORD_CONFIG_REF,
    tunnel_mode: str = "cloudflare",
) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    ws = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway=GatewayConfig(
            host="127.0.0.1",
            port=3001,
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password=login_password,
            jwt_secret="dashboard-secret",
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        infrastructure={"tunnel": {"mode": tunnel_mode}},
    )
    layout = WorkspaceLayout.from_config(sevn_json, ws)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    with (
        patch(
            "sevn.gateway.runtime.gateway_token.resolve_gateway_token_ref",
            return_value=_RESOLVED_GATEWAY_TOKEN,
        ),
        patch(
            "sevn.ui.dashboard.dashboard_password.resolve_dashboard_login_password_ref",
            return_value=_RESOLVED_DASHBOARD_PASSWORD if login_password else None,
        ),
    ):
        app = create_app(workspace=ws, layout=layout, sqlite_connection_factory=factory)
        with TestClient(app, client=("127.0.0.1", 0), raise_server_exceptions=True) as client:
            yield client


def test_login_accepts_resolved_dashboard_password_not_secret_ref(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        status = client.get("/api/v1/auth/status")
        assert status.json()["auth_required"] is True
        assert status.json()["tunnel_active"] is True

        bad = client.post(
            "/api/v1/auth/login",
            json={"password": DASHBOARD_LOGIN_PASSWORD_CONFIG_REF},
        )
        assert bad.status_code == 401

        ok = client.post(
            "/api/v1/auth/login",
            json={"password": _RESOLVED_DASHBOARD_PASSWORD},
        )
        assert ok.status_code == 200
        assert client.get("/api/v1/sessions?limit=1").status_code == 200


def test_login_falls_back_to_resolved_gateway_token_when_no_dashboard_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    with _client(tmp_path, login_password=None) as client:
        bad = client.post(
            "/api/v1/auth/login",
            json={"password": "${SECRET:keychain:sevn.gateway.token}"},
        )
        assert bad.status_code == 401

        ok = client.post(
            "/api/v1/auth/login",
            json={"password": _RESOLVED_GATEWAY_TOKEN},
        )
        assert ok.status_code == 200
