"""Loopback detection, guard lists from config, and CSP (plan 0055 D4, D5, D8).

Security core (never relax): a request that came through a proxy is never a loopback owner
session, and ``Tailscale-User-Login`` is never read as identity.

Pinned for W4 (see ``.ignorelocal/test-plans/0055-direct-multi-host.md``):
- ``sevn.http.is_loopback(headers: Headers, peer: str | None, port: int) -> bool``;
- ``HttpSettings.allowed_hosts | allowed_origins | connect_src: list[str] = []``,
  ``public_scheme: Literal["http", "https"] = "http"``;
- ``/auth/login`` from a non-loopback request: 403, body ``login is loopback only``;
- ``sevn serve --host 0.0.0.0 --allow-remote-bind`` with no allowed hosts: exit 2, names
  ``http.allowed_hosts``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from support.http_app import CSP, running_app

LOGIN_REFUSED = "login is loopback only"
PORT = 8787
TAILNET = "mac.tailnet.ts.net"
PEER = "100.101.102.103"

# W0.3: the headers `tailscale serve` adds, plus the common reverse-proxy ones (D4, completed).
PROXY_HEADERS: dict[str, str] = {
    "Forwarded": f"for={PEER};proto=https;host={TAILNET}",
    "X-Forwarded-For": PEER,
    "X-Forwarded-Host": TAILNET,
    "X-Forwarded-Proto": "https",
    "X-Real-IP": PEER,
    "Tailscale-User-Login": "owner@example.com",
    "Tailscale-User-Name": "Owner Example",
    "Tailscale-User-Profile-Pic": "https://example.com/owner.png",
    "Tailscale-Headers-Info": "https://tailscale.com/s/serve-headers",
}

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


def _config(home: Path, http: str = "") -> Path:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        f'[secrets]\nbackend = "age-file"\n\n[http]\nhost = "127.0.0.1"\nport = {PORT}\n{http}',
        encoding="utf-8",
    )
    return home


# --- loopback detection (D4) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "peer", "loopback"),
    [
        ({"host": f"127.0.0.1:{PORT}"}, "127.0.0.1", True),
        ({"host": f"localhost:{PORT}"}, "127.0.0.1", True),
        ({"host": f"[::1]:{PORT}"}, "::1", True),
        ({"host": f"127.0.0.1:{PORT}"}, PEER, False),
        ({"host": f"127.0.0.1:{PORT}"}, None, False),
        ({"host": TAILNET}, "127.0.0.1", False),
        ({"host": f"{TAILNET}:{PORT}"}, "127.0.0.1", False),
        ({"host": "127.0.0.1:9999"}, "127.0.0.1", False),
        ({"host": "127.0.0.1"}, "127.0.0.1", False),
        ({}, "127.0.0.1", False),
        ({"host": f"127.0.0.1:{PORT}", "x-forwarded-for": ""}, "127.0.0.1", False),
        ({"host": f"127.0.0.1:{PORT}", "TAILSCALE-USER-LOGIN": "a@b.c"}, "127.0.0.1", False),
    ],
    ids=[
        "ipv4",
        "localhost",
        "ipv6",
        "remote-peer",
        "no-peer",
        "tailnet-host",
        "tailnet-host-port",
        "wrong-port",
        "no-port",
        "no-host",
        "empty-forwarded-for",
        "uppercase-tailscale-header",
    ],
)
def test_is_loopback_rule(headers: dict[str, str], peer: str | None, loopback: bool) -> None:
    from sevn.http import is_loopback
    from starlette.datastructures import Headers

    assert is_loopback(Headers(headers), peer, PORT) is loopback


@pytest.mark.parametrize("header", sorted(PROXY_HEADERS))
def test_proxied_loopback_request_is_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    """`tailscale serve` connects from 127.0.0.1 with a loopback Host: any proxy header wins."""
    from sevn.http import is_loopback
    from starlette.datastructures import Headers

    value = PROXY_HEADERS[header]
    assert (
        is_loopback(Headers({"host": f"127.0.0.1:{PORT}", header: value}), "127.0.0.1", PORT)
        is False
    )
    with running_app(_config(tmp_path), monkeypatch) as (_app, token, client):
        login = client.get(f"/auth/login?token={token}", headers={header: value})
        assert login.status_code == 403
        assert login.text.strip() == LOGIN_REFUSED
        assert "sevn_session=" not in login.headers.get("set-cookie", "")
        # A real loopback login, then the same cookie through the proxy: not an owner session.
        ok = client.get(f"/auth/login?token={token}")
        assert ok.status_code == 303
        with client.websocket_connect("/ws", headers={header: value}) as socket:
            socket.send_json(_HELLO)
            first = socket.receive_json()
        assert first["t"] == "challenge", first


def test_tailscale_identity_header_is_never_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Tailscale-User-Login` names a tailnet user; it never stands in for a token or device."""
    from starlette.websockets import WebSocketDisconnect

    identity = {"Tailscale-User-Login": "owner@example.com", "Tailscale-User-Name": "Owner"}
    with running_app(_config(tmp_path, f'allowed_hosts = ["{TAILNET}"]\n'), monkeypatch) as (
        _app,
        _token,
        client,
    ):
        for headers in (identity, {**identity, "host": TAILNET}):
            login = client.get("/auth/login", headers=headers)
            assert login.status_code == 403
            assert "sevn_session=" not in login.headers.get("set-cookie", "")
        with client.websocket_connect("/ws", headers=identity) as socket:
            socket.send_json(_HELLO)
            first = socket.receive_json()
            assert first["t"] == "challenge", first
            socket.send_json({"t": "auth", "token": ""})
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
        assert closed.value.code == 4001


