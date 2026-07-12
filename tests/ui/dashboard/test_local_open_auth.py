"""Local-open Mission Control auth (`specs/24-dashboard.md` Wave MC-2)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    GatewayConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import (
    apply_tunnel_local_open_policy,
    dashboard_local_open_configured,
    local_open_effective,
    tunnel_active,
)
from sevn.workspace.layout import WorkspaceLayout


def _workspace(
    *,
    local_open: bool | None = True,
    login_password: str = "pw",
    tunnel_mode: str = "none",
    gateway_host: str = "127.0.0.1",
) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway=GatewayConfig(
            host=gateway_host, port=3001, token="${SECRET:keychain:sevn.gateway.token}"
        ),
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            local_open=local_open,
            login_password=login_password,
            jwt_secret="dashboard-secret",
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        infrastructure={"tunnel": {"mode": tunnel_mode}},
    )


@contextmanager
def _client(
    tmp_path: Path,
    *,
    workspace: WorkspaceConfig | None = None,
    remote: bool = False,
) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = workspace or _workspace()
    apply_tunnel_local_open_policy(cfg)
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    client_host = ("203.0.113.1", 40000) if remote else ("127.0.0.1", 0)
    with TestClient(app, client=client_host, raise_server_exceptions=True) as client:
        yield client


def test_auth_status_local_open_loopback(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get("/api/v1/auth/status")
        assert resp.status_code == 200
        assert resp.json() == {
            "auth_required": False,
            "local_open": True,
            "tunnel_active": False,
        }


def test_sessions_without_login_on_loopback(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get("/api/v1/sessions?limit=5")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "next_cursor": None, "has_more": False}


def test_dashboard_nav_without_login_on_loopback(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get("/api/v1/dashboard/nav")
        assert resp.status_code == 200
        assert resp.json()["tab_count"] == 45


def test_remote_client_requires_auth(tmp_path: Path) -> None:
    with _client(tmp_path, remote=True) as client:
        assert client.get("/api/v1/sessions?limit=1").status_code == 401
        assert client.get("/api/v1/dashboard/nav").status_code == 401
        status = client.get("/api/v1/auth/status")
        assert status.status_code == 200
        body = status.json()
        assert body["auth_required"] is True
        assert body["local_open"] is False


def test_tunnel_disables_local_open(tmp_path: Path) -> None:
    ws = _workspace(local_open=True, tunnel_mode="cloudflare")
    assert tunnel_active(ws)
    apply_tunnel_local_open_policy(ws)
    assert ws.dashboard is not None
    assert ws.dashboard.local_open is False
    assert dashboard_local_open_configured(ws) is False
    with _client(tmp_path, workspace=ws) as client:
        assert client.get("/api/v1/sessions?limit=1").status_code == 401
        status = client.get("/api/v1/auth/status")
        assert status.json()["tunnel_active"] is True
        assert status.json()["local_open"] is False


def test_disk_tunnel_setup_disables_local_open_without_restart(tmp_path: Path) -> None:
    ws = _workspace(local_open=True, tunnel_mode="none")
    sevn_json = tmp_path / "sevn.json"
    with _client(tmp_path, workspace=ws) as client:
        doc = json.loads(sevn_json.read_text(encoding="utf-8"))
        doc["infrastructure"] = {"tunnel": {"mode": "cloudflare", "hostname": "bot.example.com"}}
        sevn_json.write_text(json.dumps(doc), encoding="utf-8")
        assert client.get("/api/v1/sessions?limit=1").status_code == 401
        status = client.get("/api/v1/auth/status")
        body = status.json()
        assert body["tunnel_active"] is True
        assert body["local_open"] is False
        assert body["auth_required"] is True


def test_disk_tunnel_mode_none_overrides_memory_tunnel(tmp_path: Path) -> None:
    ws = _workspace(local_open=True, tunnel_mode="cloudflare")
    sevn_json = tmp_path / "sevn.json"
    with _client(tmp_path, workspace=ws) as client:
        doc = json.loads(sevn_json.read_text(encoding="utf-8"))
        doc["infrastructure"] = {"tunnel": {"mode": "none"}}
        sevn_json.write_text(json.dumps(doc), encoding="utf-8")
        status = client.get("/api/v1/auth/status")
        assert status.json()["tunnel_active"] is False
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        with (
            patch("sevn.ui.dashboard.api.ops.probe_secrets_backend") as secrets_probe,
            patch("sevn.ui.dashboard.api.ops.probe_llm_reachability") as llm_probe,
        ):
            from sevn.onboarding.live_validate import ValidationCheck

            secrets_probe.return_value = ValidationCheck("secrets", True, "info", "ok")
            llm_probe.return_value = ValidationCheck("llm", True, "info", "ok")
            tunnels = client.get("/api/v1/tunnels/status")
        assert tunnels.status_code == 200
        body = tunnels.json()
        assert body["tunnel_mode"] == "none"
        assert body["tunnel_active"] is False


def test_local_open_false_requires_login_on_loopback(tmp_path: Path) -> None:
    ws = _workspace(local_open=False)
    with _client(tmp_path, workspace=ws) as client:
        assert client.get("/api/v1/sessions?limit=1").status_code == 401
        login = client.post("/api/v1/auth/login", json={"password": "pw"})
        assert login.status_code == 200
        assert client.get("/api/v1/sessions?limit=1").status_code == 200


def test_system_logging_put_without_csrf_on_loopback(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.put(
            "/api/v1/system/logging",
            json={"retention_days": 10, "archive_mode": "copy"},
        )
        assert resp.status_code == 200
        assert resp.json()["retention_days"] == 10


def test_local_open_effective_unit() -> None:
    ws = _workspace()
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 1),
    }
    from starlette.requests import Request

    req = Request(scope)
    assert local_open_effective(ws, req) is True
    scope_remote = {**scope, "client": ("203.0.113.1", 1)}
    assert local_open_effective(ws, Request(scope_remote)) is False
