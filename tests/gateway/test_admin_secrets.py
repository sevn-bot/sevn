"""Gateway admin secrets API (`specs/23-cli.md` §8)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.http_server import create_app
from sevn.secrets.fingerprint import fingerprint_sha256_hex
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_TOKEN = "gw-admin-test"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Gateway TestClient with admin secrets routes and master key."""
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "cc" * 32)
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", _TOKEN)
    ws = tmp_path / "workspace"
    ws.mkdir()
    sevn_json = ws / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "queue_mode": "cancel",
                    "token": _TOKEN,
                },
                "secrets_backend": {
                    "chain": [
                        {
                            "type": "encrypted_file",
                            "path": ".sevn/secrets/store.enc",
                            "key_source": "master_key",
                        }
                    ],
                },
            },
        ),
        encoding="utf-8",
    )
    cfg = parse_workspace_config(json.loads(sevn_json.read_text(encoding="utf-8")))
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    app = create_app(
        workspace=cfg,
        layout=layout,
        sqlite_connection_factory=factory,
        process_settings=ProcessSettings(gateway_token=_TOKEN),
    )
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def test_admin_secrets_list_put_delete(client: TestClient) -> None:
    """``/api/v1/admin/secrets`` round-trip requires gateway bearer auth."""
    unauth = client.get("/api/v1/admin/secrets")
    assert unauth.status_code == 401

    headers = {"Authorization": f"Bearer {_TOKEN}"}
    assert client.get("/api/v1/admin/secrets", headers=headers).json() == {"entries": []}

    put = client.put(
        "/api/v1/admin/secrets/demo.key",
        headers=headers,
        json={"plaintext": "secret-value"},
    )
    assert put.status_code == 200
    fp = fingerprint_sha256_hex("secret-value")
    assert put.json()["fingerprint_sha256_hex"] == fp

    listed = client.get("/api/v1/admin/secrets", headers=headers).json()
    assert listed["entries"] == [{"alias": "demo.key", "fingerprint_sha256_hex": fp}]

    bad = client.request(
        "DELETE",
        "/api/v1/admin/secrets/demo.key",
        headers=headers,
        json={"confirm_alias": "demo.key", "confirm_fingerprint": "dead"},
    )
    assert bad.status_code == 400

    deleted = client.request(
        "DELETE",
        "/api/v1/admin/secrets/demo.key",
        headers=headers,
        json={"confirm_alias": "demo.key", "confirm_fingerprint": fp},
    )
    assert deleted.status_code == 200
    assert client.get("/api/v1/admin/secrets", headers=headers).json() == {"entries": []}
