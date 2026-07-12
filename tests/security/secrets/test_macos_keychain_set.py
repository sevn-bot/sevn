"""Unit tests for ``MacOSKeychainBackend.set`` argv shaping (`specs/06-secrets.md` §3.2).

Focus: the ``allow_any_app`` flag must add ``-A`` (no-prompt ACL) for daemon self-unlock, and the
default must keep the restrictive ACL. The ``security`` CLI is mocked so tests run off-Darwin too.
"""

from __future__ import annotations

import asyncio

import pytest

import sevn.security.secrets.backends.macos_keychain as kc
from sevn.security.secrets.backends.macos_keychain import MacOSKeychainBackend


class _FakeProc:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


def _capture_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    async def _fake_exec(*argv: str, **_kwargs: object) -> _FakeProc:
        calls.append(list(argv))
        return _FakeProc()

    # Force the Darwin guard true and stub the subprocess launcher.
    monkeypatch.setattr(kc.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(kc, "_keychain_disabled", lambda: False)
    monkeypatch.setattr(kc.asyncio, "create_subprocess_exec", _fake_exec)
    return calls


async def test_set_allow_any_app_adds_dash_a(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_argv(monkeypatch)
    await MacOSKeychainBackend().set("SEVN_SECRETS_PASSPHRASE", "pw", allow_any_app=True)
    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == "security"
    assert "add-generic-password" in argv
    assert "-A" in argv
    assert "-U" in argv
    # account + value carried through
    assert "SEVN_SECRETS_PASSPHRASE" in argv
    assert "pw" in argv


async def test_set_default_omits_dash_a(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_argv(monkeypatch)
    await MacOSKeychainBackend().set("k", "v")
    assert "-A" not in calls[0]


def test_set_off_darwin_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kc.platform, "system", lambda: "Linux")
    with pytest.raises(NotImplementedError):
        asyncio.run(MacOSKeychainBackend().set("k", "v", allow_any_app=True))
