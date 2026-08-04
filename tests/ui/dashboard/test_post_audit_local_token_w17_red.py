"""Post-audit Batch E W17 RED — dashboard local-open boot token (#169, D26).

Contracts (``about-sevn.bot/specs/24-dashboard.md``, ``specs/19-channel-webui.md``):
tokenless direct loopback is denied when local-open is effective; matching boot token
succeeds; wrong token is denied; ``dashboard.local_open_trust_address: true`` restores
tokenless loopback; CLI ``read_dashboard_local_token()`` URL append is accepted.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from click.testing import CliRunner as ClickCliRunner
from starlette.testclient import TestClient
from typer.main import get_command

from sevn.cli.app import app
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    GatewayConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import apply_tunnel_local_open_policy, local_open_effective
from sevn.ui.dashboard.services.local_token import DASHBOARD_LOCAL_TOKEN_QUERY
from sevn.workspace.layout import WorkspaceLayout


def _workspace(
    *,
    local_open: bool | None = True,
    local_open_trust_address: bool | None = None,
    login_password: str = "pw",
    tunnel_mode: str = "none",
    gateway_host: str = "127.0.0.1",
) -> WorkspaceConfig:
    dash_kwargs: dict[str, object] = {
        "enabled": True,
        "local_open": local_open,
        "login_password": login_password,
        "jwt_secret": "dashboard-secret",
    }
    if local_open_trust_address is not None:
        dash_kwargs["local_open_trust_address"] = local_open_trust_address
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway=GatewayConfig(
            host=gateway_host, port=3001, token="${SECRET:keychain:sevn.gateway.token}"
        ),
        dashboard=DashboardWorkspaceConfig(**dash_kwargs),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        infrastructure={"tunnel": {"mode": tunnel_mode}},
    )


@contextmanager
def _client(
    tmp_path: Path,
    *,
    workspace: WorkspaceConfig | None = None,
    sevn_home: Path | None = None,
    remote: bool = False,
) -> Iterator[TestClient]:
    home = sevn_home or tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = workspace or _workspace()
    apply_tunnel_local_open_policy(cfg)
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app_instance = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    client_host = ("203.0.113.1", 40000) if remote else ("127.0.0.1", 0)
    with TestClient(
        app_instance,
        client=client_host,
        raise_server_exceptions=True,
    ) as client:
        yield client


def _boot_local_token(client: TestClient) -> str:
    token = getattr(client.app.state, "dashboard_local_token", None)
    assert isinstance(token, str)
    assert token.strip()
    return token


@pytest.mark.xfail(
    reason="green after W18: tokenless loopback denied when local-open effective",
    strict=False,
)
def test_tokenless_loopback_denied_when_local_open_effective(tmp_path: Path) -> None:
    """W17.1 — no local token must not grant owner access on direct loopback."""
    with _client(tmp_path) as client:
        resp = client.get("/api/v1/sessions?limit=5")
        assert resp.status_code == 401


def test_loopback_with_boot_token_succeeds_wrong_token_denied(tmp_path: Path) -> None:
    """W17.2 — matching boot token succeeds; wrong token is denied."""
    with _client(tmp_path) as client:
        boot_token = _boot_local_token(client)

        ok = client.get(f"/api/v1/sessions?limit=5&{DASHBOARD_LOCAL_TOKEN_QUERY}={boot_token}")
        assert ok.status_code == 200
        assert ok.json() == {"items": [], "next_cursor": None, "has_more": False}

        bad = client.get(
            f"/api/v1/sessions?limit=5&{DASHBOARD_LOCAL_TOKEN_QUERY}=not-the-boot-token"
        )
        assert bad.status_code == 401


@pytest.mark.xfail(
    reason="green after W18: local_open_trust_address opt-in restores tokenless loopback",
    strict=False,
)
def test_tokenless_loopback_allowed_when_trust_address_opt_in(tmp_path: Path) -> None:
    """W17.3 — explicit ``local_open_trust_address: true`` allows tokenless loopback (D26)."""
    ws = _workspace(local_open=True, local_open_trust_address=True)
    with _client(tmp_path, workspace=ws) as client:
        resp = client.get("/api/v1/sessions?limit=5")
        assert resp.status_code == 200


def test_local_open_effective_wrong_boot_token_denied_unit() -> None:
    """W17.2 unit — verify path rejects a mismatched submitted token."""
    from starlette.applications import Starlette
    from starlette.requests import Request

    ws = _workspace()
    starlette_app = Starlette()
    starlette_app.state.dashboard_local_token = "expected-boot-token"

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "app": starlette_app,
        "query_string": b"local_token=wrong-token",
    }
    assert local_open_effective(ws, Request(scope)) is False


def test_dashboard_cli_local_token_url_accepted_by_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W17.5 — CLI token file → URL query → ``local_open_effective`` accepts the session."""
    home = tmp_path / "home"
    ws_dir = home / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {
                    "host": "127.0.0.1",
                    "port": 3001,
                    "token": "${SECRET:keychain:sevn.gateway.token}",
                },
                "dashboard": {"enabled": True, "local_open": True},
                "infrastructure": {"tunnel": {"mode": "none"}},
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_HOME", str(home))

    with _client(tmp_path, sevn_home=home) as client:
        boot_token = _boot_local_token(client)

        from sevn.cli.gateway_client import gateway_get as real_get

        def _ok(path: str, **kwargs: object) -> object:
            import httpx

            transport = httpx.MockTransport(
                lambda request: httpx.Response(200, json={"status": "ok"}, request=request),
            )
            return real_get(path, transport=transport, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr("sevn.cli.commands.dashboard_cmd.gateway_get", _ok)

        runner = ClickCliRunner()
        result = runner.invoke(
            get_command(app), ["dashboard", "--json"], env={"SEVN_HOME": str(home)}
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        url = payload["data"]["url"]
        query = parse_qs(urlparse(url).query)
        assert query[DASHBOARD_LOCAL_TOKEN_QUERY][0] == boot_token

        sessions = client.get(
            f"/api/v1/sessions?limit=5&{DASHBOARD_LOCAL_TOKEN_QUERY}={boot_token}"
        )
        assert sessions.status_code == 200
