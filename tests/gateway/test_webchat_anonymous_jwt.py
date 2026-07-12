"""Anonymous ``webchat.public`` JWT edge cases (`specs/17-gateway.md` §11, `specs/19-channel-webui.md`)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    ChannelsWorkspaceSectionConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WebChatChannelConfig,
    WorkspaceConfig,
)
from sevn.gateway.auth import mint_webchat_jwt, verify_webchat_jwt
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_SECRET = "anon-test-secret"


def _client(tmp_path: Path, *, public: bool) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    ch = ChannelsWorkspaceSectionConfig(
        webchat=WebChatChannelConfig(jwt_secret=_SECRET, public=public),
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels=ch,
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
    return TestClient(app, raise_server_exceptions=True)


def test_public_token_mints_anon_sub_prefix(tmp_path: Path) -> None:
    with _client(tmp_path, public=True) as client:
        resp = client.post("/api/webchat/token", json={})
        assert resp.status_code == 200
        body = resp.json()
        token = body["access_token"]
        claims = verify_webchat_jwt(secret=_SECRET, token=token)
        assert claims is not None
        assert claims.sub.startswith("anon:")


def test_non_public_without_bearer_returns_401(tmp_path: Path) -> None:
    with _client(tmp_path, public=False) as client:
        resp = client.post("/api/webchat/token", json={})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "webchat_auth_required"


def test_non_public_spoofed_sub_without_bearer_returns_401(tmp_path: Path) -> None:
    with _client(tmp_path, public=False) as client:
        resp = client.post("/api/webchat/token", json={"sub": "owner"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "webchat_auth_required"


def test_public_ignores_client_sub_mints_anon(tmp_path: Path) -> None:
    with _client(tmp_path, public=True) as client:
        resp = client.post("/api/webchat/token", json={"sub": "owner"})
        assert resp.status_code == 200
        claims = verify_webchat_jwt(secret=_SECRET, token=resp.json()["access_token"])
        assert claims is not None
        assert claims.sub.startswith("anon:")
        assert claims.sub != "owner"


def test_expired_jwt_rejected(tmp_path: Path) -> None:
    token, _ = mint_webchat_jwt(secret=_SECRET, sub="anon:dead", ttl_seconds=1, now=100)
    assert verify_webchat_jwt(secret=_SECRET, token=token, now=200) is None


def test_wrong_audience_rejected(tmp_path: Path) -> None:
    token, _ = mint_webchat_jwt(secret=_SECRET, sub="owner", ttl_seconds=60, now=1000)
    parts = token.split(".")
    assert len(parts) == 3
    assert verify_webchat_jwt(secret="other-secret", token=token, now=1010) is None
