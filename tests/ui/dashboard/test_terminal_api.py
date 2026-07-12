"""Tests for Mission Control sandbox web terminal (MC W8)."""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecuritySandboxSubConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.security.sandbox_runtime import SandboxDriver
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.services.sandbox_terminal import (
    SandboxTerminalSession,
    _subprocess_terminal_env,
)
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def _dashboard_cfg(*, local_open: bool = True) -> WorkspaceConfig:
    security = SecurityWorkspaceConfig(
        scanner=SecurityScannerSubConfig(heuristic_only=True),
        sandbox=SecuritySandboxSubConfig(allow_subprocess_fallback=True),
    )
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=local_open,
        ),
        security=security,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@contextmanager
def _client(tmp_path: Path, *, local_open: bool = True) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = _dashboard_cfg(local_open=local_open)
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


def test_terminal_session_requires_auth(tmp_path: Path) -> None:
    with _client(tmp_path, local_open=False) as client:
        resp = client.post("/api/v1/terminal/session", json={})
        assert resp.status_code == 401


def test_terminal_session_requires_csrf(tmp_path: Path) -> None:
    with _client(tmp_path, local_open=False) as client:
        _login(client)
        resp = client.post("/api/v1/terminal/session", json={})
        assert resp.status_code == 403


def test_terminal_session_mints_upgrade_ticket(tmp_path: Path) -> None:
    with _client(tmp_path, local_open=True) as client:
        resp = client.post("/api/v1/terminal/session", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"]
        assert body["ws_path"] == "/ws/dashboard/terminal"
        assert body["max_lifetime_s"] > 0


def test_terminal_ws_rejects_missing_auth_when_not_local_open(tmp_path: Path) -> None:
    with _client(tmp_path, local_open=False) as client:
        _login(client)
        with client.websocket_connect("/ws/dashboard/terminal") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()


def test_terminal_ws_rejects_invalid_upgrade_ticket(tmp_path: Path) -> None:
    with _client(tmp_path, local_open=False) as client:
        _login(client)
        jwt = client.cookies.get("sevn_dashboard_session")
        csrf = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
        assert jwt is not None
        assert csrf is not None
        with client.websocket_connect("/ws/dashboard/terminal") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "type": "auth",
                        "token": jwt,
                        "csrf": csrf,
                        "session_id": "not-a-real-ticket",
                    },
                ),
            )
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()


def test_subprocess_terminal_env_excludes_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MY_API_KEY", "key")
    monkeypatch.setenv("MY_TOKEN", "tok")
    monkeypatch.setenv("MY_SECRET", "sec")
    env = _subprocess_terminal_env(home=tmp_path)
    assert "SEVN_SECRETS_PASSPHRASE" not in env
    assert not any(k.endswith(("_API_KEY", "_TOKEN", "_SECRET")) for k in env)
    assert env["TERM"] == "xterm-256color"
    assert "PATH" in env
    assert env["HOME"] == str(tmp_path)


def test_sandbox_terminal_self_preservation_blocks_line() -> None:
    session = SandboxTerminalSession(
        session_id="t",
        driver=SandboxDriver.subprocess,
        sandbox_id="sb",
        runtime=object(),  # type: ignore[arg-type]
        workspace_root=Path("."),
        max_lifetime_s=60.0,
        _master_fd=-1,
    )
    assert session.check_line_policy("pkill foo") is not None
    assert session.check_line_policy("echo ok") is None


def test_terminal_ws_local_open_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with (
        _client(tmp_path, local_open=True) as client,
        client.websocket_connect(
            "/ws/dashboard/terminal",
        ) as ws,
    ):
        ready = json.loads(ws.receive_text())
        assert ready["type"] == "ready"
        assert ready["driver"] in {"subprocess", "docker"}
        stdin = base64.b64encode(b"echo mc_w8_ok\n").decode("ascii")
        ws.send_text(json.dumps({"type": "stdin", "data": stdin}))
        saw_output = False
        for _ in range(40):
            frame = json.loads(ws.receive_text())
            if frame.get("type") == "stdout" and "mc_w8_ok" in base64.b64decode(
                frame["data"],
            ).decode("utf-8", errors="replace"):
                saw_output = True
                break
        assert saw_output
