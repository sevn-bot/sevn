"""Mission Control secrets show/hide toggle API tests (MC E2E W4)."""

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

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


class _RecordingTraceSink(TraceSink):
    """Capture emitted trace rows for audit assertions."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


@contextmanager
def _client(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "cc" * 32)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "workspace_root": ".",
                "channels": {
                    "telegram": {
                        "enabled": True,
                        "bot_token": "${SECRET:k:telegram.bot_token}",
                    },
                },
                "gateway": {"token": "test-gw-token"},
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


def test_secrets_alias_reveal_returns_value_for_owner_with_csrf(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        headers = _headers(client)
        put = client.put(
            "/api/v1/secrets/store/entries/telegram.bot_token",
            headers=headers,
            json={"plaintext": "tg-secret-token"},
        )
        assert put.status_code == 200
        reveal = client.get(
            "/api/v1/secrets/aliases/telegram.bot_token/reveal",
            headers=headers,
        )
        assert reveal.status_code == 200
        body = reveal.json()
        assert body["alias"] == "telegram.bot_token"
        assert body["plaintext"] == "tg-secret-token"


def test_secrets_alias_reveal_requires_csrf(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        _headers(client)
        resp = client.get("/api/v1/secrets/aliases/telegram.bot_token/reveal")
        assert resp.status_code == 403


def test_secrets_alias_reveal_unknown_alias_404(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        headers = _headers(client)
        resp = client.get(
            "/api/v1/secrets/aliases/not.in.config/reveal",
            headers=headers,
        )
        assert resp.status_code == 404


def test_secrets_alias_reveal_emits_audit(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        sink = _RecordingTraceSink()
        client.app.state.gateway_trace = sink
        headers = _headers(client)
        client.put(
            "/api/v1/secrets/store/entries/telegram.bot_token",
            headers=headers,
            json={"plaintext": "tg-secret-token"},
        )
        reveal = client.get(
            "/api/v1/secrets/aliases/telegram.bot_token/reveal",
            headers=headers,
        )
        assert reveal.status_code == 200
        kinds = [event.kind for event in sink.events]
        assert "mission.secrets.read" in kinds
        read_events = [event for event in sink.events if event.kind == "mission.secrets.read"]
        assert read_events[-1].attrs.get("alias") == "telegram.bot_token"


def test_secrets_aliases_list_still_redacted(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        headers = _headers(client)
        client.put(
            "/api/v1/secrets/store/entries/telegram.bot_token",
            headers=headers,
            json={"plaintext": "tg-secret-token"},
        )
        resp = client.get("/api/v1/secrets/aliases")
        assert resp.status_code == 200
        body = resp.json()
        assert body["aliases"]
        assert all(row["present"] == "<redacted>" for row in body["aliases"])
        assert "tg-secret-token" not in resp.text
