"""Dashboard spec-kit REST API (`plan/bot-evolution-wave-plan.md` EV-G3)."""

from __future__ import annotations

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
from sevn.evolution import spec_kit
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
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


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_constitution_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        get_resp = client.get("/api/v1/spec-kit/constitution")
        assert get_resp.status_code == 200
        assert "text" in get_resp.json()
        put_resp = client.put(
            "/api/v1/spec-kit/constitution",
            json={"text": "# test constitution\n"},
            headers=_csrf_headers(client),
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["text"] == "# test constitution\n"
        tpl = client.get("/api/v1/spec-kit/constitution/template")
        assert tpl.status_code == 200
        assert len(tpl.json()["text"]) > 0


def test_options_put_and_runs(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        opts = client.get("/api/v1/spec-kit/options")
        assert opts.status_code == 200
        assert opts.json()["spec_kit_enabled"] is True
        put = client.put(
            "/api/v1/spec-kit/options",
            json={"dry_run_default": True, "my_sevn_bugs_use_spec_kit": True},
            headers=_csrf_headers(client),
        )
        assert put.status_code == 200
        assert put.json()["dry_run_default"] is True
        assert put.json()["my_sevn_bugs_use_spec_kit"] is True
        layout = client.app.state.layout
        spec_kit.run_specify_allowlisted(
            "plan",
            [],
            tmp_path,
            owner_principal="owner",
            ws=client.app.state.workspace,
            layout=layout,
            dry_run=True,
        )
        runs = client.get("/api/v1/spec-kit/runs?limit=10")
        assert runs.status_code == 200
        items = runs.json()["items"]
        assert len(items) >= 1
        assert items[0]["command"] == "plan"


def test_test_invoke_rejects_shell(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.post(
            "/api/v1/spec-kit/test-invoke",
            json={"command": "plan", "argv": ["sh", "-c", "echo"]},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 400
