"""Editable config tabs — PUT persistence to ``sevn.json`` (`specs/24-dashboard.md`).

Covers the six v1 read-only tabs promoted to editable: MCP Servers,
Tools & Permissions, Channels, Cron, Telegram Menu, and Web Apps.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout

_SEVN_JSON = {
    "schema_version": 1,
    "workspace_root": ".",
    "dashboard": {
        "enabled": True,
        "login_password": "pw",
        "jwt_secret": "dashboard-secret",
    },
    "channels": {
        "telegram": {
            "enabled": True,
            "reply_keyboard": {"enabled": True},
            "quick_actions": {"show_regen": True},
        },
    },
    "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
}


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(json.dumps(_SEVN_JSON), encoding="utf-8")
    cfg = WorkspaceConfig.model_validate(_SEVN_JSON)
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200, login.text
        yield client, sevn_json


def _on_disk(sevn_json: Path) -> dict:
    return json.loads(sevn_json.read_text(encoding="utf-8"))


# --- MCP Servers ---------------------------------------------------------


def test_mcp_servers_put_persists_enabled_list(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        servers = client.get("/api/v1/agent/mcp-servers").json()["servers"]
        ids = [row["server_id"] for row in servers]
        target = ids[:1]  # enable the first known server if any exist
        resp = client.put(
            "/api/v1/agent/mcp-servers",
            json={"mcp_enabled": target},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert _on_disk(sevn_json)["mcp_enabled"] == target
        assert resp.json()["mcp_enabled"] == target


def test_mcp_servers_put_rejects_unknown_server(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.put(
            "/api/v1/agent/mcp-servers",
            json={"mcp_enabled": ["definitely-not-a-real-server"]},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "unknown_server"


def test_mcp_servers_put_rejects_non_list(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.put(
            "/api/v1/agent/mcp-servers",
            json={"mcp_enabled": "nope"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 400


# --- Tools & Permissions -------------------------------------------------


def test_permissions_get_then_put_persists(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        initial = client.get("/api/v1/agent/permissions")
        assert initial.status_code == 200
        assert "permissions" in initial.json()
        resp = client.put(
            "/api/v1/agent/permissions",
            json={"permissions": {"default_template": "trusted"}, "tools": {"web_fetch": True}},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        disk = _on_disk(sevn_json)
        assert disk["permissions"] == {"default_template": "trusted"}
        assert disk["tools"] == {"web_fetch": True}
        assert resp.json()["permissions"] == {"default_template": "trusted"}


def test_permissions_put_requires_object(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.put(
            "/api/v1/agent/permissions",
            json={"permissions": "bad"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 400


# --- Channels ------------------------------------------------------------


def test_channels_config_put_persists_and_preserves_siblings(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        resp = client.put(
            "/api/v1/channels/config",
            json={"channels": {"telegram": {"enabled": False}, "webchat": {"public": True}}},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        disk = _on_disk(sevn_json)
        assert disk["channels"]["telegram"]["enabled"] is False
        assert disk["channels"]["webchat"]["public"] is True
        # deep-merge must not clobber the pre-existing reply_keyboard sibling.
        assert disk["channels"]["telegram"]["reply_keyboard"]["enabled"] is True


def test_channels_config_get_projects_toggles(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        body = client.get("/api/v1/channels/config").json()
        assert body["channels"]["telegram"]["enabled"] is True


# --- Cron ----------------------------------------------------------------


def test_cron_config_put_persists_paused(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        resp = client.put(
            "/api/v1/cron/config",
            json={"paused": True},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["triggers_paused"] is True
        assert _on_disk(sevn_json)["triggers"]["paused"] is True


def test_cron_config_put_requires_bool(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.put(
            "/api/v1/cron/config",
            json={"paused": "yes"},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 400


# --- Telegram Menu -------------------------------------------------------


def test_telegram_menu_put_persists_toggles(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        resp = client.put(
            "/api/v1/surfaces/telegram-menu",
            json={"telegram": {"reply_keyboard": {"enabled": False}, "show_routing": True}},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        editable = resp.json()["editable"]
        assert editable["reply_keyboard_enabled"] is False
        assert editable["show_routing"] is True
        disk = _on_disk(sevn_json)
        assert disk["channels"]["telegram"]["reply_keyboard"]["enabled"] is False
        # untouched sibling toggle preserved by deep-merge.
        assert disk["channels"]["telegram"]["quick_actions"]["show_regen"] is True


def test_telegram_menu_get_exposes_editable(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        body = client.get("/api/v1/surfaces/telegram-menu").json()
        assert body["editable"]["reply_keyboard_enabled"] is True


# --- Web Apps ------------------------------------------------------------


def test_web_apps_put_persists_webchat_settings(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        resp = client.put(
            "/api/v1/surfaces/web-apps",
            json={"webchat": {"public": True, "allowed_origins": ["https://example.test"]}},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        editable = resp.json()["editable"]
        assert editable["public"] is True
        assert editable["allowed_origins"] == ["https://example.test"]
        disk = _on_disk(sevn_json)
        assert disk["channels"]["webchat"]["public"] is True
        # telegram channel untouched by a webchat-only edit.
        assert disk["channels"]["telegram"]["enabled"] is True


def test_web_apps_put_requires_object(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.put(
            "/api/v1/surfaces/web-apps",
            json={"webchat": ["bad"]},
            headers=_csrf_headers(client),
        )
        assert resp.status_code == 400


# --- CSRF / auth guards ---------------------------------------------------


def test_editor_puts_require_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.put("/api/v1/cron/config", json={"paused": True})
        assert resp.status_code in (401, 403)
