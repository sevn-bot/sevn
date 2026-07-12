"""Page Agent intent API (`specs/24-dashboard.md`)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardPageAgentConfig,
    DashboardWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.ui.dashboard.services.auth import (
    DASHBOARD_CSRF_COOKIE_NAME,
    DASHBOARD_CSRF_HEADER,
)
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path, *, page_agent_enabled: bool) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            page_agent=DashboardPageAgentConfig(enabled=page_agent_enabled),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _csrf_headers(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = login.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_page_agent_disabled_returns_403(tmp_path: Path) -> None:
    with _client(tmp_path, page_agent_enabled=False) as client:
        r = client.post(
            "/api/v1/page-agent/intent",
            json={"intent": "summarize traces"},
            headers=_csrf_headers(client),
        )
    assert r.status_code == 403


def test_page_agent_accepts_intent_when_enabled(tmp_path: Path) -> None:
    with _client(tmp_path, page_agent_enabled=True) as client:
        r = client.post(
            "/api/v1/page-agent/intent",
            json={"intent": "summarize traces"},
            headers=_csrf_headers(client),
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["intent"] == "summarize traces"
