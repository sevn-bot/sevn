"""``sevn devices revoke`` while a host runs cuts the device off at once (plan 0055 D2, §3.0.4).

Locked fix direction (W3 follow-up): when a host answers for the home (``run/token`` and
``run/bind`` present and the socket answers), the CLI revoke calls the host's
``devices.revoke`` over the loopback probe connection, so the hub closes every live session of
that device with 4003 ``revoked``. Only when no host answers does it write ``revoked_at``
offline (``test_revoke_persists_and_cli_revoke_works_offline``).

The device session reaches the real ``sevn serve`` with ``X-Forwarded-For`` set, so it is a
non-loopback session (D4) that must pass the D3 handshake.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from support.pairing import (
    complete_frame,
    fingerprint,
    hello,
    new_device,
    op_id,
    sign_auth,
    unb64u,
    verify_host_sig,
)
from support.repo import repo_root

W3 = pytest.mark.xfail(
    strict=False,
    reason="green after W3 (reconcile: CLI revoke with a running host must go through the hub)",
)

_PROXIED = {"X-Forwarded-For": "100.101.102.103"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SEVN_HOME"] = str(home)
    env["SEVN_SECRETS__BACKEND"] = "age-file"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("SEVN_DEV", None)
    env.pop("SEVN_ALLOWED_HOSTS", None)
    return env


@contextlib.contextmanager
def _serve(home: Path, port: int) -> Iterator[None]:
    log = (home / "serve-test.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "sevn", "serve", "--home", str(home), "--port", str(port)],
        cwd=repo_root(),
        env=_env(home),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            if proc.poll() is not None:
                raise AssertionError((home / "serve-test.log").read_text(encoding="utf-8"))
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.2
                ) as response:
                    if response.status == 200 and (home / "run" / "bind").is_file():
                        break
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise AssertionError("sevn serve did not become healthy")
            time.sleep(0.05)
        yield
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        log.close()


async def _pair(url: str, origin: str, ticket: str) -> tuple[Any, dict[str, Any]]:
    from websockets.asyncio.client import connect

    device = new_device()
    async with connect(url, additional_headers=_PROXIED) as ws:
        await ws.send(json.dumps(hello("dev_unpaired", origin)))
        await ws.send(json.dumps(complete_frame(ticket, device, name="Phone")))
        while True:
            frame = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if frame.get("t") == "paired":
                device.id = frame["device_id"]
                return device, frame


async def _scenario(home: Path, port: int) -> None:
    from sevn.probe import call_method
    from websockets.asyncio.client import connect

    url = f"ws://127.0.0.1:{port}/ws"
    origin = f"ws://127.0.0.1:{port}"
    started = await call_method("pairing.start", {"scope": "member", "op_id": op_id()})
    device, paired = await _pair(url, origin, str(started["ticket"]))
    host_pubkey = unb64u(paired["host_pubkey"])
    async with connect(url, additional_headers=_PROXIED) as ws:
        await ws.send(json.dumps(hello(device.id, origin)))
        challenge = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert challenge["t"] == "challenge", challenge
        nonce = unb64u(challenge["nonce"])
        verify_host_sig(host_pubkey, nonce, origin, challenge["host_sig"])
        sig = sign_auth(device.key, nonce, origin, fingerprint(host_pubkey))
        await ws.send(json.dumps({"t": "auth", "device_sig": sig}))
        welcome = json.loads(await asyncio.wait_for(ws.recv(), 5))
        assert welcome["t"] == "welcome", welcome

        revoke = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "sevn",
            "devices",
            "revoke",
            device.id,
            "--home",
            str(home),
            cwd=repo_root(),
            env=_env(home),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await revoke.communicate()
        assert revoke.returncode == 0, output.decode()
        assert device.id in output.decode()
        # The live session is cut off within one second of the command returning.
        await asyncio.wait_for(ws.wait_closed(), 1.0)
        assert (ws.close_code, ws.close_reason) == (4003, "revoked")

    listed = await call_method("devices.list", {})
    rows = {row["id"]: row for row in listed["devices"]}  # type: ignore[union-attr,index]
    assert rows[device.id]["revoked_at"] is not None  # type: ignore[index]


@W3
def test_cli_revoke_with_host_running_closes_live_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / f"home-{secrets.token_hex(4)}"
    home.mkdir()
    (home / "config.toml").write_text('[secrets]\nbackend = "age-file"\n', encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_DEV", raising=False)
    monkeypatch.delenv("SEVN_ALLOWED_HOSTS", raising=False)
    port = _free_port()
    with _serve(home, port):
        asyncio.run(_scenario(home, port))
