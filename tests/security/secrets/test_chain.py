"""Tests for ``SecretsChain`` and ``ResolvedSecretsCache`` (``specs/06-secrets.md`` §9)."""

from __future__ import annotations

import pytest

from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain, SecretsChainWriteError, get_secret_resilient
from sevn.security.secrets.errors import SecretsStoreCorruptError


class _MemoryBackend:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _LockedBackend:
    async def get(self, key: str) -> str | None:
        msg = "encrypted store needs passphrase or master_key"
        raise SecretsStoreCorruptError(msg)


class _WrongKeyBackend:
    async def get(self, key: str) -> str | None:
        msg = "AEAD decrypt failed (corrupt or wrong key)"
        raise SecretsStoreCorruptError(msg)


@pytest.mark.anyio
async def test_chain_get_fallback_order() -> None:
    """``get`` returns first backend with a non-``None`` value."""
    a = _MemoryBackend()
    b = _MemoryBackend()
    await b.set("k", "from_b")
    chain = SecretsChain([a, b], backend_labels=["a", "b"])
    assert await chain.get("k") == "from_b"
    await a.set("k", "from_a")
    assert await chain.get("k") == "from_a"


@pytest.mark.anyio
async def test_get_resilient_skips_locked_encrypted_backend() -> None:
    """Locked encrypted file backends are skipped instead of aborting the chain."""
    fallback = _MemoryBackend()
    await fallback.set("k", "from_memory")
    chain = SecretsChain([_LockedBackend(), fallback], backend_labels=["locked", "mem"])
    assert await get_secret_resilient(chain, "k") == "from_memory"


@pytest.mark.anyio
async def test_get_resilient_reraises_wrong_key_store() -> None:
    """A wrong-key / corrupt store must re-raise, not silently degrade to 'secret missing'.

    Regression: silently skipping a decrypt failure hid the stale-master_key misconfiguration
    that left the gateway booting without a Telegram bot token.
    """
    fallback = _MemoryBackend()
    await fallback.set("k", "from_memory")
    chain = SecretsChain([_WrongKeyBackend(), fallback], backend_labels=["wrongkey", "mem"])
    with pytest.raises(SecretsStoreCorruptError):
        await get_secret_resilient(chain, "k")


@pytest.mark.anyio
async def test_chain_set_first_writable_default() -> None:
    """``first_writable`` routes ``set`` only to the first backend."""
    a = _MemoryBackend()
    b = _MemoryBackend()
    chain = SecretsChain([a, b], backend_labels=["a", "b"])
    await chain.set("k", "v")
    assert a.data.get("k") == "v"
    assert "k" not in b.data


@pytest.mark.anyio
async def test_chain_set_write_targets_list() -> None:
    """Named ``write_targets`` fan-out."""
    a = _MemoryBackend()
    b = _MemoryBackend()
    chain = SecretsChain(
        [a, b],
        write_targets=["a", "b"],
        backend_labels=["a", "b"],
    )
    await chain.set("k", "both")
    assert a.data.get("k") == "both"
    assert b.data.get("k") == "both"


@pytest.mark.anyio
async def test_chain_set_no_writable_raises() -> None:
    """Empty ``write_targets`` list yields ``SecretsChainWriteError``."""
    a = _MemoryBackend()
    chain = SecretsChain([a], write_targets=[], backend_labels=["a"])
    with pytest.raises(SecretsChainWriteError):
        await chain.set("k", "v")


@pytest.mark.anyio
async def test_resolved_cache_ttl_refetch_after_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """TTL expiry forces a fresh chain ``get`` (monkeypatched clock)."""
    backend = _MemoryBackend()
    await backend.set("logical", "PLACEHOLDER_FIRST")

    chain = SecretsChain([backend], backend_labels=["enc"])
    t = {"now": 0.0}

    def clock() -> float:
        return t["now"]

    cache = ResolvedSecretsCache(chain, ttl_seconds=60, clock=clock)
    assert await cache.get_resolved("providers", "logical") == "PLACEHOLDER_FIRST"

    backend.data["logical"] = "PLACEHOLDER_SECOND"
    assert await cache.get_resolved("providers", "logical") == "PLACEHOLDER_FIRST"

    t["now"] = 61.0
    assert await cache.get_resolved("providers", "logical") == "PLACEHOLDER_SECOND"


@pytest.mark.anyio
async def test_resolved_cache_ttl_zero_skips_store() -> None:
    """``ttl_seconds == 0`` does not retain entries."""
    backend = _MemoryBackend()
    chain = SecretsChain([backend], backend_labels=["enc"])
    cache = ResolvedSecretsCache(chain, ttl_seconds=0)
    await backend.set("k", "PLACEHOLDER_A")
    assert await cache.get_resolved("x", "k") == "PLACEHOLDER_A"
    backend.data["k"] = "PLACEHOLDER_B"
    assert await cache.get_resolved("x", "k") == "PLACEHOLDER_B"