@pytest.mark.parametrize(
    ("peer", "host_header", "extra"),
    [
        ((PEER, 41000), None, {}),
        (("127.0.0.1", 41000), TAILNET, {}),
        (("127.0.0.1", 41000), TAILNET, {"X-Forwarded-For": PEER, "X-Forwarded-Proto": "https"}),
    ],
    ids=["remote-peer", "tailnet-host", "tailscale-serve"],
)
def test_auth_login_refused_when_not_loopback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    peer: tuple[str, int],
    host_header: str | None,
    extra: dict[str, str],
) -> None:
    headers = dict(extra)
    if host_header is not None:
        headers["host"] = host_header
    home = _config(tmp_path, f'allowed_hosts = ["{TAILNET}"]\n')
    with running_app(home, monkeypatch, peer=peer) as (_app, token, client):
        login = client.get(f"/auth/login?token={token}", headers=headers)
        assert login.status_code == 403
        assert login.text.strip() == LOGIN_REFUSED
        assert "sevn_session=" not in login.headers.get("set-cookie", "")


def test_auth_login_still_works_on_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control for the refusals above (green now, stays green)."""
    with running_app(_config(tmp_path), monkeypatch) as (_app, token, client):
        login = client.get(f"/auth/login?token={token}")
        assert login.status_code == 303
        assert "sevn_session=" in login.headers["set-cookie"]


# --- guard config (D5) -----------------------------------------------------------------------


def test_http_settings_defaults_and_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import ValidationError
    from sevn.config import HttpSettings, Settings

    defaults = HttpSettings()
    assert defaults.allowed_hosts == []
    assert defaults.allowed_origins == []
    assert defaults.connect_src == []
    assert defaults.public_scheme == "http"
    with pytest.raises(ValidationError):
        HttpSettings(public_scheme="ftp")
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    _config(
        tmp_path,
        f'allowed_hosts = ["{TAILNET}"]\nallowed_origins = ["https://{TAILNET}"]\n'
        'public_scheme = "https"\nconnect_src = ["wss://linux.tailnet.ts.net"]\n',
    )
    loaded = Settings.load().http
    assert loaded.allowed_hosts == [TAILNET]
    assert loaded.allowed_origins == [f"https://{TAILNET}"]
    assert loaded.public_scheme == "https"
    assert loaded.connect_src == ["wss://linux.tailnet.ts.net"]


def test_allowed_hosts_from_config_and_env_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _config(tmp_path, f'allowed_hosts = ["{TAILNET}"]\n')
    with running_app(home, monkeypatch, allowed_hosts="linux.tailnet.ts.net:8443") as (
        _app,
        _token,
        client,
    ):
        for host in (TAILNET, "linux.tailnet.ts.net:8443", f"127.0.0.1:{PORT}"):
            passed = client.get("/auth/login", headers={"host": host})
            assert passed.text.strip() != "forbidden host", host
        for host in ("evil.example", f"{TAILNET}.evil.example", "linux.tailnet.ts.net"):
            denied = client.get("/auth/login", headers={"host": host})
            assert denied.status_code == 403, host
            assert denied.text.strip() == "forbidden host", host


def test_allowed_origin_accepted_other_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_spa = "https://other.tailnet.ts.net"
    home = _config(tmp_path, f'allowed_origins = ["{other_spa}"]\n')
    with running_app(home, monkeypatch) as (_app, token, client):
        accepted = client.get(f"/auth/login?token={token}", headers={"origin": other_spa})
        assert accepted.status_code == 303
        with client.websocket_connect("/ws", headers={"origin": other_spa}) as socket:
            socket.send_json(_HELLO)
            socket.send_json({"t": "auth", "token": token})
            assert socket.receive_json()["t"] == "welcome"
        for origin in (
            "https://evil.example",
            f"{other_spa}.evil.example",
            "http://other.tailnet.ts.net",
            f"{other_spa}:8443",
        ):
            refused = client.get(f"/auth/login?token={token}", headers={"origin": origin})
            assert refused.status_code == 403, origin
            assert refused.text.strip() == "forbidden origin", origin
            ws = client.get("/ws", headers={"origin": origin, **_UPGRADE})
            assert ws.status_code == 403, origin
            assert ws.text.strip() == "forbidden origin", origin


@pytest.mark.parametrize("http", ["", f'allowed_hosts = ["{TAILNET}"]\n'], ids=["none", "tailnet"])
def test_remote_bind_without_allowed_hosts_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, http: str
) -> None:
    import sevn.log
    import uvicorn
    from sevn.cli import app
    from typer.testing import CliRunner

    runs: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **kwargs: runs.append(kwargs))
    monkeypatch.setattr(sevn.log, "setup", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_ALLOWED_HOSTS", raising=False)
    _config(tmp_path, http)
    result = CliRunner().invoke(
        app,
        ["serve", "--host", "0.0.0.0", "--allow-remote-bind", "--home", str(tmp_path)],  # noqa: S104 — asserts the flag, nothing binds
    )
    output = result.output + (result.stderr or "")
    if http == "":
        assert result.exit_code == 2, output
        assert "http.allowed_hosts" in output
        assert runs == []
    else:
        assert result.exit_code == 0, output
        assert [run.get("host") for run in runs] == ["0.0.0.0"]  # noqa: S104 — the value the fake serve received


# --- CSP (D8) --------------------------------------------------------------------------------


def _directives(policy: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for part in policy.split(";"):
        words = part.split()
        if words:
            found[words[0]] = words[1:]
    return found


def test_default_csp_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: with no remote config the SPA keeps 0001's policy (green now, stays green)."""
    with running_app(_config(tmp_path), monkeypatch) as (_app, _token, client):
        response = client.get("/")
        assert response.headers["content-security-policy"] == CSP


