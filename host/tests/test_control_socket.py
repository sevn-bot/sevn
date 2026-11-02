"""The CLI reaches a running host on any bind through a unix control socket (plan 0055 WV F1-F3).

Locked fix direction (WV 2026-11-02):
- the host also serves the app on ``<SEVN_HOME>/run/control.sock`` (mode 0600, removed on
  shutdown); a connection on that listener is a loopback session (token / cookie paths), and only
  that listener can grant it; the D4 proxy-header rule still applies on it;
- ``sevn probe`` and the CLI live revoke prefer the control socket, then fall back to TCP;
- ``sevn devices revoke`` writes offline only when no host answers at all; a host that answers
  and refuses makes it exit non-zero without printing ``revoked``;
- ``sevn serve --open`` on a specific non-loopback bind opens no login URL and prints a hint to
  run ``sevn pair --scope owner``.

Overlay-bind tests bind this machine's own non-loopback IPv4 (the NetBird / ZeroTier / WireGuard
recipe); they skip only when the machine has no such address.
"""

from __future__ import annotations

import asyncio
import json
import stat
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from support.pairing import hello, op_id
from support.serve import (
    Served,
    device_session,
    free_port,
    make_home,
    overlay_ip,
    pair_over_tcp,
    serve,
    sevn,
    short_root,
)

WV = pytest.mark.xfail(strict=False, reason="green after WV fix: control socket")

_HELLO_LOOPBACK = {
    "t": "hello",
    "proto": [1, 1],
    "client": "cli",
    "device": "dev_cli",
    "last_seq": 0,
    "caps": [],
}


@pytest.fixture
def loopback_host(monkeypatch: pytest.MonkeyPatch) -> Iterator[Served]:
    with short_root() as root:
        home = make_home(root)
        monkeypatch.setenv("SEVN_HOME", str(home))
        with serve(home) as served:
            yield served


@pytest.fixture
def overlay_host(monkeypatch: pytest.MonkeyPatch) -> Iterator[Served]:
    ip = overlay_ip()
    if ip is None:
        pytest.skip("no non-loopback IPv4 address on this machine")
    port = free_port(ip)
    with short_root() as root:
        home = make_home(root, f'allowed_hosts = ["{ip}:{port}"]\n')
        monkeypatch.setenv("SEVN_HOME", str(home))
        with serve(home, ip, port) as served:
            yield served


