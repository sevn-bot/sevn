"""Mission Control MC-11 Surfaces tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    OnboardingWorkspaceSectionConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT, create_app
from sevn.gateway.menu import _mission_control_url
from sevn.gateway.onboarding_mount import mount_gateway_onboarding
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client(tmp_path: Path, *, web_ui_url: str | None = None) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    doc: dict[str, object] = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    if web_ui_url:
        doc["web_ui"] = {"url": web_ui_url}
    sevn_json.write_text(__import__("json").dumps(doc), encoding="utf-8")
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        **({"web_ui": {"url": web_ui_url}} if web_ui_url else {}),
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
    mount_gateway_onboarding(app, token="test-onboard-token")
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def test_mc11_wired_slugs_include_surfaces_tabs() -> None:
    expected = {"telegram-menu", "web-apps", "onboarding", "users-rbac"}
    assert expected <= WIRED_SLUGS


def test_surfaces_telegram_menu_snapshot(tmp_path: Path) -> None:
    with _client(tmp_path, web_ui_url="https://app.example/mission") as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/surfaces/telegram-menu")
        assert resp.status_code == 200
        body = resp.json()
        assert body["docs_url"].endswith("telegram-menu.html")
        assert body["section_count"] >= 1
        assert any(s["section_id"] == "session" for s in body["sections"])
        assert body["mission_control_url"].endswith("/mission/telegram-menu")


def test_surfaces_web_apps_lists_routes(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/surfaces/web-apps")
        assert resp.status_code == 200
        body = resp.json()
        paths = {r["path"] for r in body["routes"]}
        assert "/webapp/" in paths
        assert "/webapp/share" in paths
        assert "/webapp/feedback" in paths


def test_surfaces_onboarding_summary_with_log(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "onboard-2026.log").write_text("step=done\n", encoding="utf-8")
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "onboarding": {"applied_profile": "good_value"}, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
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
        onboarding=OnboardingWorkspaceSectionConfig(applied_profile="good_value"),
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
    mount_gateway_onboarding(app, token="test-onboard-token")
    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/surfaces/onboarding")
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied_profile"] == "good_value"
        assert body["last_log"]["filename"] == "onboard-2026.log"
        assert "onboard_token=test-onboard-token" in (body["gateway_wizard_url"] or "")


def test_surfaces_users_rbac_owner_model(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/surfaces/users-rbac")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model"] == "owner_only_v1"
        assert body["capabilities"]
        assert body["not_in_v1"]


def test_app_js_surfaces_panel_wiring() -> None:
    js = (MISSION_CONTROL_SPA_ROOT / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/surfaces/telegram-menu" in js
    assert "/api/v1/surfaces/web-apps" in js
    assert "/api/v1/surfaces/onboarding" in js
    assert "/api/v1/surfaces/users-rbac" in js
    assert "renderTelegramMenu" in js
    assert "renderWebApps" in js
    assert "renderOnboarding" in js
    assert "renderUsersRbac" in js


def test_mission_control_url_uses_path_routes() -> None:
    ws = WorkspaceConfig(
        schema_version=1,
        web_ui={"url": "https://app.example/"},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert (
        _mission_control_url(ws, fragment="integrations")
        == "https://app.example/mission/tunnels-infra"
    )
    assert _mission_control_url(ws, fragment="traces") == "https://app.example/mission/traces"
