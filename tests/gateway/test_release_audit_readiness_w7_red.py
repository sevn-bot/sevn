"""Batch B W7 RED — ``/ready`` fails closed on dependency loss (#146; green after W8).

Contracts (`about-sevn.bot/specs/17-gateway.md`): when ``ProcessSettings.proxy_url`` is
configured and the proxy ``/healthz`` probe fails, ``GET /ready`` returns **503** with
``ready: false`` and ``proxy.ok: false``. ``GET /health`` stays a pure 200 liveness probe
that never consults dependencies.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import (
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

_PROXY_URL = "http://127.0.0.1:8787"


def _stub_async_client(*, healthy: bool) -> type:
    """Return an ``httpx.AsyncClient`` stand-in with a fixed ``/healthz`` outcome."""

    class _StubAsyncClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> _StubAsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            if not healthy:
                raise httpx.ConnectError("proxy down", request=httpx.Request("GET", url))
            return httpx.Response(200, json={"status": "ok"})

    return _StubAsyncClient


def _readiness_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    proxy_healthy: bool,
) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", '
        '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    monkeypatch.setattr(
        "sevn.gateway.http_server.httpx.AsyncClient",
        _stub_async_client(healthy=proxy_healthy),
    )

    async def _skip_boot_probe(_process: ProcessSettings) -> None:
        return None

    # The boot probe polls the same stubbed client for 5s when the proxy is down; the
    # readiness contract under test is the request-time probe, not the boot poll.
    monkeypatch.setattr(
        "sevn.gateway.http_server._log_proxy_boot_health",
        _skip_boot_probe,
        raising=False,
    )

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        process_settings=ProcessSettings(proxy_url=_PROXY_URL),
        sqlite_connection_factory=factory,
    )
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


@pytest.fixture
def proxy_down_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Gateway whose configured egress proxy refuses every ``/healthz`` probe."""
    yield from _readiness_client(tmp_path, monkeypatch, proxy_healthy=False)


@pytest.fixture
def proxy_up_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Gateway whose configured egress proxy answers ``/healthz`` with 200."""
    yield from _readiness_client(tmp_path, monkeypatch, proxy_healthy=True)


def test_health_stays_200_when_proxy_is_down(proxy_down_client: TestClient) -> None:
    """Liveness never depends on the proxy — orchestrators must not restart the gateway."""
    resp = proxy_down_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.xfail(reason="green after W8: /ready 503 when a dependency is down", strict=False)
def test_ready_returns_503_when_proxy_is_down(proxy_down_client: TestClient) -> None:
    """Readiness fails closed so load balancers drain a gateway with no egress."""
    resp = proxy_down_client.get("/ready")
    assert resp.status_code == 503


@pytest.mark.xfail(reason="green after W8: /ready body reports ready=false", strict=False)
def test_ready_body_reports_not_ready_when_proxy_is_down(proxy_down_client: TestClient) -> None:
    """The failing dependency is named in the body, and ``ready`` reflects it."""
    body = proxy_down_client.get("/ready").json()
    assert body["ready"] is False
    assert body["sqlite"] is True
    assert body["proxy"] == {"ok": False}


def test_ready_returns_200_when_proxy_is_healthy(proxy_up_client: TestClient) -> None:
    """Happy path: a reachable proxy keeps readiness at 200 with ``proxy.ok`` true."""
    resp = proxy_up_client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["sqlite"] is True
    assert body["proxy"] == {"ok": True}
