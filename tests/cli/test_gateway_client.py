"""Tests for ``sevn.cli.gateway_client`` (`specs/23-cli.md` §2.3)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from sevn.cli.errors import CliAuthError, CliPreconditionError, CliUsageError
from sevn.cli.gateway_client import (
    _append_dashboard_local_token,
    _redact_gateway_url_for_error,
    gateway_get,
    gateway_json_request,
    resolve_gateway_base_url,
    resolve_gateway_token,
)
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    GatewayConfig,
    WorkspaceConfig,
)
from sevn.ui.dashboard.services.auth import apply_tunnel_local_open_policy
from sevn.ui.dashboard.services.local_token import (
    DASHBOARD_LOCAL_TOKEN_QUERY,
    write_dashboard_local_token,
)


def _local_open_workspace(*, local_open: bool = True) -> WorkspaceConfig:
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway=GatewayConfig(
            host="127.0.0.1",
            port=3001,
            token="literal-gateway-token-at-least-32-chars",
        ),
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            local_open=local_open,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        infrastructure={"tunnel": {"mode": "none"}},
    )
    apply_tunnel_local_open_policy(cfg)
    return cfg


def _write_boot_token(home: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("SEVN_HOME", str(home))
    home.mkdir(parents=True, exist_ok=True)
    return write_dashboard_local_token(home=home)


def test_resolve_gateway_url_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_URL", "http://custom:9000/")
    url = resolve_gateway_base_url(
        workspace=WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        )
    )
    assert url == "http://custom:9000"


def test_resolve_gateway_url_bad_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_URL", "not-a-url")
    with pytest.raises(CliUsageError):
        resolve_gateway_base_url()


def test_resolve_gateway_from_workspace_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_URL", raising=False)
    cfg = WorkspaceConfig(
        schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
    )
    url = resolve_gateway_base_url(process=ProcessSettings(), workspace=cfg)
    assert url == "http://127.0.0.1:3001"


def test_gateway_get_5xx_retry_then_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_URL", raising=False)
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    n = {"c": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["c"] += 1
        if n["c"] < 2:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"status": "ok"}, request=request)

    transport = httpx.MockTransport(handler)
    r = gateway_get(
        "/health",
        workspace=WorkspaceConfig(
            schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
        ),
        liveness=True,
        transport=transport,
    )
    assert r.status_code == 200
    assert n["c"] == 2


def test_resolve_gateway_token_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "from-env")
    cfg = WorkspaceConfig(schema_version=1, gateway=GatewayConfig(token="from-json"))
    assert resolve_gateway_token(process=ProcessSettings(), workspace=cfg) == "from-env"


def test_resolve_gateway_token_from_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    cfg = WorkspaceConfig(schema_version=1, gateway=GatewayConfig(token="from-json"))
    assert resolve_gateway_token(process=ProcessSettings(), workspace=cfg) == "from-json"


def test_gateway_json_request_uses_workspace_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    cfg = WorkspaceConfig(schema_version=1, gateway=GatewayConfig(token="ws-tok"))
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={}, request=request)

    response = gateway_json_request(
        "GET",
        "/api/v1/admin/secrets",
        workspace=cfg,
        transport=httpx.MockTransport(handler),
    )
    assert response.status_code == 200
    assert seen["auth"] == "Bearer ws-tok"


def test_gateway_get_require_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)
    with pytest.raises(CliAuthError):
        gateway_get(
            "/x",
            workspace=WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            ),
            require_token=True,
            transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        )


def test_gateway_get_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "tok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with pytest.raises(CliAuthError):
        gateway_get(
            "/health",
            workspace=WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            ),
            transport=httpx.MockTransport(handler),
        )


def test_gateway_get_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_GATEWAY_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    with pytest.raises(CliPreconditionError):
        gateway_get(
            "/nope",
            workspace=WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            ),
            transport=httpx.MockTransport(handler),
        )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "http://127.0.0.1:3001/api/v1/x?local_token=secret",
            "http://127.0.0.1:3001/api/v1/x",
        ),
        (
            "http://127.0.0.1:3001/api/v1/x?foo=1&local_token=secret&bar=2",
            "http://127.0.0.1:3001/api/v1/x?foo=1&bar=2",
        ),
        ("http://127.0.0.1:3001/health", "http://127.0.0.1:3001/health"),
    ],
)
def test_redact_gateway_url_for_error_strips_local_token(url: str, expected: str) -> None:
    assert _redact_gateway_url_for_error(url) == expected


def test_append_dashboard_local_token_appends_on_api_v1_local_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    token = _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()
    url = _append_dashboard_local_token(
        "http://127.0.0.1:3001/api/v1/sessions",
        workspace=ws,
        path="/api/v1/sessions",
    )
    assert f"{DASHBOARD_LOCAL_TOKEN_QUERY}={token}" in url


def test_append_dashboard_local_token_skips_non_api_v1_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()
    url = _append_dashboard_local_token(
        "http://127.0.0.1:3001/health",
        workspace=ws,
        path="/health",
    )
    assert DASHBOARD_LOCAL_TOKEN_QUERY not in url


def test_gateway_get_appends_local_token_for_api_v1_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    token = _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True}, request=request)

    response = gateway_get(
        "/api/v1/sessions",
        workspace=ws,
        transport=httpx.MockTransport(handler),
    )
    assert response.status_code == 200
    assert f"{DASHBOARD_LOCAL_TOKEN_QUERY}={token}" in seen["url"]


def test_gateway_get_auth_error_redacts_local_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    token = _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with pytest.raises(CliAuthError, match="gateway auth failed") as exc_info:
        gateway_get(
            "/api/v1/sessions",
            workspace=ws,
            transport=httpx.MockTransport(handler),
        )
    message = str(exc_info.value)
    assert token not in message
    assert DASHBOARD_LOCAL_TOKEN_QUERY not in message


def test_gateway_get_client_error_redacts_local_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    token = _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    with pytest.raises(CliPreconditionError, match="gateway HTTP 404") as exc_info:
        gateway_get(
            "/api/v1/sessions",
            workspace=ws,
            transport=httpx.MockTransport(handler),
        )
    message = str(exc_info.value)
    assert token not in message
    assert DASHBOARD_LOCAL_TOKEN_QUERY not in message


def test_gateway_json_request_appends_local_token_for_api_v1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    token = _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={}, request=request)

    response = gateway_json_request(
        "GET",
        "/api/v1/admin/secrets",
        workspace=ws,
        transport=httpx.MockTransport(handler),
    )
    assert response.status_code == 200
    assert f"{DASHBOARD_LOCAL_TOKEN_QUERY}={token}" in seen["url"]


def test_gateway_json_request_auth_error_redacts_local_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    token = _write_boot_token(home, monkeypatch)
    ws = _local_open_workspace()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    with pytest.raises(CliAuthError, match="gateway auth failed") as exc_info:
        gateway_json_request(
            "GET",
            "/api/v1/admin/secrets",
            workspace=ws,
            transport=httpx.MockTransport(handler),
        )
    message = str(exc_info.value)
    assert token not in message
    assert DASHBOARD_LOCAL_TOKEN_QUERY not in message
