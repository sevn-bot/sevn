"""Secret Service backend, backend selection and ``sevn secret migrate`` (plan 0025 D4, W3).

Default tests never reach D-Bus: ``SecretServiceBackend`` talks to a ``FakeKeyring``
installed with ``sevn.secrets.backends.use_keyring``, and the 2 s collection probe
``sevn.secrets.probe_secret_service`` is patched. Probe tests that need the real
``secretstorage`` module run where it is installed (Linux) and patch its entry points.
"""

from __future__ import annotations

import itertools
import os
import secrets
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_keyring import FakeKeyring
from support.canary import canary

_BUS = "unix:path=/run/user/1000/bus"


# --- arrange -----------------------------------------------------------------


def _home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend: str | None,
    extra_toml: str = "",
) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_WORKSPACES", str(home / "workspaces"))
    monkeypatch.delenv("SEVN_SECRETS__BACKEND", raising=False)
    monkeypatch.delenv("SEVN_DEV", raising=False)
    lines = [] if backend is None else ["[secrets]", f'backend = "{backend}"', ""]
    (home / "config.toml").write_text("\n".join(lines) + extra_toml, encoding="utf-8")
    return home


def _age(home: Path) -> Any:
    from sevn.secrets.backends import AgeFileBackend

    return AgeFileBackend(home / "secrets.age", home / "keys" / "age.key")