async def _unix_first_frame(path: Path, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """hello + token auth over the control socket; returns the first frame the host sends."""
    from websockets.asyncio.client import unix_connect

    token = (path.parent / "token").read_text(encoding="utf-8").strip()
    async with unix_connect(str(path), "ws://localhost/ws", additional_headers=headers) as ws:
        await ws.send(json.dumps(_HELLO_LOOPBACK))
        first = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if first.get("t") == "challenge":
            return first
        await ws.send(json.dumps({"t": "auth", "token": token}))
        return json.loads(await asyncio.wait_for(ws.recv(), 5))


# --- the control socket itself ----------------------------------------------------------------


@WV
def test_control_socket_is_0600_and_removed_on_shutdown() -> None:
    from support.serve import stop

    with short_root() as root, serve(make_home(root)) as served:
        path = served.control
        info = path.stat()
        assert stat.S_ISSOCK(info.st_mode), "run/control.sock must be a unix socket"
        assert stat.S_IMODE(info.st_mode) == 0o600
        stop(served)
        deadline = time.monotonic() + 5
        while path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not path.exists(), "the control socket must be removed on shutdown"


@WV
def test_control_socket_gives_a_loopback_owner_session(loopback_host: Served) -> None:
    first = asyncio.run(_unix_first_frame(loopback_host.control))
    assert first["t"] == "welcome", first


@WV
@pytest.mark.parametrize(
    "header",
    ["X-Forwarded-For", "Forwarded", "Tailscale-User-Login"],
)
def test_control_socket_still_applies_proxy_headers(loopback_host: Served, header: str) -> None:
    """D4 on the control listener too: a proxied request there is not loopback."""
    assert loopback_host.control.exists()
    first = asyncio.run(_unix_first_frame(loopback_host.control, {header: "100.101.102.103"}))
    assert first["t"] == "challenge", first


# --- overlay bind: probe and live revoke ------------------------------------------------------


@WV
def test_probe_works_on_an_overlay_bind(overlay_host: Served) -> None:
    ping = sevn(
        overlay_host.home,
        "probe",
        "call",
        "system.ping",
        json.dumps({"note": "overlay", "op_id": op_id()}),
    )
    assert ping.returncode == 0, ping.stdout + ping.stderr
    assert "seq" in ping.stdout


@WV
def test_cli_revoke_on_an_overlay_bind_closes_the_live_session(overlay_host: Served) -> None:
    async def scenario() -> None:
        device, host_pubkey = await pair_over_tcp(overlay_host)
        ws = await device_session(overlay_host, device, host_pubkey)
        try:
            done = await asyncio.to_thread(sevn, overlay_host.home, "devices", "revoke", device.id)
            assert done.returncode == 0, done.stdout + done.stderr
            assert f"revoked {device.id}" in done.stdout
            await asyncio.wait_for(ws.wait_closed(), 1.0)
            assert (ws.close_code, ws.close_reason) == (4003, "revoked")
        finally:
            await ws.close()

    asyncio.run(scenario())


def test_tcp_on_an_overlay_bind_cannot_use_the_loopback_token(overlay_host: Served) -> None:
    """The control-socket privilege is not reachable over TCP: the token is refused there.

    Green now and must stay green after the fix.
    """
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    token = (overlay_host.home / "run" / "token").read_text(encoding="utf-8").strip()

    async def scenario() -> tuple[int | None, str | None, list[str]]:
        seen: list[str] = []
        async with connect(overlay_host.url) as ws:
            await ws.send(json.dumps(hello("dev_cli", overlay_host.origin)))
            challenge = json.loads(await asyncio.wait_for(ws.recv(), 5))
            seen.append(str(challenge.get("t")))
            await ws.send(json.dumps({"t": "auth", "token": token}))
            try:
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
                    seen.append(str(frame.get("t")))
            except ConnectionClosed:
                pass
            return ws.close_code, ws.close_reason, seen

    code, reason, seen = asyncio.run(scenario())
    assert seen[0] == "challenge"
    assert (code, reason) == (4001, "unauthorized")
    assert "welcome" not in seen


# --- refusals are not "no host" ---------------------------------------------------------------


@WV
def test_cli_revoke_does_not_claim_success_when_the_host_refuses(loopback_host: Served) -> None:
    """A host answered but refused (here: a wrong token, no control socket): exit non-zero,
    never print ``revoked``."""

    async def paired() -> str:
        device, _key = await pair_over_tcp(loopback_host)
        return device.id

    device_id = asyncio.run(paired())
    control = loopback_host.control
    if control.exists():
        control.unlink()
    (loopback_host.home / "run" / "token").write_text("not-the-token\n", encoding="utf-8")
    done = sevn(loopback_host.home, "devices", "revoke", device_id)
    assert done.returncode != 0, done.stdout + done.stderr
    assert "revoked" not in done.stdout


def test_cli_revoke_writes_offline_when_no_host_answers(tmp_path: Path) -> None:
    """Control for the rule above (green now, stays green): nothing listening -> offline write."""
    home = make_home(tmp_path)
    with serve(home) as served:

        async def paired() -> str:
            device, _key = await pair_over_tcp(served)
            return device.id

        device_id = asyncio.run(paired())
    done = sevn(home, "devices", "revoke", device_id)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"revoked {device_id}" in done.stdout


# --- sevn serve --open on a specific non-loopback bind ----------------------------------------


@WV
def test_serve_open_on_an_overlay_bind_prints_a_pair_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sevn.log
    import uvicorn
    from sevn.cli import app
    from typer.testing import CliRunner

    runs: list[Any] = []
    monkeypatch.setattr(uvicorn, "run", lambda api, **_kwargs: runs.append(api))
    monkeypatch.setattr(sevn.log, "setup", lambda *_args, **_kwargs: None)
    home = make_home(tmp_path, 'allowed_hosts = ["100.101.102.103:8787"]\n')
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_ALLOWED_HOSTS", raising=False)
    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--host",
            "100.101.102.103",
            "--port",
            "8787",
            "--allow-remote-bind",
            "--open",
            "--home",
            str(home),
        ],
    )
    output = result.output + (result.stderr or "")
    assert result.exit_code == 0, output
    assert "sevn pair --scope owner" in output
    assert len(runs) == 1
    assert runs[0].state.sevn.runtime.open_browser is False
