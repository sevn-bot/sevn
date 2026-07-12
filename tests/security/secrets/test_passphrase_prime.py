"""Unit tests for keychain self-unlock priming (`specs/06-secrets.md`).

Covers ``sevn.security.secrets.passphrase_prime``: the daemon boot helper that primes the
encrypted-store unlock var from the macOS login Keychain when the launchd session lost it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sevn.security.secrets.passphrase_prime as pp
from sevn.security.secrets.passphrase_prime import (
    keychain_has_unlock_secret,
    prime_unlock_env_from_keychain,
    reconcile_unlock_env_with_keychain,
    unlock_env_var_for,
)

if TYPE_CHECKING:
    import pytest


def test_unlock_env_var_for_mapping() -> None:
    assert unlock_env_var_for("passphrase") == "SEVN_SECRETS_PASSPHRASE"
    assert unlock_env_var_for("master_key") == "SEVN_SECRETS_MASTER_KEY"
    assert unlock_env_var_for("anything-else") == "SEVN_SECRETS_PASSPHRASE"


def _patch_keychain_get(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    async def _fake_get(self: object, key: str) -> str | None:
        return value

    monkeypatch.setattr(pp.MacOSKeychainBackend, "get", _fake_get)


async def test_prime_sets_env_when_keychain_has_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE", raising=False)
    _patch_keychain_get(monkeypatch, "kc-secret")
    primed = await prime_unlock_env_from_keychain(key_source="passphrase")
    assert primed is True
    import os

    assert os.environ.get("SEVN_SECRETS_PASSPHRASE") == "kc-secret"


async def test_prime_noop_when_env_already_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "shell-value")
    _patch_keychain_get(monkeypatch, "kc-secret")
    primed = await prime_unlock_env_from_keychain(key_source="passphrase")
    assert primed is False
    import os

    assert os.environ["SEVN_SECRETS_PASSPHRASE"] == "shell-value"


async def test_prime_noop_when_keychain_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE", raising=False)
    _patch_keychain_get(monkeypatch, None)
    primed = await prime_unlock_env_from_keychain(key_source="passphrase")
    assert primed is False
    import os

    assert "SEVN_SECRETS_PASSPHRASE" not in os.environ


async def test_prime_master_key_targets_right_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEVN_SECRETS_MASTER_KEY", raising=False)
    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE", raising=False)

    captured: dict[str, str] = {}

    async def _fake_get(self: object, key: str) -> str | None:
        captured["key"] = key
        return "raw-key-hex"

    monkeypatch.setattr(pp.MacOSKeychainBackend, "get", _fake_get)
    primed = await prime_unlock_env_from_keychain(key_source="master_key")
    assert primed is True
    assert captured["key"] == "SEVN_SECRETS_MASTER_KEY"
    import os

    assert os.environ.get("SEVN_SECRETS_MASTER_KEY") == "raw-key-hex"
    assert "SEVN_SECRETS_PASSPHRASE" not in os.environ


async def test_keychain_has_unlock_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_keychain_get(monkeypatch, "present")
    assert await keychain_has_unlock_secret(key_source="passphrase") is True
    _patch_keychain_get(monkeypatch, None)
    assert await keychain_has_unlock_secret(key_source="passphrase") is False
    _patch_keychain_get(monkeypatch, "   ")
    assert await keychain_has_unlock_secret(key_source="passphrase") is False


async def test_reconcile_replaces_stale_env_with_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "stale-shell")

    async def _fake_fetch(*, key_source: str, service: str | None = None) -> str | None:
        assert key_source == "passphrase"
        return "onboard-pass"

    monkeypatch.setattr(pp, "fetch_unlock_secret_from_keychain", _fake_fetch)
    replaced = await reconcile_unlock_env_with_keychain(key_source="passphrase")
    assert replaced is True
    import os

    assert os.environ["SEVN_SECRETS_PASSPHRASE"] == "onboard-pass"


async def test_reconcile_noop_when_env_matches_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", "same")
    _patch_keychain_get(monkeypatch, "same")
    replaced = await reconcile_unlock_env_with_keychain(key_source="passphrase")
    assert replaced is False
