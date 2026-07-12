"""Unit tests for ``SecretsBackend`` implementations (``specs/06-secrets.md`` §9)."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest

from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.errors import SecretsStoreCorruptError


class _MemoryBackend:
    """In-memory store for contract tests."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.anyio
async def test_memory_backend_roundtrip() -> None:
    """Happy path: ``get`` / ``set`` / ``delete``."""
    b = _MemoryBackend()
    assert await b.get("k") is None
    await b.set("k", "PLACEHOLDER_VALUE")
    assert await b.get("k") == "PLACEHOLDER_VALUE"
    await b.delete("k")
    assert await b.get("k") is None


@pytest.mark.anyio
async def test_encrypted_file_backend_roundtrip(tmp_path: Path) -> None:
    """Encrypted JSON map persists under ``master_key``."""
    path = tmp_path / "store.enc"
    mk = secrets.token_bytes(32)
    b = EncryptedFileBackend(path, master_key=mk)
    assert await b.get("providers.openai.api_key") is None
    await b.set("providers.openai.api_key", "PLACEHOLDER_OPENAI")
    b2 = EncryptedFileBackend(path, master_key=mk)
    assert await b2.get("providers.openai.api_key") == "PLACEHOLDER_OPENAI"
    await b2.delete("providers.openai.api_key")
    assert not path.exists()


@pytest.mark.anyio
async def test_pbkdf2_store_reads_with_stray_master_key(tmp_path: Path) -> None:
    """A passphrase-sealed (PBKDF2) store must decrypt even when a stray ``master_key``
    is also supplied to the reader.

    Regression: when both ``SEVN_SECRETS_PASSPHRASE`` and ``SEVN_SECRETS_MASTER_KEY`` are
    present, ``_material_key`` used to short-circuit a PBKDF2 blob to the raw master_key,
    deriving the wrong AEAD key and silently failing to decrypt — which left the gateway
    Telegram adapter starting without a bot token.
    """
    path = tmp_path / "store.enc"
    writer = EncryptedFileBackend(path, passphrase="correct horse battery staple")
    await writer.set("SEVN_TELEGRAM_BOT_TOKEN", "123456:PLACEHOLDER_BOT_TOKEN")

    reader = EncryptedFileBackend(
        path,
        passphrase="correct horse battery staple",
        master_key=secrets.token_bytes(32),  # unrelated key, must be ignored for PBKDF2 blobs
    )
    assert await reader.get("SEVN_TELEGRAM_BOT_TOKEN") == "123456:PLACEHOLDER_BOT_TOKEN"


@pytest.mark.anyio
async def test_encrypted_file_corrupt_raises(tmp_path: Path) -> None:
    """Corrupt blob surfaces ``SecretsStoreCorruptError`` (§6)."""
    path = tmp_path / "bad.enc"
    path.write_bytes(b"not-a-sevn-store")
    b = EncryptedFileBackend(path, master_key=secrets.token_bytes(32))
    with pytest.raises(SecretsStoreCorruptError):
        await b.get("any.key")
