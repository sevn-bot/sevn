"""Secret backends and host identity (D16, D13)."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import re
import secrets
import sys
from pathlib import Path

import pytest


def _host_id(pubkey: bytes) -> str:
    encoded = base64.b32encode(hashlib.sha256(pubkey).digest()).decode("ascii")
    return "host_" + encoded.rstrip("=").lower()[:26]


def _fingerprint(pubkey: bytes) -> str:
    digest = hashlib.sha256(pubkey).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")


def _age_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, Path]:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    (tmp_path / "config.toml").write_text('[secrets]\nbackend = "age-file"\n', encoding="utf-8")
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    paths = Paths.from_env()
    return open_backend(Settings.load(), paths), paths.secrets_file


def test_age_file_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.secrets.errors import SecretNotFound

    backend, secrets_file = _age_backend(tmp_path, monkeypatch)
    value = secrets.token_urlsafe(32)
    backend.set("a/b", value)  # type: ignore[attr-defined]
    assert backend.get("a/b") == value  # type: ignore[attr-defined]
    mode = secrets_file.stat().st_mode & 0o777
    assert mode == 0o600
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert value.encode() not in path.read_bytes()
    backend.delete("a/b")  # type: ignore[attr-defined]
    with pytest.raises(SecretNotFound, match=r"^secret not found: a/b$"):
        backend.get("a/b")  # type: ignore[attr-defined]


def test_env_backend_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.secrets.backends import EnvBackend
    from sevn.secrets.errors import SecretBackendReadOnly

    monkeypatch.setenv("SEVN_SECRET_FOO", "bar")
    backend = EnvBackend()
    assert backend.get("foo") == "bar"
    with pytest.raises(SecretBackendReadOnly):
        backend.set("foo", "baz")
    assert backend.get("foo") == "bar"


def test_default_backend_per_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_SECRETS__BACKEND", raising=False)
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import AgeFileBackend, EnvBackend, KeychainBackend, open_backend

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    assert isinstance(open_backend(Settings.load(), Paths.from_env()), KeychainBackend)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("platform.system", lambda: "Linux")
    assert isinstance(open_backend(Settings.load(), Paths.from_env()), AgeFileBackend)

    (tmp_path / "config.toml").write_text('[secrets]\nbackend = "env"\n', encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(open_backend(Settings.load(), Paths.from_env()), EnvBackend)


def test_set_and_get_register_for_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.log import logger, setup

    backend, _secrets_file = _age_backend(tmp_path, monkeypatch)
    value = secrets.token_urlsafe(24)
    backend.set("opencode/api_key", value)  # type: ignore[attr-defined]
    log_path = tmp_path / "sevnd.log"
    logger.remove()
    setup(level="DEBUG", json_file=log_path)
    found: list[object] = []
    sink_id = logger.add(lambda message: found.append(message))
    try:
        logger.warning("seen " + value)
        logger.complete()
    finally:
        logger.remove(sink_id)
    blob = log_path.read_text(encoding="utf-8") + "".join(str(item) for item in found)
    assert value not in blob
    assert "«redacted:opencode/api_key»" in blob


def test_host_identity_created_once_and_id_derived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.config import Settings
    from sevn.identity import load_or_create
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    _backend, _secrets_file = _age_backend(tmp_path, monkeypatch)
    settings = Settings.load()
    paths = Paths.from_env()

    first = load_or_create(open_backend(settings, paths))
    stored = open_backend(settings, paths).get("host/identity")
    second = load_or_create(open_backend(settings, paths))
    assert open_backend(settings, paths).get("host/identity") == stored
    assert stored
    assert isinstance(first.public_key, bytes)
    assert len(first.public_key) == 32
    assert second.public_key == first.public_key
    assert first.host_id == second.host_id == _host_id(first.public_key)
    assert re.fullmatch(r"host_[a-z2-7]{26}", first.host_id)
    assert first.host_pubkey_fp == second.host_pubkey_fp == _fingerprint(first.public_key)
    assert len(first.host_pubkey_fp) == 22


@pytest.mark.live
def test_keychain_roundtrip() -> None:
    if sys.platform != "darwin":
        pytest.skip("macOS keychain only")
    from sevn.secrets.backends import KeychainBackend

    backend = KeychainBackend(service="sevn-test")
    value = secrets.token_urlsafe(16)
    name = "canary/roundtrip"
    try:
        backend.set(name, value)
        assert backend.get(name) == value
    finally:
        with contextlib.suppress(Exception):
            backend.delete(name)