def _probe_returns(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> list[tuple[tuple[object, ...], dict[str, object]]]:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake(*args: object, **kwargs: object) -> str:
        calls.append((args, kwargs))
        return state

    monkeypatch.setattr("sevn.secrets.probe_secret_service", fake)
    return calls


def _invoke(args: list[str]) -> Any:
    from sevn.cli import app
    from typer.testing import CliRunner

    return CliRunner().invoke(app, args)


def _out(result: Any) -> str:
    return f"{result.output}\n{getattr(result, 'stderr', '') or ''}"


@pytest.fixture
def fake_keyring() -> Iterator[FakeKeyring]:
    from sevn.secrets.backends import use_keyring

    ring = FakeKeyring()
    use_keyring(ring)
    try:
        yield ring
    finally:
        use_keyring(None)


# --- config ------------------------------------------------------------------


def test_config_accepts_secret_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.config import Settings

    _home(tmp_path, monkeypatch, "secret-service")
    assert Settings.load().secrets.backend == "secret-service"


def test_open_backend_returns_secret_service_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import SecretServiceBackend, open_backend

    _home(tmp_path, monkeypatch, "secret-service")
    _probe_returns(monkeypatch, "unlocked")
    backend = open_backend(Settings.load(), Paths.from_env())
    assert isinstance(backend, SecretServiceBackend)
    value = secrets.token_urlsafe(16)
    backend.set("provider/openai", value)
    assert value in fake_keyring.values()


# --- selection (D4) ----------------------------------------------------------


def _expected(platform: str, dbus: bool, state: str, age: bool) -> str:
    if platform == "darwin":
        return "keychain"
    if age:
        return "age-file"
    if dbus and state == "unlocked":
        return "secret-service"
    return "age-file"


_MATRIX = [
    pytest.param(platform, dbus, state, age, _expected(platform, dbus, state, age), id=case_id)
    for platform, dbus, state, age in itertools.product(
        ("darwin", "linux"), (True, False), ("unlocked", "locked", "unavailable"), (True, False)
    )
    for case_id in [f"{platform}-{'bus' if dbus else 'nobus'}-{state}-{'age' if age else 'noage'}"]
]


@pytest.mark.parametrize(("platform", "dbus", "state", "age", "expected"), _MATRIX)
def test_selection_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    dbus: bool,
    state: str,
    age: bool,
    expected: str,
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets import selected_backend

    home = _home(tmp_path, monkeypatch, None)
    if age:
        _age(home).set("provider/anthropic", secrets.token_urlsafe(16))
    monkeypatch.setattr(sys, "platform", platform)
    if dbus:
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    else:
        monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    calls = _probe_returns(monkeypatch, state)

    assert selected_backend(Settings.load(), Paths.from_env()) == expected
    if platform == "darwin":
        assert calls == [], "the D-Bus probe must not run on macOS"


@pytest.mark.parametrize("configured", ["keychain", "age-file", "env", "secret-service"])
def test_configured_backend_always_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets import selected_backend

    home = _home(tmp_path, monkeypatch, configured)
    _age(home).set("provider/anthropic", secrets.token_urlsafe(16))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    assert selected_backend(Settings.load(), Paths.from_env()) == configured


def test_existing_age_file_is_never_switched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import AgeFileBackend, open_backend

    home = _home(tmp_path, monkeypatch, None)
    old = secrets.token_urlsafe(16)
    _age(home).set("provider/anthropic", old)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")

    backend = open_backend(Settings.load(), Paths.from_env())
    assert isinstance(backend, AgeFileBackend)
    assert backend.get("provider/anthropic") == old

    new = secrets.token_urlsafe(16)
    monkeypatch.setattr("getpass.getpass", lambda *_a, **_k: new)
    result = _invoke(["secret", "set", "provider/openai"])
    assert result.exit_code == 0, _out(result)
    assert _age(home).get("provider/openai") == new
    assert fake_keyring.store == {}


def test_secret_set_pins_the_secret_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets import selected_backend

    home = _home(tmp_path, monkeypatch, None, extra_toml="[http]\nport = 9123\n")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    value = secrets.token_urlsafe(16)
    monkeypatch.setattr("getpass.getpass", lambda *_a, **_k: value)

    result = _invoke(["secret", "set", "provider/openai"])
    assert result.exit_code == 0, _out(result)
    assert 'pinned [secrets] backend = "secret-service"' in _out(result)
    assert value not in _out(result)
    assert value in fake_keyring.values()
    assert not (home / "secrets.age").exists()
    settings = Settings.load()
    assert settings.secrets.backend == "secret-service"
    assert settings.http.port == 9123

    # A later start with a locked keyring keeps the Secret Service (and refuses), instead
    # of selecting a fresh age file.
    _probe_returns(monkeypatch, "locked")
    assert selected_backend(settings, Paths.from_env()) == "secret-service"


@pytest.mark.parametrize(
    "config",
    ["[secrets]", "[secrets] # the store", "[http]\nport = 9123\n[secrets]"],
    ids=["header-only", "header-with-comment", "last-line"],
)
def test_pin_after_an_unterminated_secrets_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring, config: str
) -> None:
    from sevn.config import Settings

    home = _home(tmp_path, monkeypatch, None, extra_toml=config)
    assert not (home / "config.toml").read_text(encoding="utf-8").endswith("\n")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    value = secrets.token_urlsafe(16)
    monkeypatch.setattr("getpass.getpass", lambda *_a, **_k: value)

    result = _invoke(["secret", "set", "provider/openai"])
    assert result.exit_code == 0, _out(result)
    settings = Settings.load()
    assert settings.secrets.backend == "secret-service"
    if "port" in config:
        assert settings.http.port == 9123


# --- backend behaviour -------------------------------------------------------


def test_secret_service_roundtrip_and_names(tmp_path: Path, fake_keyring: FakeKeyring) -> None:
    from sevn.secrets.backends import SecretServiceBackend
    from sevn.secrets.errors import SecretNotFound

    backend = SecretServiceBackend(tmp_path / "home", keyring=fake_keyring)
    first = secrets.token_urlsafe(16)
    second = secrets.token_urlsafe(16)
    backend.set("provider/openai", first)
    backend.set("provider/anthropic", second)
    assert backend.get("provider/openai") == first
    assert backend.names() == ["provider/anthropic", "provider/openai"]

    reopened = SecretServiceBackend(tmp_path / "home", keyring=fake_keyring)
    assert reopened.get("provider/anthropic") == second

    backend.delete("provider/openai")
    assert backend.names() == ["provider/anthropic"]
    with pytest.raises(SecretNotFound, match=r"^secret not found: provider/openai$"):
        backend.get("provider/openai")
    with pytest.raises(SecretNotFound, match=r"^secret not found: provider/openai$"):
        backend.delete("provider/openai")


