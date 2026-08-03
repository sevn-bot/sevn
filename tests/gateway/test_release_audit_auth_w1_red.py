"""Batch A W1 RED — fail-closed auth surfaces (#138; green after W3).

Contracts: OpenAI compat 503 when unconfigured; triggers 401; GUI proxy 401;
``POST /login`` rejects when gateway token unset.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI
from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.api.gui_proxy import _verify_gui_gateway_access, mount_gui_proxy
from sevn.gateway.api.openai_compat_api import build_openai_compat_router
from sevn.gateway.auth import verify_login_gateway_token
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.triggers.auth import triggers_api_auth_required, verify_triggers_api_bearer
from sevn.workspace.layout import WorkspaceLayout

_GATEWAY_TOKEN = "required-token-at-least-32-characters-long"


def _openai_compat_client(*, gateway_token: str | None) -> TestClient:
    app = FastAPI()
    router = build_openai_compat_router()
    app.include_router(router)
    app.state.resolved_gateway_token = gateway_token
    app.state.gateway_router = None
    app.state.sqlite_conn = None
    app.state.gateway_sessions = None
    return TestClient(app)


def test_openai_compat_chat_completions_503_when_token_unconfigured() -> None:
    client = _openai_compat_client(gateway_token=None)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "sevn-agent", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 503
    assert resp.json().get("detail") == "auth_not_configured"


def test_triggers_api_auth_required_when_unconfigured() -> None:
    assert triggers_api_auth_required(gateway_token=None, webchat_jwt_secret=None) is True


def test_triggers_api_rejects_missing_bearer_when_unconfigured() -> None:
    assert (
        verify_triggers_api_bearer(
            authorization_header=None,
            gateway_token=None,
            webchat_jwt_secret=None,
        )
        is False
    )


def test_gui_proxy_rejects_when_token_unconfigured() -> None:
    assert (
        _verify_gui_gateway_access(
            configured=None,
            authorization_header=None,
            query_params={},
            cookies={},
        )
        is False
    )


def test_gui_http_route_401_when_token_unconfigured(monkeypatch) -> None:
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: None)
    client = TestClient(app)
    resp = client.get("/gui/vnc.html", follow_redirects=False)
    assert resp.status_code == 401


def test_login_rejects_when_gateway_token_unconfigured() -> None:
    assert verify_login_gateway_token(configured=None, submitted="any-token") is False
    assert verify_login_gateway_token(configured=None, submitted="") is False


def test_login_post_rejects_when_gateway_token_unconfigured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", '
        '"gateway": {"host": "127.0.0.1", "port": 3001, '
        '"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={
            "host": "127.0.0.1",
            "port": 3001,
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app) as client:
        resp = client.post("/login", json={"token": "operator-supplied"})
    assert resp.status_code == 401