def test_csp_connect_src_lists_allowed_hosts_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _config(
        tmp_path,
        f'allowed_hosts = ["{TAILNET}", "linux.tailnet.ts.net:8443"]\n'
        'connect_src = ["wss://pi.tailnet.ts.net", "ws://100.101.102.104:8787"]\n',
    )
    with running_app(home, monkeypatch) as (_app, _token, client):
        response = client.get("/")
        policy = _directives(response.headers["content-security-policy"])
    assert set(policy["connect-src"]) == {
        "'self'",
        f"wss://{TAILNET}",
        "wss://linux.tailnet.ts.net:8443",
        "wss://pi.tailnet.ts.net",
        "ws://100.101.102.104:8787",
    }
    assert policy["connect-src"][0] == "'self'"
    baseline = _directives(CSP)
    for name in ("default-src", "img-src", "style-src"):
        assert policy[name] == baseline[name]


# --- guard order (D5) ------------------------------------------------------------------------


def test_guard_order_host_then_origin_then_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sevn.http as http

    home = _config(tmp_path, f'allowed_hosts = ["{TAILNET}"]\n')
    with running_app(home, monkeypatch) as (_app, token, client):
        calls: list[object] = []
        real = http.check_credentials

        def spy(presented: str, expected: str) -> bool:
            calls.append(presented)
            return real(presented, expected)

        monkeypatch.setattr(http, "check_credentials", spy)
        evil = {"origin": "https://evil.example", **{"X-Forwarded-For": PEER}}
        host_first = client.get("/auth/login?token=bad", headers={"host": "evil.example", **evil})
        assert (host_first.status_code, host_first.text.strip()) == (403, "forbidden host")
        origin_next = client.get("/auth/login?token=bad", headers={"host": TAILNET, **evil})
        assert (origin_next.status_code, origin_next.text.strip()) == (403, "forbidden origin")
        ws_origin = client.get("/ws", headers={"host": TAILNET, **evil, **_UPGRADE})
        assert (ws_origin.status_code, ws_origin.text.strip()) == (403, "forbidden origin")
        assert calls == [], "no credential lookup before the Host and Origin checks"
        remote = client.get(
            f"/auth/login?token={token}",
            headers={"host": TAILNET, "origin": f"https://{TAILNET}"},
        )
        assert (remote.status_code, remote.text.strip()) == (403, LOGIN_REFUSED)
        assert calls == [], "a remote login is refused before the token is looked at"
        local = client.get("/auth/login?token=bad")
        assert (local.status_code, local.text.strip()) == (401, "unauthorized")
        assert calls == ["bad"]