def test_secret_service_registers_values_for_redaction(
    tmp_path: Path, fake_keyring: FakeKeyring
) -> None:
    from sevn.secrets.backends import SecretServiceBackend
    from sevn.secrets.registry import registered_secrets

    backend = SecretServiceBackend(tmp_path / "home", keyring=fake_keyring)
    value = secrets.token_urlsafe(24)
    backend.set("provider/google", value)
    assert (value, "provider/google") in registered_secrets()


def test_two_homes_do_not_collide(tmp_path: Path, fake_keyring: FakeKeyring) -> None:
    from sevn.secrets.backends import SecretServiceBackend
    from sevn.secrets.errors import SecretNotFound

    first = SecretServiceBackend(tmp_path / "one", keyring=fake_keyring)
    second = SecretServiceBackend(tmp_path / "two", keyring=fake_keyring)
    value_one = secrets.token_urlsafe(16)
    value_two = secrets.token_urlsafe(16)
    first.set("provider/openai", value_one)
    second.set("provider/openai", value_two)
    first.set("only/first", secrets.token_urlsafe(16))

    assert first.get("provider/openai") == value_one
    assert second.get("provider/openai") == value_two
    assert first.names() == ["only/first", "provider/openai"]
    assert second.names() == ["provider/openai"]
    with pytest.raises(SecretNotFound):
        second.get("only/first")

    first.delete("provider/openai")
    assert second.get("provider/openai") == value_two


def test_locked_keyring_raises_secrets_locked(tmp_path: Path, fake_keyring: FakeKeyring) -> None:
    from sevn.secrets.backends import SecretServiceBackend
    from sevn.secrets.errors import SecretNotFound, SecretsLocked

    backend = SecretServiceBackend(tmp_path / "home", keyring=fake_keyring)
    backend.set("provider/openai", secrets.token_urlsafe(16))
    fake_keyring.locked = True
    with pytest.raises(SecretsLocked) as caught:
        backend.get("provider/openai")
    assert caught.value.code == "secrets_locked"
    assert "locked" in str(caught.value)
    assert not isinstance(caught.value, SecretNotFound)


@pytest.mark.parametrize(
    ("state", "code"),
    [("locked", "secrets_locked"), ("unavailable", "secrets_unavailable")],
)
def test_real_keyring_is_never_reached_unless_unlocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, code: str
) -> None:
    from sevn.secrets import backends
    from sevn.secrets.errors import SecretsBackendError

    calls = _probe_returns(monkeypatch, state)

    def no_keyring() -> object:
        raise AssertionError("keyring unlocks a locked collection, which opens a prompt")

    monkeypatch.setattr(backends, "_secret_service_keyring", no_keyring)
    backend = backends.SecretServiceBackend(tmp_path / "home")
    operations: list[Callable[[], object]] = [
        lambda: backend.get("provider/openai"),
        lambda: backend.set("provider/openai", secrets.token_urlsafe(16)),
        lambda: backend.delete("provider/openai"),
        backend.names,
    ]
    for operation in operations:
        with pytest.raises(SecretsBackendError) as caught:
            operation()
        assert caught.value.code == code
    assert len(calls) == len(operations)


def test_real_keyring_is_used_when_unlocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.secrets import backends

    calls = _probe_returns(monkeypatch, "unlocked")
    ring = FakeKeyring()
    monkeypatch.setattr(backends, "_secret_service_keyring", lambda: ring)
    backend = backends.SecretServiceBackend(tmp_path / "home")
    value = secrets.token_urlsafe(16)
    backend.set("provider/openai", value)
    assert backend.get("provider/openai") == value
    assert calls, "every real keyring access checks the lock state first"


