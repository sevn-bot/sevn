"""WebSocket handshake and the Origin/Host guard (D7, D8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.http_app import running_app

_HELLO = {
    "t": "hello",
    "proto": [1, 1],
    "client": "web",
    "device": "dev_test",
    "last_seq": 0,
    "caps": [],
}
_UPGRADE = {
    "connection": "Upgrade",
    "upgrade": "websocket",
    "sec-websocket-version": "13",
    "sec-websocket-key": "dGhlIHNhbXBsZSBub25jZQ==",
}


def test_ws_handshake_with_auth_frame(host_app: tuple[object, str, object], tmp_path: Path) -> None:
    _app, token, client = host_app
    token_path = tmp_path / "run" / "token"
    assert token_path.stat().st_mode & 0o777 == 0o600
    assert token_path.parent.stat().st_mode & 0o777 == 0o700
    with client.websocket_connect("/ws") as socket:  # type: ignore[attr-defined]
        socket.send_json(_HELLO)
        socket.send_json({"t": "auth", "token": token})
        welcome = socket.receive_json()
    assert welcome["t"] == "welcome"
    assert welcome["proto"] == 1


def test_foreign_origin_403(host_app: tuple[object, str, object]) -> None:
    _app, _token, client = host_app
    response = client.get(  # type: ignore[attr-defined]
        "/ws",
        headers={"origin": "https://evil.example", **_UPGRADE},
    )
    assert response.status_code == 403
    assert response.text.strip() == "forbidden origin"


def test_foreign_host_403(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with running_app(tmp_path, monkeypatch, base_url="http://evil.example") as (
        _app,
        _token,
        client,
    ):
        response = client.get("/auth/login", headers=_UPGRADE)  # type: ignore[attr-defined]
        assert response.status_code == 403
        assert response.text.strip() == "forbidden host"


def test_no_origin_allowed_for_cli(host_app: tuple[object, str, object]) -> None:
    _app, token, client = host_app
    with client.websocket_connect("/ws") as socket:  # type: ignore[attr-defined]
        socket.send_json(_HELLO)
        socket.send_json({"t": "auth", "token": token})
        welcome = socket.receive_json()
    assert welcome["t"] == "welcome"


def test_foreign_origin_with_valid_cookie_403_and_no_auth_lookup(
    host_app: tuple[object, str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, token, client = host_app
    login = client.get(f"/auth/login?token={token}")  # type: ignore[attr-defined]
    assert login.status_code == 303
    import sevn.http as http

    if not hasattr(http, "check_credentials"):
        raise AssertionError(
            "sevn.http.check_credentials is the credential lookup the origin guard must not call"
        )
    calls: list[object] = []

    def spy(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(http, "check_credentials", spy)
    response = client.get(  # type: ignore[attr-defined]
        "/ws",
        headers={"origin": "https://evil.example", **_UPGRADE},
    )
    assert response.status_code == 403
    assert response.text.strip() == "forbidden origin"
    assert calls == []


def test_dev_origin_only_with_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with running_app(tmp_path / "off", monkeypatch) as (_app, _token, client):
        denied = client.get(  # type: ignore[attr-defined]
            "/auth/login",
            headers={"origin": "http://localhost:5173"},
        )
        assert denied.status_code == 403
        assert denied.text.strip() == "forbidden origin"
    with running_app(tmp_path / "on", monkeypatch, dev="1") as (_app, _token, client):
        allowed = client.get(  # type: ignore[attr-defined]
            "/auth/login?token=not-the-token",
            headers={"origin": "http://localhost:5173"},
        )
        assert allowed.status_code == 401


def test_dev_proxy_host_allowed_when_sevn_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vite forwards the browser Host. SEVN_DEV=1 must let that request through."""
    with running_app(
        tmp_path,
        monkeypatch,
        dev="1",
        base_url="http://localhost:5173",
    ) as (_app, _token, client):
        response = client.get(  # type: ignore[attr-defined]
            "/auth/login?token=not-the-token",
            headers={"host": "localhost:5173", "origin": "http://localhost:5173"},
        )
        assert response.status_code == 401
        assert response.text.strip() == "unauthorized"


def test_allowed_hosts_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with running_app(tmp_path / "closed", monkeypatch, base_url="http://sevn.internal:8787") as (
        _app,
        _token,
        client,
    ):
        denied = client.get("/auth/login")  # type: ignore[attr-defined]
        assert denied.status_code == 403
        assert denied.text.strip() == "forbidden host"
    with running_app(
        tmp_path / "open",
        monkeypatch,
        allowed_hosts="sevn.internal:8787",
        base_url="http://sevn.internal:8787",
    ) as (_app, _token, client):
        allowed = client.get("/auth/login?token=not-the-token")  # type: ignore[attr-defined]
        assert allowed.status_code == 401


def test_https_origin_is_allowed_for_an_allowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_ALLOWED_HOSTS", "sevn.example")
    from sevn.http import refusal
    from starlette.datastructures import Headers

    allowed = Headers({"host": "sevn.example", "origin": "https://sevn.example"})
    assert refusal(allowed, 8787) is None
    denied = Headers({"host": "sevn.example", "origin": "https://evil.example"})
    assert refusal(denied, 8787) == "forbidden origin"


def test_login_sets_cookie_and_redirects(host_app: tuple[object, str, object]) -> None:
    _app, token, client = host_app
    response = client.get(f"/auth/login?token={token}")  # type: ignore[attr-defined]
    assert response.status_code == 303
    location = response.headers["location"]
    assert location == "/" or location.endswith("/")
    cookie = response.headers["set-cookie"]
    assert "sevn_session=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=strict" in cookie.lower()
    assert "path=/" in cookie.lower()


def test_login_bad_token_401(host_app: tuple[object, str, object]) -> None:
    _app, _token, client = host_app
    response = client.get("/auth/login?token=not-the-token")  # type: ignore[attr-defined]
    assert response.status_code == 401
    assert "sevn_session=" not in response.headers.get("set-cookie", "")


def test_ws_accepts_cookie_session(host_app: tuple[object, str, object]) -> None:
    _app, token, client = host_app
    login = client.get(f"/auth/login?token={token}")  # type: ignore[attr-defined]
    assert login.status_code == 303
    with client.websocket_connect("/ws") as socket:  # type: ignore[attr-defined]
        socket.send_json(_HELLO)
        welcome = socket.receive_json()
    assert welcome["t"] == "welcome"
