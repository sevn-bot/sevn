"""Mission Control providers health API (`specs/24-dashboard.md` stubs Wave C)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    VoiceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.onboarding.live_validate import ValidationCheck
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
)
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}, '
        '"providers": {"tier_default": {"triager": "anthropic/claude-sonnet-4-6"}, '
        '"anthropic": {"api_key": "${SECRET:SEVN_SECRET_ANTHROPIC}"}}}',
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

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_providers_health_returns_live_rows(tmp_path: Path) -> None:
    secrets_check = ValidationCheck(
        check_id="secrets_backend",
        ok=True,
        severity="info",
        detail="sentinel _sevn_probe read ok",
    )
    llm_check = ValidationCheck(
        check_id="llm_reachability",
        ok=True,
        severity="info",
        detail="proxy ping ok model=anthropic/claude-sonnet-4-6",
    )

    with _client(tmp_path) as client:
        _ = _login(client)
        with (
            patch(
                "sevn.ui.dashboard.api.system.probe_secrets_backend",
                new=AsyncMock(return_value=secrets_check),
            ),
            patch(
                "sevn.ui.dashboard.api.system.credentials_status",
                new=AsyncMock(
                    return_value={
                        "present": {"SEVN_SECRET_ANTHROPIC": True},
                        "ready_for_handoff": True,
                        "keystore_locked": False,
                        "needs_passphrase": False,
                    }
                ),
            ),
            patch(
                "sevn.ui.dashboard.api.system.probe_llm_reachability",
                new=AsyncMock(return_value=llm_check),
            ),
            patch(
                "sevn.ui.dashboard.api.system.build_stt_backend",
            ) as stt_factory,
            patch(
                "sevn.ui.dashboard.api.system.build_tts_backend",
            ) as tts_factory,
        ):
            stt_backend = stt_factory.return_value
            stt_backend.is_available = AsyncMock(return_value=True)
            tts_backend = tts_factory.return_value
            tts_backend.is_available = AsyncMock(return_value=True)

            resp = client.get("/api/v1/providers/health")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["generated_at_ns"], int)
        rows = body["providers"]
        ids = [row["id"] for row in rows]
        assert "secrets_backend" in ids
        assert "credential.anthropic" in ids
        assert "llm_reachability" in ids
        assert "voice_stt.whisper_cpp" in ids
        assert "voice_tts.edge_tts" in ids
        llm_row = next(row for row in rows if row["id"] == "llm_reachability")
        assert llm_row["ok"] is True
        assert llm_row["severity"] == "info"


def test_providers_health_degraded_llm_probe(tmp_path: Path) -> None:
    secrets_check = ValidationCheck(
        check_id="secrets_backend",
        ok=True,
        severity="warn",
        detail="sentinel _sevn_probe not set (backend reachable)",
    )
    llm_check = ValidationCheck(
        check_id="llm_reachability",
        ok=False,
        severity="warn",
        detail="proxy ping timed out after 15s",
    )

    with _client(tmp_path) as client:
        _ = _login(client)
        with (
            patch(
                "sevn.ui.dashboard.api.system.probe_secrets_backend",
                new=AsyncMock(return_value=secrets_check),
            ),
            patch(
                "sevn.ui.dashboard.api.system.credentials_status",
                new=AsyncMock(
                    return_value={
                        "present": {"SEVN_SECRET_ANTHROPIC": True},
                        "ready_for_handoff": True,
                        "keystore_locked": False,
                        "needs_passphrase": False,
                    }
                ),
            ),
            patch(
                "sevn.ui.dashboard.api.system.probe_llm_reachability",
                new=AsyncMock(return_value=llm_check),
            ),
            patch("sevn.ui.dashboard.api.system.build_stt_backend") as stt_factory,
            patch("sevn.ui.dashboard.api.system.build_tts_backend") as tts_factory,
        ):
            stt_factory.return_value.is_available = AsyncMock(return_value=False)
            tts_factory.return_value.is_available = AsyncMock(return_value=False)

            resp = client.get("/api/v1/providers/health")

        assert resp.status_code == 200
        rows = resp.json()["providers"]
        llm_row = next(row for row in rows if row["id"] == "llm_reachability")
        assert llm_row["ok"] is False
        assert llm_row["severity"] == "warn"
        assert "timed out" in llm_row["detail"]
        stt_row = next(row for row in rows if row["id"] == "voice_stt.whisper_cpp")
        assert stt_row["ok"] is False


def test_providers_health_degraded_on_probe_exception(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _ = _login(client)
        with patch(
            "sevn.ui.dashboard.api.system._collect_providers_health",
            side_effect=RuntimeError("probe chain failed"),
        ):
            resp = client.get("/api/v1/providers/health")
        assert resp.status_code == 200
        rows = resp.json()["providers"]
        assert len(rows) == 1
        assert rows[0]["id"] == "health_probe"
        assert rows[0]["ok"] is False
        assert "probe chain failed" in rows[0]["detail"]
