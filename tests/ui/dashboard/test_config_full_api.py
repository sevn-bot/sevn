"""Unified Config tab API tests (MC W2)."""

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

_BASE_DOC: dict[str, object] = {
    "schema_version": 1,
    "workspace_root": ".",
    "dashboard": {
        "enabled": True,
        "login_password": "pw",
        "jwt_secret": "dashboard-secret-value",
    },
    "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}", "port": 3001},
}


@contextmanager
def _client(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(json.dumps(_BASE_DOC), encoding="utf-8")
    cfg = WorkspaceConfig.model_validate(_BASE_DOC)
    if cfg.dashboard is not None:
        cfg = cfg.model_copy(
            update={"dashboard": cfg.dashboard.model_copy(update={"local_open": False})}
        )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, sevn_json


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def _on_disk(sevn_json: Path) -> dict:
    return json.loads(sevn_json.read_text(encoding="utf-8"))


def test_config_full_get_redacts_secrets(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        _login(client)
        resp = client.get("/api/v1/config/full")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "schema" in body
        assert body["config"]["gateway"]["token"] in {"<redacted>", "<redacted-secret-ref>"}
        assert body["config"]["dashboard"]["jwt_secret"] == "<redacted>"
        assert body["schema_version"] == 1


def test_config_full_round_trip_change(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        headers = _login(client)
        got = client.get("/api/v1/config/full").json()
        doc = dict(got["config"])
        doc["gateway"] = dict(doc["gateway"])
        doc["gateway"]["port"] = 3002
        put = client.put("/api/v1/config/full", headers=headers, json=doc)
        assert put.status_code == 200, put.text
        assert _on_disk(sevn_json)["gateway"]["port"] == 3002
        again = client.get("/api/v1/config/full").json()
        assert again["config"]["gateway"]["port"] == 3002


def test_config_full_invalid_put_returns_field_errors_and_no_write(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        headers = _login(client)
        got = client.get("/api/v1/config/full").json()
        doc = dict(got["config"])
        doc["gateway"] = {"token": ""}
        before = sevn_json.read_text(encoding="utf-8")
        put = client.put("/api/v1/config/full", headers=headers, json=doc)
        assert put.status_code == 422, put.text
        errors = put.json()["errors"]
        assert isinstance(errors, list)
        assert errors
        assert sevn_json.read_text(encoding="utf-8") == before


def test_config_full_redacted_secret_not_clobbered(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        headers = _login(client)
        got = client.get("/api/v1/config/full").json()
        doc = dict(got["config"])
        doc["gateway"] = dict(doc["gateway"])
        doc["gateway"]["port"] = 3003
        put = client.put("/api/v1/config/full", headers=headers, json=doc)
        assert put.status_code == 200, put.text
        disk = _on_disk(sevn_json)
        assert disk["gateway"]["token"] == "${SECRET:keychain:sevn.gateway.token}"
        assert disk["gateway"]["port"] == 3003
        assert disk["dashboard"]["jwt_secret"] == "dashboard-secret-value"


def test_config_full_dry_run_validate_does_not_write(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, sevn_json):
        headers = _login(client)
        got = client.get("/api/v1/config/full").json()
        doc = dict(got["config"])
        doc["gateway"] = dict(doc["gateway"])
        doc["gateway"]["port"] = 3004
        before = sevn_json.read_text(encoding="utf-8")
        put = client.put(
            "/api/v1/config/full?dry_run=1",
            headers=headers,
            json=doc,
        )
        assert put.status_code == 200, put.text
        assert put.json()["dry_run"] is True
        assert sevn_json.read_text(encoding="utf-8") == before
        post = client.post("/api/v1/config/full/validate", headers=headers, json=doc)
        assert post.status_code == 200, post.text


def test_config_full_put_requires_csrf(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        _login(client)
        got = client.get("/api/v1/config/full").json()
        resp = client.put("/api/v1/config/full", json=got["config"])
        assert resp.status_code in (401, 403)


def test_config_full_get_requires_owner_session(tmp_path: Path) -> None:
    with _client(tmp_path) as (client, _sevn_json):
        resp = client.get("/api/v1/config/full")
        assert resp.status_code in (401, 403)