@pytest.mark.parametrize("literal", ["::ffff:127.0.0.1", "::ffff:7f00:1"])
@pytest.mark.parametrize("hostname", ["127.0.0.1", "localhost"])
def test_ipv4_mapped_loopback_peer_can_log_in_and_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, literal: str, hostname: str
) -> None:
    from sevn.http import is_loopback
    from starlette.datastructures import Headers

    host = f"{hostname}:{PORT}"
    assert is_loopback(Headers({"host": host}), literal, PORT)
    with running_app(_config(tmp_path), monkeypatch, peer=(literal, 41000)) as (
        _app,
        token,
        client,
    ):
        login = client.get(f"/auth/login?token={token}", headers={"host": host})
        assert login.status_code == 303
        with client.websocket_connect("/ws", headers={"host": host}) as socket:
            socket.send_json(_HELLO)
            socket.send_json({"t": "auth", "token": token})
            assert socket.receive_json()["t"] == "welcome"


@pytest.mark.parametrize(
    ("peer", "extra"),
    [
        ("::ffff:192.168.1.2", {}),
        ("::ffff:127.0.0.1", {"x-forwarded-for": "192.168.1.2"}),
        ("::ffff:127.0.0.1", {"x-forwarded-for": ""}),
    ],
    ids=["mapped-remote", "mapped-proxy", "mapped-empty-proxy"],
)
def test_mapped_peer_still_requires_loopback_and_no_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, peer: str, extra: dict[str, str]
) -> None:
    from sevn.http import is_loopback
    from starlette.datastructures import Headers

    headers = {"host": f"127.0.0.1:{PORT}", **extra}
    assert not is_loopback(Headers(headers), peer, PORT)
    with running_app(_config(tmp_path), monkeypatch, peer=(peer, 41000)) as (
        _app,
        token,
        client,
    ):
        login = client.get(f"/auth/login?token={token}", headers=headers)
        assert (login.status_code, login.text.strip()) == (403, LOGIN_REFUSED)
        assert "sevn_session=" not in login.headers.get("set-cookie", "")
