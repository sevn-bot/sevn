"""The CLI trusts a control socket only in a private directory it owns (plan 0055 WV F4).

Locked fix: ``sevn.control.client_path(run)`` accepts the pointer target (``run/control``) and
the default ``run/control.sock`` only when the socket's parent is a directory owned by
``os.getuid()`` with no group/other permission bits and the socket is owned by ``os.getuid()``;
otherwise it returns ``None`` and the CLI sends nothing there (no token). This stops a stale
pointer into a re-created shared-temp directory from handing the loopback token to another
local user's listener.

Deterministic without a second uid: permission bits cover the directory rule, and a
monkeypatched ``os.getuid`` covers the owner rule.
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from support.serve import env, sevn, short_root

F4 = pytest.mark.xfail(strict=False, reason="green after WV fix: control pointer ownership")


class _Listener:
    """A stand-in unix listener that records every byte any client sends it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.received = bytearray()
        self.connections = 0
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        self._sock.listen(4)
        self._sock.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                continue
            self.connections += 1
            conn.settimeout(1.0)
            try:
                while chunk := conn.recv(4096):
                    self.received += chunk
            except OSError:
                pass
            finally:
                conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._sock.close()


@contextmanager
def _pointed_home(dir_mode: int, *, pointer: bool = True) -> Iterator[tuple[Path, Path]]:
    """A home whose ``run/`` points at a socket in a directory with ``dir_mode``.

    With ``pointer=False`` the socket is the default ``run/control.sock`` and ``run/`` gets
    ``dir_mode``. Yields ``(home, socket path)``.
    """
    with short_root() as root:
        home = root / "home"
        run = home / "run"
        run.mkdir(parents=True)
        (home / "config.toml").write_text('[secrets]\nbackend = "age-file"\n', encoding="utf-8")
        (run / "token").write_text("canary-token-must-not-leak\n", encoding="utf-8")
        if pointer:
            run.chmod(0o700)
            shared = root / "shared"
            shared.mkdir()
            shared.chmod(dir_mode)
            target = shared / "control.sock"
            (run / "control").write_text(f"{target}\n", encoding="utf-8")
        else:
            run.chmod(dir_mode)
            target = run / "control.sock"
        yield home, target


def _client_path(home: Path) -> Path | None:
    from sevn.control import client_path

    return client_path(home / "run")


# --- client_path ------------------------------------------------------------------------------


@F4
@pytest.mark.parametrize("dir_mode", [0o777, 0o755, 0o750, 0o701], ids=oct)
def test_pointer_into_a_shared_directory_is_ignored(dir_mode: int) -> None:
    with _pointed_home(dir_mode) as (home, target):
        listener = _Listener(target)
        try:
            assert _client_path(home) is None
        finally:
            listener.close()


@F4
@pytest.mark.parametrize("dir_mode", [0o777, 0o755], ids=oct)
def test_default_socket_in_a_shared_run_directory_is_ignored(dir_mode: int) -> None:
    with _pointed_home(dir_mode, pointer=False) as (home, target):
        listener = _Listener(target)
        try:
            assert _client_path(home) is None
        finally:
            listener.close()


@pytest.mark.parametrize("pointer", [True, False], ids=["pointer", "default"])
def test_socket_in_a_private_own_directory_is_accepted(pointer: bool) -> None:
    """Control (passes before and after the fix): a 0700 own directory is trusted."""
    with _pointed_home(0o700, pointer=pointer) as (home, target):
        listener = _Listener(target)
        try:
            assert _client_path(home) == target
        finally:
            listener.close()


@F4
@pytest.mark.parametrize("pointer", [True, False], ids=["pointer", "default"])
def test_socket_owned_by_another_user_is_ignored(
    pointer: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The directory and socket are 0700 but not owned by the caller's uid."""
    with _pointed_home(0o700, pointer=pointer) as (home, target):
        listener = _Listener(target)
        try:
            real = os.getuid()
            monkeypatch.setattr(os, "getuid", lambda: real + 1)
            assert _client_path(home) is None
        finally:
            monkeypatch.undo()
            listener.close()


# --- the CLI sends nothing to an untrusted socket ---------------------------------------------


@F4
@pytest.mark.parametrize("dir_mode", [0o777, 0o755], ids=oct)
@pytest.mark.parametrize(
    "command",
    [
        ("probe", "call", "system.ping", '{"note": "f4", "op_id": "op_f4"}'),
        ("devices", "revoke", "dev_01J00000000000000000000000"),
    ],
    ids=["probe", "devices-revoke"],
)
def test_cli_sends_no_bytes_to_a_stale_pointer(dir_mode: int, command: tuple[str, ...]) -> None:
    with _pointed_home(dir_mode) as (home, target):
        assert env(home)["SEVN_HOME"] == str(home)
        listener = _Listener(target)
        try:
            done = sevn(home, *command, timeout=60)
        finally:
            listener.close()
        assert listener.connections == 0, done.stdout + done.stderr
        assert bytes(listener.received) == b""
        assert b"canary-token-must-not-leak" not in bytes(listener.received)
