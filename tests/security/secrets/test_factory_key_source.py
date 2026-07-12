"""`key_source` decides the encrypted-file unlock mechanism (``specs/06-secrets.md`` §5).

The factory passes exactly one credential (master_key XOR passphrase) to the backend based on
the explicit ``key_source``, so a stray env var can no longer change which key seals/opens the
store. These tests assert the observable contract end-to-end via ``secrets_chain_from_workspace``.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from sevn.config.workspace_config import (
    EncryptedFileBackendEntry,
    SecretsBackendSectionConfig,
)
from sevn.security.secrets.errors import SecretsStoreCorruptError
from sevn.security.secrets.factory import secrets_chain_from_workspace

_PASS = "correct horse battery staple"


def _section(key_source: str | None) -> SecretsBackendSectionConfig:
    entry = EncryptedFileBackendEntry(path=".sevn/secrets/store.enc", key_source=key_source)  # type: ignore[arg-type]
    return SecretsBackendSectionConfig(chain=[entry])


@pytest.mark.anyio
async def test_passphrase_mode_ignores_stray_master_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """key_source=passphrase seals + reads PBKDF2 even when a stray master_key is also set."""
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", _PASS)
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", secrets.token_bytes(32).hex())

    chain = secrets_chain_from_workspace(tmp_path, _section("passphrase"))
    await chain.set("SEVN_SECRET_TEST", "PLACEHOLDER")
    assert await chain.get("SEVN_SECRET_TEST") == "PLACEHOLDER"

    # Prove it was sealed with the passphrase (PBKDF2), not the raw key: a master_key-only
    # reader must fail to decrypt it.
    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE")
    mk_only = secrets_chain_from_workspace(tmp_path, _section("master_key"))
    with pytest.raises(SecretsStoreCorruptError):
        await mk_only.get("SEVN_SECRET_TEST")


@pytest.mark.anyio
async def test_master_key_mode_ignores_passphrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """key_source=master_key seals + reads raw-key even when a passphrase is also set."""
    raw = secrets.token_bytes(32).hex()
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", raw)
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", _PASS)

    chain = secrets_chain_from_workspace(tmp_path, _section("master_key"))
    await chain.set("SEVN_SECRET_TEST", "PLACEHOLDER")
    assert await chain.get("SEVN_SECRET_TEST") == "PLACEHOLDER"

    # Sealed with the raw key: a passphrase-only reader must fail.
    monkeypatch.delenv("SEVN_SECRETS_MASTER_KEY")
    pp_only = secrets_chain_from_workspace(tmp_path, _section("passphrase"))
    with pytest.raises(SecretsStoreCorruptError):
        await pp_only.get("SEVN_SECRET_TEST")


@pytest.mark.anyio
async def test_absent_key_source_defaults_to_passphrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No key_source + a stray master_key → store still seals/reads under the passphrase."""
    monkeypatch.setenv("SEVN_SECRETS_PASSPHRASE", _PASS)
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", secrets.token_bytes(32).hex())

    chain = secrets_chain_from_workspace(tmp_path, _section(None))
    await chain.set("SEVN_SECRET_TEST", "PLACEHOLDER")
    assert await chain.get("SEVN_SECRET_TEST") == "PLACEHOLDER"

    monkeypatch.delenv("SEVN_SECRETS_PASSPHRASE")
    mk_only = secrets_chain_from_workspace(tmp_path, _section("master_key"))
    with pytest.raises(SecretsStoreCorruptError):
        await mk_only.get("SEVN_SECRET_TEST")
