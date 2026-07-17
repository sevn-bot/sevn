"""Proton Pass CLI backend tests (``specs/06-secrets.md`` §5.3).

Exports:
    _FakeProc
    test_set_round_trip
    test_set_raises_on_cli_failure
    test_delete_missing_is_idempotent
    test_proton_cli_secrets_subcommands
    test_pass_cli_item_subcommands
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sevn.security.secrets.backends.proton_pass import ProtonPassCliBackend
from sevn.security.secrets.errors import SecretsBackendError


class _FakeProc:
    """Minimal asyncio subprocess stand-in."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin = input
        return self._stdout, self._stderr


@pytest.fixture
def proton_cli(tmp_path: Any) -> str:
    """Fake CLI path registered on PATH via monkeypatch."""
    exe = tmp_path / "proton-pass"
    exe.write_text("", encoding="utf-8")
    return str(exe)


@pytest.mark.anyio
async def test_set_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    proton_cli: str,
) -> None:
    """``set`` shells out with vault + value; ``get`` reads stdout after a successful write."""
    calls: list[list[str]] = []

    async def _fake_exec(*args: str, **kwargs: object) -> _FakeProc:
        _ = kwargs
        argv = list(args)
        calls.append(argv)
        if "set" in argv:
            return _FakeProc(returncode=0)
        if "show" in argv:
            return _FakeProc(returncode=0, stdout=b"secret-value\n")
        return _FakeProc(returncode=1, stderr=b"unexpected")

    monkeypatch.setattr("shutil.which", lambda _name: proton_cli)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    backend = ProtonPassCliBackend(vault="main")
    await backend.set("providers.openai.api_key", "secret-value")
    assert await backend.get("providers.openai.api_key") == "secret-value"
    assert calls[0][:4] == [proton_cli, "--vault", "main", "set"]
    assert calls[0][4:] == ["providers.openai.api_key", "secret-value"]


@pytest.mark.anyio
async def test_set_raises_on_cli_failure(
    monkeypatch: pytest.MonkeyPatch,
    proton_cli: str,
) -> None:
    """Non-zero ``set`` exit raises ``SecretsBackendError``."""

    async def _fake_exec(*args: str, **kwargs: object) -> _FakeProc:
        _ = args, kwargs
        return _FakeProc(returncode=2, stderr=b"boom")

    monkeypatch.setattr("shutil.which", lambda _name: proton_cli)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    backend = ProtonPassCliBackend()
    with pytest.raises(SecretsBackendError, match="set failed"):
        await backend.set("k", "v")


@pytest.mark.anyio
async def test_delete_missing_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    proton_cli: str,
) -> None:
    """``delete`` swallows not-found CLI errors."""

    async def _fake_exec(*args: str, **kwargs: object) -> _FakeProc:
        _ = args, kwargs
        return _FakeProc(returncode=1, stderr=b"item not found")

    monkeypatch.setattr("shutil.which", lambda _name: proton_cli)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    backend = ProtonPassCliBackend()
    await backend.delete("missing-key")


@pytest.mark.anyio
async def test_proton_cli_secrets_subcommands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``proton-cli`` dialect uses ``pass secrets`` argv without plaintext in args.

    Args:
        monkeypatch (pytest.MonkeyPatch): Pytest monkeypatch fixture.
        tmp_path (pathlib.Path): Temporary directory for fake CLI binary.

    Returns:
        None

    Examples:
        >>> True
        True
    """
    exe = tmp_path / "proton-cli"
    exe.write_text("", encoding="utf-8")
    cli = str(exe)
    calls: list[dict[str, object]] = []
    stdin_payloads: list[bytes | None] = []

    async def _fake_exec(*args: str, **kwargs: object) -> _FakeProc:
        calls.append({"args": list(args), "stdin": kwargs.get("stdin")})
        proc = _FakeProc(returncode=0, stdout=b"secret-value\n" if "get" in args else b"")
        original_communicate = proc.communicate

        async def _communicate(input: bytes | None = None) -> tuple[bytes, bytes]:
            stdin_payloads.append(input)
            return await original_communicate(input)

        proc.communicate = _communicate  # type: ignore[method-assign]
        return proc

    monkeypatch.setattr("shutil.which", lambda _name: cli)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    backend = ProtonPassCliBackend(vault="Personal", cli_path="proton-cli")
    assert await backend.get("logical") == "secret-value"
    await backend.set("logical", "pw")
    await backend.delete("logical")
    assert calls[0]["args"] == [cli, "pass", "secrets", "get", "logical", "--vault", "Personal"]
    assert calls[1]["args"] == [cli, "pass", "secrets", "set", "logical", "-", "--vault", "Personal"]
    assert stdin_payloads[1] == b"pw"
    assert calls[2]["args"] == [cli, "pass", "secrets", "delete", "logical", "--vault", "Personal"]


@pytest.mark.anyio
async def test_pass_cli_item_subcommands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """``pass-cli`` dialect uses ``item update`` / ``item delete`` argv."""
    exe = tmp_path / "pass-cli"
    exe.write_text("", encoding="utf-8")
    cli = str(exe)
    calls: list[list[str]] = []

    async def _fake_exec(*args: str, **kwargs: object) -> _FakeProc:
        _ = kwargs
        calls.append(list(args))
        return _FakeProc(returncode=0)

    monkeypatch.setattr("shutil.which", lambda _name: cli)
    monkeypatch.setattr("asyncio.create_subprocess_exec", _fake_exec)

    backend = ProtonPassCliBackend(vault="vault-a", cli_path="pass-cli")
    await backend.set("logical", "pw")
    await backend.delete("logical")
    assert calls[0] == [
        cli,
        "item",
        "update",
        "--vault-name",
        "vault-a",
        "--item-title",
        "logical",
        "--field",
        "password=pw",
    ]
    assert calls[1] == [
        cli,
        "item",
        "delete",
        "--vault-name",
        "vault-a",
        "--item-title",
        "logical",
    ]
