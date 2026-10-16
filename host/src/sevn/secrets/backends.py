"""Keychain, age-file, and environment secret backends."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import assert_never, cast

import keyring
import keyring.errors

from sevn.config import Settings
from sevn.paths import Paths
from sevn.secrets._age import decrypt, encrypt, generate_identity, recipient_for
from sevn.secrets.errors import SecretBackendReadOnly, SecretNotFound
from sevn.secrets.registry import register

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


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


class KeychainBackend:
    def __init__(self, service: str = "sevn") -> None:
        self._service = service

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self._service, name, value)
        register(name, value)

    def get(self, name: str) -> str:
        value = keyring.get_password(self._service, name)
        if value is None:
            raise SecretNotFound(name)
        register(name, value)
        return value

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self._service, name)
        except keyring.errors.PasswordDeleteError as exc:
            raise SecretNotFound(name) from exc


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


class AgeFileBackend:
    def __init__(self, secrets_file: Path, identity_file: Path) -> None:
        self._secrets_file = secrets_file
        self._identity_file = identity_file

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


def open_backend(settings: Settings, paths: Paths) -> KeychainBackend | AgeFileBackend | EnvBackend:
    choice = settings.secrets.backend
    if choice is None:
        choice = "keychain" if sys.platform == "darwin" else "age-file"
    if choice == "keychain":
        return KeychainBackend()
    if choice == "age-file":
        return AgeFileBackend(paths.secrets_file, paths.keys / "age.key")
    if choice == "env":
        return EnvBackend()
    assert_never(choice)
