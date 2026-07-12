"""Mission Control secrets store API tests (MC W1 §2b)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "cc" * 32)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "workspace_root": ".",
                "secrets_backend": {
                    "chain": [
                        {
                            "type": "encrypted_file",
                            "path": ".sevn/secrets/store.enc",
                            "key_source": "master_key",
                        }
                    ],
                },
                "gateway": {"token": "test-gw-token"},
            },
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=2,
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
        secrets_backend={
            "chain": [
                {
                    "type": "encrypted_file",
                    "path": ".sevn/secrets/store.enc",
                    "key_source": "master_key",
                }
            ],
        },
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


def test_secrets_store_put_reveal_roundtrip(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        headers = _headers(client)
        put = client.put(
            "/api/v1/secrets/store/entries/demo.key",
            headers=headers,
            json={"plaintext": "secret-value"},
        )
        assert put.status_code == 200
        fp = fingerprint_sha256_hex("secret-value")
        reveal = client.get("/api/v1/secrets/store/entries/demo.key")
        assert reveal.status_code == 200
        assert reveal.json()["plaintext"] == "secret-value"
        blocked = client.put(
            "/api/v1/secrets/store/entries/demo.key",
            headers=headers,
            json={"plaintext": "other"},
        )
        assert blocked.status_code == 400
        ok = client.put(
            "/api/v1/secrets/store/entries/demo.key",
            headers=headers,
            json={"plaintext": "other", "confirm_fingerprint": fp},
        )
        assert ok.status_code == 200


def test_secrets_store_delete_requires_confirm(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        headers = _headers(client)
        client.put(
            "/api/v1/secrets/store/entries/demo.key",
            headers=headers,
            json={"plaintext": "secret-value"},
        )
        fp = fingerprint_sha256_hex("secret-value")
        deleted = client.request(
            "DELETE",
            "/api/v1/secrets/store/entries/demo.key",
            headers=headers,
            json={"confirm_alias": "demo.key", "confirm_fingerprint": fp},
        )
        assert deleted.status_code == 200


def test_secrets_store_unauthenticated(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        assert (
            client.get(
                "/api/v1/secrets/store",
                headers={"X-Forwarded-For": "203.0.113.1"},
            ).status_code
            == 401
        )


def test_secrets_store_missing_csrf(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        _headers(client)
        resp = client.put(
            "/api/v1/secrets/store/entries/demo.key",
            json={"plaintext": "x"},
        )
        assert resp.status_code == 403
