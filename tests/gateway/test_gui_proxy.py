"""Tests for ``sevn.gateway.gui_proxy``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sevn.gateway.gui_proxy import (
    GUI_SESSION_COOKIE,
    _upstream_ws_url,
    mount_gui_proxy,
)

_GATEWAY_TOKEN = "required-token-at-least-32-characters-long"


@pytest.fixture
def gui_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: None)
    return TestClient(app)


def test_upstream_ws_url_builds_ws_scheme() -> None:
    """Internal upstream HTTP base maps to ws:// for websockify."""
    assert _upstream_ws_url("http://127.0.0.1:6080", "websockify", query="a=1") == (
        "ws://127.0.0.1:6080/websockify?a=1"
    )


def test_gui_root_redirect_uses_gui_websockify_path(gui_client: TestClient) -> None:
    """noVNC path query targets the gateway WebSocket proxy route."""
    response = gui_client.get("/gui", follow_redirects=False)
    assert response.status_code == 307
    assert (
        "path=gui%2Fwebsockify" in response.headers["location"]
        or "path=gui/websockify" in (response.headers["location"])
    )


def test_gui_proxy_forwards_query_string(gui_client: TestClient) -> None:
    """Proxied noVNC requests include the client query string."""
    mock_response = MagicMock()
    mock_response.content = b"ok"
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}

    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("sevn.gateway.gui_proxy.httpx.AsyncClient", return_value=mock_client):
        response = gui_client.get("/gui/vnc.html?autoconnect=1&resize=scale")

    assert response.status_code == 200
    mock_client.request.assert_awaited_once()
    called_url = mock_client.request.await_args.args[1]
    assert called_url == "http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale"


def test_gui_accepts_token_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    """Browser entry may authenticate via ``?token=`` instead of Authorization."""
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: _GATEWAY_TOKEN)
    client = TestClient(app)

    denied = client.get("/gui/vnc.html", follow_redirects=False)
    assert denied.status_code == 401

    mock_response = MagicMock()
    mock_response.content = b"ok"
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("sevn.gateway.gui_proxy.httpx.AsyncClient", return_value=mock_client):
        allowed = client.get(f"/gui/vnc.html?token={_GATEWAY_TOKEN}")
    assert allowed.status_code == 200


def test_gui_sets_session_cookie_on_token_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful ``/gui?token=`` mints a scoped session cookie for assets + WS."""
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: _GATEWAY_TOKEN)
    client = TestClient(app)

    response = client.get(f"/gui?token={_GATEWAY_TOKEN}", follow_redirects=False)
    assert response.status_code == 307
    assert GUI_SESSION_COOKIE in response.cookies


def test_gui_accepts_valid_cookie_when_query_token_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bookmarked URLs with stale ``?token=`` still work when the session cookie is valid."""
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: _GATEWAY_TOKEN)
    client = TestClient(app)
    client.cookies.set(GUI_SESSION_COOKIE, _GATEWAY_TOKEN)

    mock_response = MagicMock()
    mock_response.content = b"ok"
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("sevn.gateway.gui_proxy.httpx.AsyncClient", return_value=mock_client):
        response = client.get("/gui/vnc.html?token=wrong-token-at-least-32-characters-long")
    assert response.status_code == 200


def test_gui_renews_stale_session_cookie_on_new_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh ``?token=`` replaces a stale GUI session cookie."""
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: _GATEWAY_TOKEN)
    client = TestClient(app)
    client.cookies.set(GUI_SESSION_COOKIE, "stale-token-at-least-32-characters-long")

    response = client.get(f"/gui?token={_GATEWAY_TOKEN}", follow_redirects=False)
    assert response.status_code == 307
    assert response.cookies[GUI_SESSION_COOKIE] == _GATEWAY_TOKEN
    client.cookies.set(GUI_SESSION_COOKIE, response.cookies[GUI_SESSION_COOKIE])

    mock_response = MagicMock()
    mock_response.content = b"ok"
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/html"}
    mock_client = MagicMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("sevn.gateway.gui_proxy.httpx.AsyncClient", return_value=mock_client):
        follow_up = client.get("/gui/vnc.html")
    assert follow_up.status_code == 200


def test_gui_ws_route_registered(gui_client: TestClient) -> None:
    """WebSocket proxy route is mounted for authenticated noVNC sessions."""
    paths = [getattr(route, "path", "") for route in gui_client.app.routes]
    assert "/gui/websockify" in paths


def test_gui_ws_rejects_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unauthenticated WebSocket handshakes close with 4401."""
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: _GATEWAY_TOKEN)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/gui/websockify"):
        pass


def test_gui_ws_accepts_token_query_param(monkeypatch: pytest.MonkeyPatch) -> None:
    """WebSocket proxy accepts ``?token=`` when browsers cannot set headers."""
    monkeypatch.setenv("SEVN_NOVNC_UPSTREAM", "http://127.0.0.1:6080")
    app = FastAPI()
    mount_gui_proxy(app, resolve_gateway_token=lambda _request: _GATEWAY_TOKEN)

    with patch("sevn.gateway.gui_proxy._relay_gui_websocket", new=AsyncMock(return_value=None)):
        client = TestClient(app)
        with client.websocket_connect(f"/gui/websockify?token={_GATEWAY_TOKEN}"):
            pass
