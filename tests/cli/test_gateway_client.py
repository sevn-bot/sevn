"""Tests for ``sevn.cli.gateway_client`` (`specs/23-cli.md` §2.3)."""

from __future__ import annotations

import httpx
import pytest

from sevn.cli.errors import CliAuthError, CliPreconditionError, CliUsageError
from sevn.cli.gateway_client import (
    gateway_get,
    gateway_json_request,
    resolve_gateway_base_url,
    resolve_gateway_token,
)
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import GatewayConfig, WorkspaceConfig


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
