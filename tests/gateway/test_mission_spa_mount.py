"""Mission Control SPA static mount (`plan/sevn-recovery-wave-plan.md` Wave C3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import _mission_control_mount_path, create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def _app_client(tmp_path: Path) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)

    def factory() -> sqlite3.Connection:
        conn_local = sqlite3.connect(":memory:", check_same_thread=False)
        conn_local.execute("PRAGMA journal_mode=WAL")
        conn_local.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn_local)
        return conn_local

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=factory,
    )
    return TestClient(app, raise_server_exceptions=True)


@pytest.mark.parametrize(
    ("env_val", "expected"),
    [
        ("", "/mission"),
        ("/mission", "/mission"),
        ("mission", "/mission"),
        ("/custom-mc", "/custom-mc"),
        ("custom-mc", "/custom-mc"),
        ("/custom-mc/", "/custom-mc"),
    ],
)
def test_mission_control_mount_path(
    monkeypatch: pytest.MonkeyPatch,
    env_val: str,
    expected: str,
) -> None:
    if env_val:
        monkeypatch.setenv("MISSION_CONTROL_MOUNT_PATH", env_val)
    else:
        monkeypatch.delenv("MISSION_CONTROL_MOUNT_PATH", raising=False)
    assert _mission_control_mount_path() == expected


def test_mission_index_html_returns_200(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        response = client.get("/mission/index.html")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "<title>sevn.bot Mission Control</title>" in response.text
        assert "PyClaww" not in response.text


def test_mission_app_js_returns_200(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        response = client.get("/mission/app.js")
        assert response.status_code == 200
        assert "javascript" in response.headers.get("content-type", "")


def test_mission_style_logos_served(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        for path in (
            "/style/logos/logo-primary.svg",
            "/style/logos/logo-dark-bg.svg",
        ):
            response = client.get(path)
            assert response.status_code == 200, path
            assert "svg" in response.headers.get("content-type", ""), path


def test_mission_spa_deep_link_returns_shell(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        response = client.get("/mission/sessions/sess-demo/api-calls")
        assert response.status_code == 200
        assert "<title>sevn.bot Mission Control</title>" in response.text


def test_mission_spa_csp_header_is_sane(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        response = client.get("/mission/")
        assert response.status_code == 200
        csp = response.headers.get("content-security-policy", "")
        assert csp
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "connect-src" in csp
