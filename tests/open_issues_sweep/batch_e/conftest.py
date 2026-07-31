"""Shared fixtures for open-issues sweep Batch E (W23 — security & policy)."""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.config.sections.channels import ChannelsWorkspaceSectionConfig, TelegramChannelConfig
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    TriggersWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

# W24 will expose ``DEFAULT_MAX_INGRESS_BODY_BYTES`` in ``sevn.config.defaults``.
EXPECTED_MAX_INGRESS_BODY_BYTES: int = 1_048_576
OVERSIZED_BODY_BYTES: bytes = b"x" * (EXPECTED_MAX_INGRESS_BODY_BYTES + 1)

_GITHUB_SECRET = b"batch-e-gh-secret"
_GATEWAY_TOKEN = "batch-e-gw-token"
_TELEGRAM_WEBHOOK_SECRET = "batch-e-tg-secret"


@dataclass(frozen=True)
class IngressPostTarget:
    """One HTTP POST ingress surface for body-cap parametrization (W23.1 → W24)."""

    route_id: str
    path: str
    headers: dict[str, str]
    content_type: str = "application/octet-stream"


def oversized_json_body(*, pad_bytes: int | None = None) -> bytes:
    """Return a JSON object whose raw body exceeds the ingress cap."""
    extra = pad_bytes if pad_bytes is not None else EXPECTED_MAX_INGRESS_BODY_BYTES + 1
    return json.dumps({"pad": "x" * extra}).encode("utf-8")


def github_signature(body: bytes, *, secret: bytes = _GITHUB_SECRET) -> str:
    """Build a valid GitHub ``X-Hub-Signature-256`` header for ``body``."""
    import hashlib
    import hmac

    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@contextmanager
def gateway_test_client(
    tmp_path: Path,
    *,
    triggers: TriggersWorkspaceConfig | None = None,
    dashboard_enabled: bool = False,
    telegram_webhook_secret: str | None = _TELEGRAM_WEBHOOK_SECRET,
) -> Iterator[TestClient]:
    """Minimal gateway ``TestClient`` with migrated SQLite and webhook triggers."""
    sevn_json = tmp_path / "sevn.json"
    payload: dict[str, object] = {
        "schema_version": 2,
        "workspace_root": ".",
        "gateway": {"token": _GATEWAY_TOKEN},
    }
    if telegram_webhook_secret:
        payload["channels"] = {
            "telegram": {
                "webhook_secret": telegram_webhook_secret,
            },
        }
    sevn_json.write_text(json.dumps(payload), encoding="utf-8")

    channels = None
    if telegram_webhook_secret:
        channels = ChannelsWorkspaceSectionConfig(
            telegram=TelegramChannelConfig(webhook_secret=telegram_webhook_secret),
        )
    cfg = WorkspaceConfig(
        schema_version=2,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": _GATEWAY_TOKEN},
        triggers=triggers,
        channels=channels,
        dashboard=(
            DashboardWorkspaceConfig(
                enabled=True,
                login_password="pw",
                jwt_secret="dashboard-secret",
                local_open=False,
            )
            if dashboard_enabled
            else None
        ),
    )

    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    conn_holder: dict[str, sqlite3.Connection] = {}

    def factory() -> sqlite3.Connection:
        if "conn" not in conn_holder:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.execute("PRAGMA foreign_keys=ON")
            apply_migrations(conn)
            conn_holder["conn"] = conn
        return conn_holder["conn"]

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/health")
        yield client


def ingress_post_targets(*, github_configured: bool = True) -> tuple[IngressPostTarget, ...]:
    """Return parametrized POST ingress paths named in W24.1."""
    auth = {"Authorization": f"Bearer {_GATEWAY_TOKEN}"}
    tg_hdr = {"X-Telegram-Bot-Api-Secret-Token": _TELEGRAM_WEBHOOK_SECRET}
    targets: list[IngressPostTarget] = [
        IngressPostTarget("webhook_telegram", "/webhook/telegram", tg_hdr),
        IngressPostTarget("webhook_channel", "/webhook/discord", auth),
        IngressPostTarget(
            "triggers_api_run",
            "/api/v1/run",
            {**auth, "Content-Type": "application/json"},
            content_type="application/json",
        ),
        IngressPostTarget(
            "openai_chat_completions",
            "/v1/chat/completions",
            {**auth, "Content-Type": "application/json"},
            content_type="application/json",
        ),
        IngressPostTarget(
            "dashboard_auth_login",
            "/api/v1/auth/login",
            {"Content-Type": "application/json"},
            content_type="application/json",
        ),
        IngressPostTarget(
            "onboarding_validate_field",
            "/onboarding/api/validate-field",
            {"Content-Type": "application/json"},
            content_type="application/json",
        ),
    ]
    if github_configured:
        body = json.dumps({"action": "ping"}).encode("utf-8")
        targets.insert(
            1,
            IngressPostTarget(
                "webhook_github_signed",
                "/webhook/github",
                {
                    "X-Hub-Signature-256": github_signature(body),
                    "X-GitHub-Delivery": "batch-e-oversize-1",
                    "Content-Type": "application/json",
                },
                content_type="application/json",
            ),
        )
    return tuple(targets)


@pytest.fixture
def batch_e_tmp_path(tmp_path: Path) -> Path:
    """Isolated workspace directory for Batch E gateway tests."""
    return tmp_path


@pytest.fixture
def make_gateway_client() -> Callable[..., Iterator[TestClient]]:
    """Factory fixture wrapping :func:`gateway_test_client`."""

    @contextmanager
    def _factory(
        tmp_path: Path,
        *,
        triggers: TriggersWorkspaceConfig | None = None,
        dashboard_enabled: bool = False,
    ) -> Iterator[TestClient]:
        with gateway_test_client(
            tmp_path,
            triggers=triggers,
            dashboard_enabled=dashboard_enabled,
        ) as client:
            yield client

    return _factory


@pytest.fixture
def github_triggers_config() -> TriggersWorkspaceConfig:
    """Triggers block with GitHub webhook secret for signed ingress tests."""
    return TriggersWorkspaceConfig(
        webhooks={
            "github": {"secret_b64": base64.b64encode(_GITHUB_SECRET).decode("ascii")},
        },
    )
