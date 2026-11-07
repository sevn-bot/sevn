"""Keychain, Secret Service, age-file, and environment secret backends."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, assert_never, cast

import keyring
import keyring.errors

import sevn.secrets
from sevn.config import BackendName, Settings
from sevn.paths import Paths
from sevn.secrets import selected_backend
from sevn.secrets._age import decrypt, encrypt, generate_identity, recipient_for
from sevn.secrets.errors import (
    SecretBackendReadOnly,
    SecretNotFound,
    SecretsLocked,
    SecretsUnavailable,
)
from sevn.secrets.registry import register

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_KEYCHAIN_INDEX = "sevn.names"


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written == 0:
            raise OSError("failed to write secret file")
        view = view[written:]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        tmp_path.unlink(missing_ok=True)
        raise
    os.close(descriptor)
    try:
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)


def _store_errors(module: str, *names: str) -> tuple[type[Exception], ...]:
    """The named exception classes of ``module``, or none when it is not installed.

    ``secretstorage`` and ``jeepney`` come with ``keyring`` on Linux only.
    """
    try:
        loaded = importlib.import_module(module)
    except ImportError:
        return ()
    found: list[type[Exception]] = []
    for name in names:
        value: object = getattr(loaded, name, None)
        if isinstance(value, type) and issubclass(value, Exception):
            found.append(value)
    return tuple(found)


# ``keyring``'s Secret Service backend lets these through untranslated: the collection
# stayed locked (a dismissed or refused unlock), or D-Bus answered with an error.
_LOCKED_STORE_ERRORS = _store_errors(
    "secretstorage.exceptions", "LockedException", "PromptDismissedException"
)
_FAILED_STORE_ERRORS = _store_errors(
    "secretstorage.exceptions", "SecretStorageException"
) + _store_errors("jeepney.wrappers", "DBusErrorResponse")


def _translate[T](operation: Callable[[], T], store: str, action: str, locked: str) -> T:
    """Run one keyring operation; its failures become typed errors that never hold a value."""
    try:
        return operation()
    except keyring.errors.PasswordDeleteError as exc:
        raise _Missing from exc
    except (keyring.errors.KeyringLocked, *_LOCKED_STORE_ERRORS) as exc:
        raise SecretsLocked(locked) from exc
    except (keyring.errors.KeyringError, RuntimeError, OSError, *_FAILED_STORE_ERRORS) as exc:
        raise SecretsUnavailable(f"the {store} {action} failed ({type(exc).__name__})") from exc


class KeychainBackend:
    """Secrets in the macOS keychain through ``keyring``.

    A locked keychain raises :class:`SecretsLocked`; any other keyring failure raises
    :class:`SecretsUnavailable`. Neither message ever contains a value.
    """

    def __init__(self, service: str = "sevn") -> None:
        self._service = service

    def set(self, name: str, value: str) -> None:
        self._call(lambda: keyring.set_password(self._service, name, value), "write")
        register(name, value)
        if name == _KEYCHAIN_INDEX:
            return
        found = [item for item in self.names() if item != name]
        found.append(name)
        self._store_names(sorted(found))

    def get(self, name: str) -> str:
        value = self._call(lambda: keyring.get_password(self._service, name), "read")
        if value is None:
            raise SecretNotFound(name)
        register(name, value)
        return value

    def delete(self, name: str) -> None:
        if not self._delete_item(name):
            raise SecretNotFound(name)
        if name == _KEYCHAIN_INDEX:
            return
        self._store_names([item for item in self.names() if item != name])

    def names(self) -> list[str]:
        raw = self._call(lambda: keyring.get_password(self._service, _KEYCHAIN_INDEX), "read")
        if raw is None or raw == "":
            return []
        return _decode_names(raw)

    def _store_names(self, names: list[str]) -> None:
        if not names:
            self._delete_item(_KEYCHAIN_INDEX)
            return
        payload = json.dumps(names)
        self._call(lambda: keyring.set_password(self._service, _KEYCHAIN_INDEX, payload), "write")

    def _delete_item(self, name: str) -> bool:
        """Delete one keychain item; ``False`` means it was not there.

        ``keyring``'s macOS backend raises the same error for a missing item and for a locked
        keychain, so a read tells them apart: it fails on a locked keychain and finds nothing
        when the item is gone.
        """
        try:
            self._call(lambda: keyring.delete_password(self._service, name), "delete")
        except _Missing as exc:
            if self._call(lambda: keyring.get_password(self._service, name), "read") is None:
                return False
            raise SecretsUnavailable("the keychain delete failed") from exc
        return True

    def _call[T](self, operation: Callable[[], T], action: str) -> T:
        return _translate(operation, "keychain", action, "the keychain is locked")


class KeyringAPI(Protocol):
    """The slice of a ``keyring`` backend that :class:`SecretServiceBackend` uses."""

    def get_password(self, service: str, username: str, /) -> str | None: ...

    def set_password(self, service: str, username: str, password: str, /) -> None: ...

    def delete_password(self, service: str, username: str, /) -> None: ...


_keyring_override: KeyringAPI | None = None


def use_keyring(ring: KeyringAPI | None) -> None:
    """Route every :class:`SecretServiceBackend` without its own keyring to ``ring``.

    ``None`` restores the real Secret Service keyring. Tests install a fake here.
    """
    global _keyring_override
    _keyring_override = ring


def _secret_service_keyring() -> KeyringAPI:
    from keyring.backends.SecretService import Keyring

    return Keyring()


def _require_unlocked_collection() -> None:
    """Refuse before ``keyring`` touches a locked or missing collection.

    ``keyring`` unlocks a locked collection on access, which on a desktop opens a prompt and
    blocks until it is answered. The bounded probe reads the lock state without unlocking.
    """
    state = sevn.secrets.probe_secret_service()
    if state == "locked":
        raise SecretsLocked
    if state == "unavailable":
        raise SecretsUnavailable("no Secret Service answered on the session bus")


def home_key(home: Path) -> str:
    """A short, stable id for one sevn home, so two homes never share Secret Service items."""
    digest = hashlib.sha256(str(home.expanduser().resolve()).encode("utf-8")).hexdigest()
    return digest[:16]


class SecretServiceBackend:
    """Secrets in the desktop keyring through ``keyring``'s Secret Service backend (D4).

    Items are stored under the service ``sevn:<home hash>``, so the home is part of the
    ``(service, username)`` key. A locked collection raises :class:`SecretsLocked`; a missing
    daemon or a refused operation raises :class:`SecretsUnavailable`. Neither message ever
    contains a value.
    """

    def __init__(self, home: Path, *, keyring: KeyringAPI | None = None) -> None:
        self._service = f"sevn:{home_key(home)}"
        self._keyring = keyring

    @property
    def service(self) -> str:
        return self._service

    def set(self, name: str, value: str) -> None:
        self._call(lambda ring: ring.set_password(self._service, name, value), "write")
        register(name, value)
        if name == _KEYCHAIN_INDEX:
            return
        found = [item for item in self.names() if item != name]
        found.append(name)
        self._store_names(sorted(found))

    def get(self, name: str) -> str:
        value = self._call(lambda ring: ring.get_password(self._service, name), "read")
        if value is None:
            raise SecretNotFound(name)
        register(name, value)
        return value

    def delete(self, name: str) -> None:
        try:
            self._call(lambda ring: ring.delete_password(self._service, name), "delete")
        except _Missing as exc:
            raise SecretNotFound(name) from exc
        if name == _KEYCHAIN_INDEX:
            return
        self._store_names([item for item in self.names() if item != name])

    def names(self) -> list[str]:
        raw = self._call(lambda ring: ring.get_password(self._service, _KEYCHAIN_INDEX), "read")
        if raw is None or raw == "":
            return []
        return _decode_names(raw)

    def _store_names(self, names: list[str]) -> None:
        if not names:
            try:
                self._call(
                    lambda ring: ring.delete_password(self._service, _KEYCHAIN_INDEX), "delete"
                )
            except _Missing:
                return
            return
        payload = json.dumps(names)
        self._call(lambda ring: ring.set_password(self._service, _KEYCHAIN_INDEX, payload), "write")

    def _ring(self) -> KeyringAPI:
        if self._keyring is not None:
            return self._keyring
        if _keyring_override is not None:
            return _keyring_override
        _require_unlocked_collection()
        return _secret_service_keyring()

    def _call[T](self, operation: Callable[[KeyringAPI], T], action: str) -> T:
        return _translate(
            lambda: operation(self._ring()),
            "Secret Service",
            action,
            "the Secret Service collection is locked",
        )


class _Missing(Exception):
    """``delete_password`` found no item."""


class EnvBackend:
    def get(self, name: str) -> str:
        value = os.environ.get("SEVN_SECRET_" + name.upper())
        if value is None:
            raise SecretNotFound(name)
        register(name, value)
        return value

    def set(self, name: str, value: str) -> None:
        raise SecretBackendReadOnly(name)

    def delete(self, name: str) -> None:
        raise SecretBackendReadOnly(name)

    def names(self) -> list[str]:
        prefix = "SEVN_SECRET_"
        return sorted(key.removeprefix(prefix) for key in os.environ if key.startswith(prefix))


class AgeFileBackend:
    def __init__(self, secrets_file: Path, identity_file: Path) -> None:
        self._secrets_file = secrets_file
        self._identity_file = identity_file

    @property
    def files(self) -> tuple[Path, Path]:
        """The secrets file and the age identity that encrypts it."""
        return self._secrets_file, self._identity_file

    def set(self, name: str, value: str) -> None:
        with _path_lock(self._secrets_file):
            data = self._read()
            data[name] = value
            self._write(data)
        register(name, value)

    def get(self, name: str) -> str:
        with _path_lock(self._secrets_file):
            data = self._read()
            try:
                value = data[name]
            except KeyError:
                raise SecretNotFound(name) from None
        register(name, value)
        return value

    def delete(self, name: str) -> None:
        with _path_lock(self._secrets_file):
            data = self._read()
            if name not in data:
                raise SecretNotFound(name)
            del data[name]
            self._write(data)

    def names(self) -> list[str]:
        with _path_lock(self._secrets_file):
            return sorted(self._read())

    def _identity(self) -> tuple[str, str]:
        path = self._identity_file
        if path.is_file():
            secret = path.read_text(encoding="utf-8").strip()
        else:
            secret = ""
        if not secret:
            secret = generate_identity()
            _atomic_write(path, (secret + "\n").encode("ascii"))
        return secret, recipient_for(secret)

    def _read(self) -> dict[str, str]:
        if not self._secrets_file.is_file():
            return {}
        secret, _recipient = self._identity()
        plaintext = decrypt(self._secrets_file.read_bytes(), secret)
        return _parse_secret_map(plaintext)

    def _write(self, data: dict[str, str]) -> None:
        _secret, recipient = self._identity()
        payload = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        _atomic_write(self._secrets_file, encrypt(payload, recipient))


def _object_dict(value: object) -> dict[object, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[object, object], value)


def _decode_names(raw: str) -> list[str]:
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    names: list[str] = []
    for item in cast("list[object]", parsed):
        if isinstance(item, str) and item != "":
            names.append(item)
    return names


def _parse_secret_map(plaintext: bytes) -> dict[str, str]:
    parsed = _object_dict(json.loads(plaintext.decode("utf-8")))
    if parsed is None:
        raise ValueError("secrets.age does not contain an object")
    values: dict[str, str] = {}
    for key, item in parsed.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError("secrets.age values must be strings")
        values[key] = item
    return values


type SecretBackend = KeychainBackend | SecretServiceBackend | AgeFileBackend | EnvBackend


def backend_named(name: BackendName, paths: Paths) -> SecretBackend:
    """The backend called ``name`` for the home in ``paths``."""
    if name == "keychain":
        return KeychainBackend()
    if name == "secret-service":
        return SecretServiceBackend(paths.home)
    if name == "age-file":
        return AgeFileBackend(paths.secrets_file, paths.keys / "age.key")
    if name == "env":
        return EnvBackend()
    assert_never(name)


def open_backend(settings: Settings, paths: Paths) -> SecretBackend:
    """The backend :func:`sevn.secrets.selected_backend` picks for this host."""
    return backend_named(selected_backend(settings, paths), paths)
