"""Mission Control exposes ``version_id`` (plan D4 / W3 / #30)."""

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
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path, *, version_id: str | None = "mc-build-7") -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    doc: dict[str, object] = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    if version_id is not None:
        doc["version_id"] = version_id
    sevn_json.write_text(json.dumps(doc), encoding="utf-8")
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
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    assert client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)


def test_config_payload_includes_top_level_version_id(tmp_path: Path) -> None:
    """D4: system/config metadata JSON exposes ``version_id`` for System menu."""
    with _client(tmp_path, version_id="mc-build-7") as client:
        _login(client)
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("version_id") == "mc-build-7"
        # Still present in the document after W2 persist (orthogonal check).
        assert body["document"].get("version_id") == "mc-build-7"


def test_config_payload_version_id_when_missing_from_doc(tmp_path: Path) -> None:
    """When ``sevn.json`` lacks the key, payload still exposes a string (may be unknown)."""
    with _client(tmp_path, version_id=None) as client:
        _login(client)
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "version_id" in body
        assert isinstance(body["version_id"], str)
        assert body["version_id"].strip() != ""
