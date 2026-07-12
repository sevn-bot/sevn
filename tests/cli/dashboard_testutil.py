"""Shared TestClient + dashboard API patching for CLI command tests."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

import httpx
from starlette.testclient import TestClient

if TYPE_CHECKING:
    import pytest

import sevn.cli.dashboard_api_client as dashboard_api_client_mod
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import parse_workspace_config
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout


def patch_dashboard_gateway(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    request: pytest.FixtureRequest,
    *,
    sevn_doc: dict[str, object] | None = None,
) -> TestClient:
    """Boot in-process gateway and route dashboard API calls through TestClient.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
        tmp_path_factory (pytest.TempPathFactory): Temp directory factory.
        request (pytest.FixtureRequest): Pytest request for finalizer.
        sevn_doc (dict[str, object] | None): Optional ``sevn.json`` document override.

    Returns:
        TestClient: Starlette test client for the gateway app.
    """
    home = tmp_path_factory.mktemp("home")
    ws = home / "workspace"
    ws.mkdir()
    doc = sevn_doc or {
        "schema_version": 2,
        "providers": {
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        "gateway": {"token": "gw-token"},
    }
    (ws / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    cfg = parse_workspace_config(doc)
    layout = WorkspaceLayout.from_config(ws / "sevn.json", cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    gw_app = create_app(
        workspace=cfg,
        layout=layout,
        sqlite_connection_factory=factory,
        process_settings=ProcessSettings(gateway_token="gw-token"),
    )
    client_cm = TestClient(gw_app, raise_server_exceptions=True)
    tc = client_cm.__enter__()
    tc.get("/health")
    request.addfinalizer(lambda: client_cm.__exit__(None, None, None))

    def _via_test_client(
        method: str,
        path: str,
        *,
        json_body: dict[str, object] | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        _ = kwargs, json_body
        if method.upper() != "GET":
            msg = f"unsupported method {method}"
            raise ValueError(msg)
        starlette_resp = tc.get(path)
        return httpx.Response(
            status_code=starlette_resp.status_code,
            json=starlette_resp.json() if starlette_resp.content else None,
            request=httpx.Request("GET", path),
        )

    monkeypatch.setattr(dashboard_api_client_mod, "gateway_json_request", _via_test_client)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "gw-token")
    return tc
