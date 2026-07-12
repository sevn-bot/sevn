"""GitHub webhook signature vectors (`specs/30-non-interactive-triggers.md` §2.3)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TriggersWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_SECRET = b"gh-test-secret"


def _github_signature(body: bytes) -> str:
    digest = hmac.new(_SECRET, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_client(tmp_path: Path, *, triggers: TriggersWorkspaceConfig) -> TestClient:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        triggers=triggers,
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn_local = sqlite3.connect(":memory:", check_same_thread=False)
        conn_local.execute("PRAGMA journal_mode=WAL")
        conn_local.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn_local)
        return conn_local

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    return TestClient(app, raise_server_exceptions=True)


def test_github_webhook_202_signed(tmp_path: Path) -> None:
    triggers = TriggersWorkspaceConfig(
        webhooks={
            "github": {"secret_b64": base64.b64encode(_SECRET).decode("ascii")},
        },
    )
    body = json.dumps({"action": "ping"}).encode("utf-8")
    with _make_client(tmp_path, triggers=triggers) as client:
        client.get("/health")
        r = client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": _github_signature(body),
                "X-GitHub-Delivery": "dev-delivery-1",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 202
    assert r.json()["correlation_id"]


def test_github_webhook_dedupe_duplicate(tmp_path: Path) -> None:
    triggers = TriggersWorkspaceConfig(
        webhooks={
            "github": {"secret_b64": base64.b64encode(_SECRET).decode("ascii")},
        },
    )
    body = json.dumps({"action": "opened"}).encode("utf-8")
    hdrs = {
        "X-Hub-Signature-256": _github_signature(body),
        "X-GitHub-Delivery": "dup-delivery-2",
        "Content-Type": "application/json",
    }
    with _make_client(tmp_path, triggers=triggers) as client:
        client.get("/health")
        r1 = client.post("/webhook/github", content=body, headers=hdrs)
        r2 = client.post("/webhook/github", content=body, headers=hdrs)
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r2.json().get("dedupe") == "duplicate"


def test_github_webhook_401_bad_sig(tmp_path: Path) -> None:
    triggers = TriggersWorkspaceConfig(
        webhooks={
            "github": {"secret_b64": base64.b64encode(_SECRET).decode("ascii")},
        },
    )
    body = json.dumps({"zen": "pong"}).encode("utf-8")
    with _make_client(tmp_path, triggers=triggers) as client:
        client.get("/health")
        r = client.post(
            "/webhook/github",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=deadbeef",
                "X-GitHub-Delivery": "bad-sig-1",
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 401
