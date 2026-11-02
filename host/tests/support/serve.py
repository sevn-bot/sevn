"""Run a real ``sevn serve`` subprocess for CLI / control-socket tests (plan 0055 WV fix).

Product imports stay inside functions so collection works before the fix exists.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support.pairing import (
    Device,
    complete_frame,
    fingerprint,
    hello,
    new_device,
    sign_auth,
    unb64u,
)
from support.repo import repo_root

CROCKFORD_CODE = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{8}\b")


@dataclass
class Served:
    home: Path
    host: str
    port: int
    proc: subprocess.Popen[str]

    @property
    def name(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return f"ws://{self.name}/ws"

    @property
    def origin(self) -> str:
        return f"ws://{self.name}"

    @property
    def device_headers(self) -> dict[str, str]:
        """On a loopback bind a device session needs a proxy header to be non-loopback (D4)."""
        return {"X-Forwarded-For": "100.101.102.103"} if self.host == "127.0.0.1" else {}

    @property
    def control(self) -> Path:
        return self.home / "run" / "control.sock"


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def overlay_ip() -> str | None:
    """This machine's own non-loopback IPv4 (stands in for a NetBird/ZeroTier/WireGuard address).

    A UDP ``connect`` only picks a route; it sends nothing.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))
            found = str(sock.getsockname()[0])
        except OSError:
            return None
    address = ipaddress.ip_address(found)
    if address.is_loopback or address.is_unspecified:
        return None
    try:
        free_port(found)
    except OSError:
        return None
    return found


def env(home: Path) -> dict[str, str]:
    values = os.environ.copy()
    values["SEVN_HOME"] = str(home)
    values["SEVN_SECRETS__BACKEND"] = "age-file"
    values["PYTHONUNBUFFERED"] = "1"
    values.pop("SEVN_DEV", None)
    values.pop("SEVN_ALLOWED_HOSTS", None)
    return values


@contextlib.contextmanager
def short_root() -> Iterator[Path]:
    """A short temporary directory: ``<home>/run/control.sock`` must fit AF_UNIX's path limit
    (104 bytes on macOS), which pytest's ``tmp_path`` exceeds."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="sv-", dir="/tmp"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def make_home(root: Path, http: str = "") -> Path:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        f'[secrets]\nbackend = "age-file"\n\n[http]\n{http}', encoding="utf-8"
    )
    return home


@contextlib.contextmanager
def serve(home: Path, host: str = "127.0.0.1", port: int | None = None) -> Iterator[Served]:
    bound = free_port(host) if port is None else port
    args = [sys.executable, "-m", "sevn", "serve", "--home", str(home), "--host", host]
    args += ["--port", str(bound)]
    if host != "127.0.0.1":
        args.append("--allow-remote-bind")
    log = (home / "serve-test.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        args,
        cwd=repo_root(),
        env=env(home),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    served = Served(home=home, host=host, port=bound, proc=proc)
    try:
        _wait_ready(served)
        yield served
    finally:
        stop(served)
        log.close()


def stop(served: Served) -> None:
    proc = served.proc
    if proc.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


def _wait_ready(served: Served) -> None:
    deadline = time.monotonic() + 20
    url = f"http://{served.name}/health"
    while True:
        if served.proc.poll() is not None:
            raise AssertionError((served.home / "serve-test.log").read_text(encoding="utf-8"))
        try:
            request = urllib.request.Request(url, headers={"Host": served.name})
            with urllib.request.urlopen(request, timeout=0.3) as response:  # noqa: S310
                if response.status == 200 and (served.home / "run" / "bind").is_file():
                    return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise AssertionError("sevn serve did not become healthy")
        time.sleep(0.05)


def sevn(home: Path, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "sevn", *args, "--home", str(home)],
        cwd=repo_root(),
        env=env(home),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def short_code(home: Path) -> str:
    minted = sevn(home, "pair", "--scope", "member")
    assert minted.returncode == 0, minted.stdout + minted.stderr
    text = "\n".join(line for line in minted.stdout.splitlines() if "sevn://" not in line)
    found = CROCKFORD_CODE.search(text)
    assert found is not None, minted.stdout
    return found.group(0)


async def pair_over_tcp(served: Served) -> tuple[Device, bytes]:
    """Pair a new device over the host's TCP listener; returns it and the host public key."""
    from websockets.asyncio.client import connect

    code = short_code(served.home)
    device = new_device()
    async with connect(served.url, additional_headers=served.device_headers) as ws:
        await ws.send(json.dumps(hello("dev_unpaired", served.origin)))
        await ws.send(json.dumps(complete_frame(code, device, name="Phone")))
        while True:
            frame: dict[str, Any] = json.loads(await ws.recv())
            if frame.get("t") == "paired":
                device.id = str(frame["device_id"])
                return device, unb64u(str(frame["host_pubkey"]))


async def device_session(served: Served, device: Device, host_pubkey: bytes) -> Any:
    """An authenticated device session over TCP (the caller closes it)."""
    import asyncio

    from websockets.asyncio.client import connect

    ws = await connect(served.url, additional_headers=served.device_headers)
    await ws.send(json.dumps(hello(device.id, served.origin)))
    challenge = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert challenge["t"] == "challenge", challenge
    nonce = unb64u(challenge["nonce"])
    sig = sign_auth(device.key, nonce, served.origin, fingerprint(host_pubkey))
    await ws.send(json.dumps({"t": "auth", "device_sig": sig}))
    welcome = json.loads(await asyncio.wait_for(ws.recv(), 5))
    assert welcome["t"] == "welcome", welcome
    return ws
