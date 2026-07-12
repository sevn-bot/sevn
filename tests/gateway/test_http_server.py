"""Tests for gateway HTTP surface (`specs/17-gateway.md` §9)."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.openui.store import OpenUIRecord
from sevn.ui.openui.tokens import sign_token
from sevn.workspace.layout import WorkspaceLayout


def _app_client(tmp_path: Path, *, cfg: WorkspaceConfig | None = None) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = cfg or WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)

    def factory() -> sqlite3.Connection:
        conn_local = sqlite3.connect(":memory:", check_same_thread=False)
        conn_local.execute("PRAGMA journal_mode=WAL")
        conn_local.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn_local)
        return conn_local

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=factory,
    )
    return TestClient(app, raise_server_exceptions=True)


def test_health_and_ready(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        r2 = client.get("/ready")
        assert r2.status_code == 200
        assert r2.json().get("sqlite") is True


def test_onboarding_mounted_on_gateway(tmp_path: Path) -> None:
    """Gateway mounts onboarding wizard at ``/onboarding`` (`specs/22-onboarding.md` §10.1)."""

    with _app_client(tmp_path) as client:
        r = client.get("/onboarding/healthz")
        assert r.status_code == 200
        assert r.text.strip() == "ok"
        r2 = client.get("/onboarding/")
        assert r2.status_code == 401


def test_mission_spa_serves(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        r = client.get("/mission/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


def test_gateway_lifespan_prunes_stale_tts_files(tmp_path: Path) -> None:
    """Gateway boot prunes ``out/audio`` TTS files older than ``voice.tts_temp_ttl_days``."""

    tts_dir = tmp_path / "out" / "audio"
    tts_dir.mkdir(parents=True)
    stale = tts_dir / "stale.ogg"
    stale.write_bytes(b"x")
    old = time.time() - 10 * 86400
    os.utime(stale, (old, old))
    with _app_client(tmp_path) as client:
        client.get("/health")
    assert not stale.exists()


def test_metrics_phase3_stub(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        body = client.get("/metrics").text
        assert "sevn_gateway_up" in body


def test_openui_get_unknown_token_returns_404(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        client.get("/health")
        r = client.get("/openui/not-a-valid-token")
        assert r.status_code == 404


def test_openui_callback_missing_query_token_returns_410(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        client.get("/health")
        r = client.post("/openui/callback", data="a=1")
        assert r.status_code == 410


def test_openui_get_and_callback_happy_path(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        client.get("/health")
        secret = str(client.app.state.openui_secret)
        store = client.app.state.openui_store
        conn = client.app.state.sqlite_conn
        sid = "sess-openui-1"
        conn.execute(
            """
            INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (sid, "webchat:owner", "webchat", "owner"),
        )
        conn.commit()
        record_id = "rec-openui-1"
        exp_ns = time.time_ns() + 3600 * 10**9
        rec = OpenUIRecord(
            record_id=record_id,
            workspace_id=".",
            session_id=sid,
            message_id="msg-1",
            channel="webchat",
            sanitised_html="<p>hello</p>",
            expires_at_ns=exp_ns,
            submit_consumed=False,
            fallback_text="fb",
        )
        store.put(rec)
        render_tok = sign_token(
            secret=secret,
            workspace_id=".",
            session_id=sid,
            message_id="msg-1",
            record_id=record_id,
            scope="render",
            exp_unix=int(time.time()) + 3600,
        )
        submit_tok = sign_token(
            secret=secret,
            workspace_id=".",
            session_id=sid,
            message_id="msg-1",
            record_id=record_id,
            scope="submit",
            exp_unix=int(time.time()) + 3600,
        )
        gr = client.get(f"/openui/{render_tok}")
        assert gr.status_code == 200
        assert "hello" in gr.text
        assert "Content-Security-Policy" in gr.headers
        pr = client.post(
            f"/openui/callback?token={submit_tok}",
            data="form_id=openui%3Aagent%3Ax%3Asubmit&choice=1",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert pr.status_code == 200
        pr2 = client.post(
            f"/openui/callback?token={submit_tok}",
            data="form_id=openui%3Aagent%3Ax%3Asubmit&choice=2",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert pr2.status_code == 409


def test_webhook_telegram_requires_secret_when_configured(tmp_path: Path) -> None:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        channels={"telegram": {"webhook_secret": "sekrit"}},
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    with _app_client(tmp_path, cfg=cfg) as client:
        payload = {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 42, "is_bot": False, "first_name": "T"},
                "chat": {"id": 42, "type": "private"},
                "text": "hello gateway",
            },
        }
        assert client.post("/webhook/telegram", json=payload).status_code == 401
        ok = client.post(
            "/webhook/telegram",
            json=payload,
            headers={"X-Telegram-Bot-Api-Secret-Token": "sekrit"},
        )
        assert ok.status_code == 200
        conn = client.app.state.sqlite_conn
        count = conn.execute(
            "SELECT COUNT(*) FROM gateway_messages WHERE kind = 'message'",
        ).fetchone()[0]
        assert int(count) >= 1


_GATEWAY_BEARER = "a" * 64


def test_login_post_rate_limited_after_budget_exhausted(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        for _ in range(5):
            resp = client.post("/login", json={"token": "wrong-token"})
            assert resp.status_code == 401
        limited = client.post("/login", json={"token": "wrong-token"})
        assert limited.status_code == 429
        assert limited.json()["detail"] == "rate_limited"


def test_login_post_success_within_budget(tmp_path: Path) -> None:
    with _app_client(tmp_path) as client:
        ok = client.post("/login", json={"token": _GATEWAY_BEARER})
        assert ok.status_code == 200
        assert ok.json()["ok"] is True
