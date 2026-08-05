"""Prod-readiness Batch F W21 RED - C6.2 / C6.4 trust-address + CLI honesty.

Contracts (``about-sevn.bot/specs/24-dashboard.md``, ``19-channel-webui.md``,
``.ignorelocal/waves/prod-readiness-0.0.1-wave-plan.md`` W21 / D-table):

- **C6.2 / W21.1** - ``dashboard.local_open_trust_address`` is refused when a
  tunnel or reverse-proxy-style bind is configured, even when the key is
  ``true`` (xfail → W22).
- **C6.2 / W21.2** - enabling the escape logs a loud boot warning mirroring
  ``SEVN_PROXY_ALLOW_UNAUTHENTICATED`` (xfail → W22).
- **C6.4 / W21.3** - ``sevn dashboard`` no longer prints
  ``loopback access - no login required`` when a boot token is required
  (xfail → W22).
- **W21.4 guard** - landed C6.1 / C6.3 tokenless-loopback denial stays green
  and the auth suites are not rewritten by this wave.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
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
from sevn.ui.dashboard.services.auth import apply_tunnel_local_open_policy
from sevn.workspace.layout import WorkspaceLayout

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LANDED_LOCAL_OPEN = _REPO_ROOT / "tests" / "ui" / "dashboard" / "test_local_open_auth.py"
_LANDED_POST_AUDIT = (
    _REPO_ROOT / "tests" / "ui" / "dashboard" / "test_post_audit_local_token_w17_red.py"
)


def _workspace(
    *,
    local_open: bool | None = True,
    local_open_trust_address: bool = False,
    login_password: str = "pw",
    tunnel_mode: str = "none",
    gateway_host: str = "127.0.0.1",
) -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway=GatewayConfig(
            host=gateway_host,
            port=3001,
            token="${SECRET:keychain:sevn.gateway.token}",
        ),
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            local_open=local_open,
            local_open_trust_address=local_open_trust_address,
            login_password=login_password,
            jwt_secret="dashboard-secret",
        ),
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
) -> Iterator[TestClient]:
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
    with TestClient(app_instance, client=("127.0.0.1", 0), raise_server_exceptions=True) as client:
        yield client


def _write_cli_workspace(
    home: Path,
    *,
    local_open: bool = True,
    tunnel_mode: str = "none",
) -> None:
    ws = home / "workspace"
    ws.mkdir(parents=True)
    doc: dict[str, object] = {
        "schema_version": 1,
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "dashboard": {"enabled": True, "local_open": local_open},
        "infrastructure": {"tunnel": {"mode": tunnel_mode}},
    }
    (ws / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")


def _patch_gateway_get_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli.gateway_client import gateway_get as real_get

    def _ok(path: str, **kwargs: object) -> httpx.Response:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ok"}, request=request),
        )
        return real_get(path, transport=transport, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("sevn.cli.commands.dashboard_cmd.gateway_get", _ok)


# ---------------------------------------------------------------------------
# W21.4 - guard (must pass on batch base; do not modify landed suites)
# ---------------------------------------------------------------------------


def test_guard_c61_tokenless_loopback_denied(tmp_path: Path) -> None:
    """W21.4 - landed C6.1: tokenless direct loopback is denied."""
    with _client(tmp_path, workspace=_workspace(local_open=True)) as client:
        assert client.get("/api/v1/sessions?limit=5").status_code == 401


def test_guard_c63_landed_auth_suites_unmodified() -> None:
    """W21.4 - C6.1/C6.3 dashboard auth suites remain present and assertive."""
    local_open = _LANDED_LOCAL_OPEN.read_text(encoding="utf-8")
    post_audit = _LANDED_POST_AUDIT.read_text(encoding="utf-8")
    assert "test_auth_status_local_open_loopback" in local_open
    assert '"auth_required": True' in local_open or "'auth_required': True" in local_open
    assert "test_tokenless_loopback_denied_when_local_open_effective" in post_audit
    assert "assert resp.status_code == 401" in post_audit
    # Permissive-branch pin must stay gone (C6.3).
    assert "test_sessions_without_login_on_loopback" in local_open
    assert "DASHBOARD_LOCAL_TOKEN_QUERY" in local_open


# ---------------------------------------------------------------------------
# W21.1 - refuse trust-address under tunnel / reverse-proxy bind (→ W22)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W22: trust-address refused under tunnel", strict=False)
def test_trust_address_forced_off_when_tunnel_configured() -> None:
    """W21.1 / C6.2 - tunnel active must clear ``local_open_trust_address``."""
    ws = _workspace(
        local_open=True,
        local_open_trust_address=True,
        tunnel_mode="cloudflare",
    )
    assert ws.dashboard is not None
    assert ws.dashboard.local_open_trust_address is True
    apply_tunnel_local_open_policy(ws)
    assert ws.dashboard.local_open_trust_address is False
    assert ws.dashboard.local_open is False


@pytest.mark.xfail(
    reason="green after W22: trust-address refused under non-loopback bind",
    strict=False,
)
def test_trust_address_forced_off_when_gateway_not_loopback() -> None:
    """W21.1 / C6.2 - reverse-proxy-style bind refuses the escape hatch."""
    ws = _workspace(
        local_open=True,
        local_open_trust_address=True,
        tunnel_mode="none",
        gateway_host="0.0.0.0",
    )
    apply_tunnel_local_open_policy(ws)
    assert ws.dashboard is not None
    assert ws.dashboard.local_open_trust_address is False
    assert ws.dashboard.local_open is False


def test_tokenless_denied_under_tunnel_even_when_trust_address_true(tmp_path: Path) -> None:
    """W21.1 companion - tunnel policy already denies tokenless even if the escape is set.

    The *new* W22 contract is forcing ``local_open_trust_address`` off (xfails above);
    this assertion stays green on the batch base so deleting tunnel refusal regresses.
    """
    ws = _workspace(
        local_open=True,
        local_open_trust_address=True,
        tunnel_mode="cloudflare",
    )
    with _client(tmp_path, workspace=ws) as client:
        assert client.get("/api/v1/sessions?limit=5").status_code == 401
        status = client.get("/api/v1/auth/status")
        body = status.json()
        assert body["tunnel_active"] is True
        assert body["local_open"] is False
        assert body["auth_required"] is True


# ---------------------------------------------------------------------------
# W21.2 - boot warning when trust-address enabled (→ W22)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W22: trust-address boot warning", strict=False)
def test_trust_address_boot_warning_emitted_when_enabled() -> None:
    """W21.2 / C6.2 - loud warning when ``local_open_trust_address`` is on."""
    from loguru import logger

    from sevn.ui.dashboard.services.auth import log_local_open_trust_address_boot_warning

    ws = _workspace(local_open=True, local_open_trust_address=True, tunnel_mode="none")
    warnings: list[str] = []
    sink_id = logger.add(lambda rec: warnings.append(str(rec)), level="WARNING")
    try:
        log_local_open_trust_address_boot_warning(ws)
    finally:
        logger.remove(sink_id)
    joined = " ".join(warnings).lower()
    assert "local_open_trust_address" in joined or "trust_address" in joined
    assert "trust" in joined or "dangerous" in joined or "escape" in joined


@pytest.mark.xfail(reason="green after W22: trust-address boot warning noop", strict=False)
def test_trust_address_boot_warning_noop_when_disabled() -> None:
    """W21.2 - no warning when the escape hatch is off (proxy-pattern mirror)."""
    from loguru import logger

    from sevn.ui.dashboard.services.auth import log_local_open_trust_address_boot_warning

    ws = _workspace(local_open=True, local_open_trust_address=False)
    warnings: list[str] = []
    sink_id = logger.add(lambda rec: warnings.append(str(rec)), level="WARNING")
    try:
        log_local_open_trust_address_boot_warning(ws)
    finally:
        logger.remove(sink_id)
    assert warnings == []


# ---------------------------------------------------------------------------
# W21.3 - CLI message honesty when token is required (→ W22)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W22: CLI no longer claims no login required", strict=False)
def test_dashboard_cli_does_not_claim_no_login_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W21.3 / C6.4 - C6.1 made a boot token mandatory; the CLI must say so."""
    home = tmp_path / "home"
    _write_cli_workspace(home, local_open=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    _patch_gateway_get_ok(monkeypatch)

    result = ClickCliRunner().invoke(get_command(app), ["dashboard"])
    assert result.exit_code == 0
    assert "http://127.0.0.1:3001/mission/" in result.stdout
    assert "no login required" not in result.stdout.lower()
