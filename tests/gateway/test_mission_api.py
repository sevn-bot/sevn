"""Deprecated Mission Control recovery API (`specs/24-dashboard.md` MC-14)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    VoiceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_TOKEN = "mission-gw-token"
_DEPRECATED = "Deprecated recovery routes; use /api/v1/* dashboard routes instead (MC-14)."


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Gateway TestClient with deprecated mission routes."""
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", _TOKEN)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        voice=VoiceConfig(
            stt_providers=["whisper_cpp"],
            tts_providers=["edge_tts"],
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

    app = create_app(
        workspace=cfg,
        layout=layout,
        sqlite_connection_factory=factory,
        process_settings=ProcessSettings(gateway_token=_TOKEN),
    )
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client


def test_mission_sessions_returns_410(client: TestClient) -> None:
    client.get("/health")
    resp = client.get("/api/v1/mission/sessions")
    assert resp.status_code == 410
    assert resp.json()["detail"] == _DEPRECATED


def test_mission_session_detail_returns_410(client: TestClient) -> None:
    client.get("/health")
    resp = client.get("/api/v1/mission/sessions/sess-m1")
    assert resp.status_code == 410
    assert resp.json()["detail"] == _DEPRECATED


def test_mission_providers_health_returns_410(client: TestClient) -> None:
    client.get("/health")
    resp = client.get("/api/v1/mission/providers/health")
    assert resp.status_code == 410
    assert resp.json()["detail"] == _DEPRECATED


def test_mission_activity_websocket_rejects(client: TestClient) -> None:
    client.get("/health")
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(f"/api/v1/mission/activity?token={_TOKEN}") as ws,
    ):
        ws.receive_json()