class _RaisingKeyring:
    """A keyring whose every call raises ``error``."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def get_password(self, service: str, username: str) -> str | None:
        raise self.error

    def set_password(self, service: str, username: str, password: str) -> None:
        raise self.error

    def delete_password(self, service: str, username: str) -> None:
        raise self.error


def _store_error(kind: str) -> Exception:
    """The raw ``secretstorage`` / ``jeepney`` error that ``keyring`` lets through."""
    exceptions = pytest.importorskip("secretstorage.exceptions")
    if kind == "dbus":
        wrappers = pytest.importorskip("jeepney.wrappers")

        class ServiceUnknown(wrappers.DBusErrorResponse):
            def __init__(self) -> None:
                # The fields DBusErrorResponse reads from the reply message.
                self.name = "org.freedesktop.DBus.Error.ServiceUnknown"
                self.data = ("The name is not activatable",)

        return ServiceUnknown()
    classes = {
        "locked": exceptions.LockedException,
        "dismissed": exceptions.PromptDismissedException,
        "not-available": exceptions.SecretServiceNotAvailableException,
    }
    return classes[kind]("raised by the Secret Service")


def _operations(backend: Any, value: str) -> list[Callable[[], object]]:
    return [
        lambda: backend.get("provider/openai"),
        lambda: backend.set("provider/openai", value),
        lambda: backend.delete("provider/openai"),
        backend.names,
    ]


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("locked", "secrets_locked"),
        ("dismissed", "secrets_locked"),
        ("not-available", "secrets_unavailable"),
        ("dbus", "secrets_unavailable"),
    ],
)
def test_secret_service_store_errors_are_typed(tmp_path: Path, kind: str, code: str) -> None:
    from sevn.secrets.backends import SecretServiceBackend
    from sevn.secrets.errors import SecretsBackendError

    error = _store_error(kind)
    backend = SecretServiceBackend(tmp_path / "home", keyring=_RaisingKeyring(error))
    value = secrets.token_urlsafe(16)
    for operation in _operations(backend, value):
        with pytest.raises(SecretsBackendError) as caught:
            operation()
        assert caught.value.code == code
        assert value not in str(caught.value)


def _keychain_fails(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    import keyring

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, fail)


def _keyring_error(kind: str) -> Exception:
    import keyring.errors

    if kind == "locked":
        return keyring.errors.KeyringLocked("Can't get password from keychain: locked")
    if kind == "init":
        return keyring.errors.InitError("no keychain")
    return OSError(5, "Input/output error")


@pytest.mark.parametrize(
    ("kind", "code"),
    [("locked", "secrets_locked"), ("init", "secrets_unavailable"), ("os", "secrets_unavailable")],
)
def test_keychain_errors_are_typed(monkeypatch: pytest.MonkeyPatch, kind: str, code: str) -> None:
    from sevn.secrets.backends import KeychainBackend
    from sevn.secrets.errors import SecretsBackendError

    _keychain_fails(monkeypatch, _keyring_error(kind))
    backend = KeychainBackend(service=f"sevn-test-{secrets.token_hex(4)}")
    value = secrets.token_urlsafe(16)
    for operation in _operations(backend, value):
        with pytest.raises(SecretsBackendError) as caught:
            operation()
        assert caught.value.code == code
        assert value not in str(caught.value)


def test_keychain_delete_of_a_missing_secret_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import keyring.errors
    from sevn.secrets.backends import KeychainBackend
    from sevn.secrets.errors import SecretNotFound

    _keychain_fails(monkeypatch, keyring.errors.PasswordDeleteError("not found"))
    with pytest.raises(SecretNotFound):
        KeychainBackend(service=f"sevn-test-{secrets.token_hex(4)}").delete("provider/openai")


@pytest.mark.parametrize(
    "args",
    [
        ["secret", "list"],
        ["secret", "rm", "provider/openai"],
        ["secret", "migrate", "--to", "age-file"],
    ],
    ids=["list", "rm", "migrate"],
)
def test_locked_keychain_cli_answers_secrets_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    home = _home(tmp_path, monkeypatch, None)
    monkeypatch.setattr(sys, "platform", "darwin")
    _keychain_fails(monkeypatch, _keyring_error("locked"))

    result = _invoke(args)
    assert result.exit_code == 1, _out(result)
    assert isinstance(result.exception, SystemExit), result.exception
    assert "secrets_locked" in _out(result)
    assert "Traceback" not in _out(result)
    assert not (home / "secrets.age").exists()


# --- startup refusal ---------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.parametrize(
    ("state", "code"),
    [("locked", "secrets_locked"), ("unavailable", "secrets_unavailable")],
)
def test_locked_collection_refuses_start_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring: FakeKeyring,
    state: str,
    code: str,
) -> None:
    _home(tmp_path, monkeypatch, "secret-service")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, state)
    served: list[object] = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: served.append(args))

    result = _invoke(["serve", "--port", str(_free_port())])
    assert result.exit_code == 1, _out(result)
    assert code in _out(result)
    assert served == []


def test_unlocked_collection_starts_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    # Guards the refusal above against refusing unconditionally.
    _home(tmp_path, monkeypatch, "secret-service")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    served: list[object] = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: served.append(args))

    result = _invoke(["serve", "--port", str(_free_port())])
    assert result.exit_code == 0, _out(result)
    assert len(served) == 1


# --- migrate -----------------------------------------------------------------


def _seed_age_home(home: Path, count: int = 2) -> dict[str, str]:
    from sevn.identity import load_or_create

    backend = _age(home)
    seeded: dict[str, str] = {}
    for index in range(count):
        name = f"provider/test{index}"
        value = secrets.token_urlsafe(24)
        backend.set(name, value)
        seeded[name] = value
    load_or_create(backend)
    seeded["host/identity"] = backend.get("host/identity")
    return seeded


def test_migrate_copies_verifies_then_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    from sevn.config import Settings
    from sevn.identity import load_or_create
    from sevn.log import logger
    from sevn.secrets.backends import SecretServiceBackend

    home = _home(tmp_path, monkeypatch, "age-file", extra_toml="[http]\nport = 9123\n")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    seeded = _seed_age_home(home)
    host_id = load_or_create(_age(home)).host_id

    with canary() as probe:
        seeded[probe.name] = probe.value
        sink: list[str] = []
        sink_id = logger.add(lambda message: sink.append(str(message)))
        try:
            result = _invoke(["secret", "migrate", "--to", "secret-service"])
        finally:
            logger.remove(sink_id)
        assert result.exit_code == 0, _out(result)
        for value in seeded.values():
            assert value not in _out(result)
            assert value not in "\n".join(sink)
        probe.assert_absent(probe.value)

    target = SecretServiceBackend(home)
    for name, value in seeded.items():
        assert target.get(name) == value
    assert load_or_create(target).host_id == host_id
    settings = Settings.load()
    assert settings.secrets.backend == "secret-service"
    assert settings.http.port == 9123
    assert _age(home).names() == []


@pytest.mark.parametrize("failure", ["write", "read-back"])
def test_migrate_failure_keeps_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring: FakeKeyring,
    failure: str,
) -> None:
    from sevn.config import Settings

    home = _home(tmp_path, monkeypatch, "age-file")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    seeded = _seed_age_home(home, count=3)
    if failure == "write":
        fake_keyring.fail_set.add("provider/test1")
    else:
        fake_keyring.wrong_read.add("provider/test1")

    with canary() as probe:
        seeded[probe.name] = probe.value
        result = _invoke(["secret", "migrate", "--to", "secret-service"])
        assert result.exit_code == 1, _out(result)
        assert "provider/test1" in _out(result)
        for value in seeded.values():
            assert value not in _out(result)
        probe.assert_absent(probe.value)

    source = _age(home)
    for name, value in seeded.items():
        assert source.get(name) == value
    assert Settings.load().secrets.backend == "age-file"


@pytest.mark.parametrize(
    ("state", "code"),
    [("locked", "secrets_locked"), ("unavailable", "secrets_unavailable")],
)
def test_migrate_refuses_an_unreachable_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring: FakeKeyring,
    state: str,
    code: str,
) -> None:
    from sevn.config import Settings

    home = _home(tmp_path, monkeypatch, "age-file")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, state)
    seeded = _seed_age_home(home)

    result = _invoke(["secret", "migrate", "--to", "secret-service"])
    assert result.exit_code == 1, _out(result)
    assert code in _out(result)
    assert fake_keyring.store == {}
    assert _age(home).names() == sorted(seeded)
    assert Settings.load().secrets.backend == "age-file"


def test_migrate_back_to_age_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    from sevn.config import Settings
    from sevn.secrets.backends import SecretServiceBackend

    home = _home(tmp_path, monkeypatch, "secret-service")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    source = SecretServiceBackend(home)
    seeded = {f"provider/test{index}": secrets.token_urlsafe(24) for index in range(3)}
    for name, value in seeded.items():
        source.set(name, value)

    result = _invoke(["secret", "migrate", "--to", "age-file"])
    assert result.exit_code == 0, _out(result)
    target = _age(home)
    for name, value in seeded.items():
        assert target.get(name) == value
        assert value not in fake_keyring.values()
    assert SecretServiceBackend(home).names() == []
    assert Settings.load().secrets.backend == "age-file"


@pytest.mark.parametrize("existing_age", [False, True], ids=["new-age-file", "existing-age-file"])
def test_failed_migrate_to_age_file_leaves_no_new_age_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring: FakeKeyring,
    existing_age: bool,
) -> None:
    from sevn.config import Settings
    from sevn.secrets.backends import AgeFileBackend, SecretServiceBackend

    home = _home(tmp_path, monkeypatch, "secret-service")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    _probe_returns(monkeypatch, "unlocked")
    source = SecretServiceBackend(home)
    seeded = {f"provider/test{index}": secrets.token_urlsafe(24) for index in range(3)}
    for name, value in seeded.items():
        source.set(name, value)
    kept = secrets.token_urlsafe(24)
    if existing_age:
        _age(home).set("other/kept", kept)
    real_set = AgeFileBackend.set

    def failing_set(self: AgeFileBackend, name: str, value: str) -> None:
        if name == "provider/test1":
            raise OSError(28, "No space left on device")
        real_set(self, name, value)

    monkeypatch.setattr(AgeFileBackend, "set", failing_set)

    result = _invoke(["secret", "migrate", "--to", "age-file"])
    assert result.exit_code == 1, _out(result)
    assert "provider/test1" in _out(result)
    assert "nothing was changed" in _out(result)
    if existing_age:
        assert _age(home).names() == ["other/kept"]
        assert _age(home).get("other/kept") == kept
    else:
        assert not (home / "secrets.age").exists()
        assert not (home / "keys" / "age.key").exists()
    for name, value in seeded.items():
        assert source.get(name) == value
    assert Settings.load().secrets.backend == "secret-service"


def test_migrate_to_the_current_backend_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring
) -> None:
    home = _home(tmp_path, monkeypatch, "age-file")
    seeded = _seed_age_home(home)
    result = _invoke(["secret", "migrate", "--to", "age-file"])
    assert result.exit_code == 1, _out(result)
    assert "already using age-file" in _out(result)
    assert _age(home).names() == sorted(seeded)


@pytest.mark.parametrize("target", ["env", "keychain", "vault"])
def test_migrate_rejects_other_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keyring: FakeKeyring, target: str
) -> None:
    from sevn.config import Settings

    home = _home(tmp_path, monkeypatch, "age-file")
    seeded = _seed_age_home(home)
    result = _invoke(["secret", "migrate", "--to", target])
    assert result.exit_code != 0, _out(result)
    assert _age(home).names() == sorted(seeded)
    assert Settings.load().secrets.backend == "age-file"
    assert fake_keyring.store == {}


# --- the 2 s probe (W0.4 facts) ----------------------------------------------


def test_probe_without_a_bus_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.secrets import probe_secret_service

    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    started = time.monotonic()
    assert probe_secret_service() == "unavailable"
    assert time.monotonic() - started < 2.5


def test_probe_with_a_stale_socket_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.secrets import probe_secret_service

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path / 'gone'}")
    started = time.monotonic()
    assert probe_secret_service() == "unavailable"
    assert time.monotonic() - started < 2.5


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _patch_secretstorage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dbus_init: Callable[[], object],
    locked: bool = False,
) -> None:
    secretstorage = pytest.importorskip("secretstorage")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", _BUS)
    monkeypatch.setattr(secretstorage, "dbus_init", dbus_init)

    class FakeCollection:
        def __init__(self, connection: object, *_args: object, **_kwargs: object) -> None:
            self.connection = connection

        def is_locked(self) -> bool:
            return locked

        def unlock(self, *_args: object, **_kwargs: object) -> bool:
            raise AssertionError("the probe must never unlock (that opens a prompt)")

    monkeypatch.setattr(secretstorage, "Collection", FakeCollection)

    def no_keyring(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the probe must not go through keyring")

    monkeypatch.setattr(
        "keyring.backends.SecretService.Keyring.get_preferred_collection", no_keyring
    )


@pytest.mark.parametrize(("locked", "expected"), [(False, "unlocked"), (True, "locked")])
def test_probe_reads_the_lock_state_without_prompting(
    monkeypatch: pytest.MonkeyPatch, locked: bool, expected: str
) -> None:
    from sevn.secrets import probe_secret_service

    connection = _FakeConnection()
    _patch_secretstorage(monkeypatch, dbus_init=lambda: connection, locked=locked)
    assert probe_secret_service() == expected
    assert connection.closed


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(2, "No such file or directory"),
        ConnectionRefusedError(111, "Connection refused"),
    ],
    ids=["stale-socket", "refused"],
)
def test_probe_maps_raw_os_errors_to_unavailable(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    from sevn.secrets import probe_secret_service

    def broken() -> object:
        raise error

    _patch_secretstorage(monkeypatch, dbus_init=broken)
    assert probe_secret_service() == "unavailable"


def test_probe_maps_secretstorage_errors_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.secrets import probe_secret_service

    secretstorage = pytest.importorskip("secretstorage")

    def broken() -> object:
        raise secretstorage.exceptions.SecretServiceNotAvailableException("no bus")

    _patch_secretstorage(monkeypatch, dbus_init=broken)
    assert probe_secret_service() == "unavailable"


def test_probe_is_bounded_when_the_bus_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.secrets import probe_secret_service

    release = threading.Event()

    def hang() -> object:
        release.wait(10)
        return _FakeConnection()

    _patch_secretstorage(monkeypatch, dbus_init=hang)
    started = time.monotonic()
    try:
        assert probe_secret_service(timeout=0.3) == "unavailable"
        assert time.monotonic() - started < 2.0
    finally:
        release.set()


# --- live --------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.session_bus
def test_live_secret_service_roundtrip(tmp_path: Path) -> None:
    if not sys.platform.startswith("linux") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        pytest.skip("needs a Linux desktop session bus")
    from sevn.secrets import probe_secret_service
    from sevn.secrets.backends import SecretServiceBackend

    if probe_secret_service() != "unlocked":
        pytest.skip("no unlocked Secret Service collection")
    backend = SecretServiceBackend(tmp_path / "live-home")
    value = secrets.token_urlsafe(16)
    name = "canary/live-roundtrip"
    try:
        backend.set(name, value)
        assert backend.get(name) == value
        assert name in backend.names()
    finally:
        backend.delete(name)
    assert name not in backend.names()


# --- isolation guard (W3.R) --------------------------------------------------

_BUS_AT_IMPORT = os.environ.get("DBUS_SESSION_BUS_ADDRESS")


def test_tests_never_see_the_real_session_bus() -> None:
    assert "DBUS_SESSION_BUS_ADDRESS" not in os.environ


@pytest.mark.session_bus
def test_session_bus_marker_keeps_the_real_variable() -> None:
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS") == _BUS_AT_IMPORT
