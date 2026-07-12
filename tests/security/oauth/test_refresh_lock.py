"""Proxy-owned refresh-under-lock tests (W1.4 — D3)."""

from __future__ import annotations

import asyncio

import pytest
from tests.security.oauth.conftest import fake_access_jwt

from sevn.security.oauth.credential import CodexOAuthCredential
from sevn.security.secrets.chain import SecretsChain


class _MemoryBackend:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.mark.anyio
async def test_expired_credential_triggers_refresh_and_persist(
    expired_credential: CodexOAuthCredential,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Near-expiry credential is refreshed and persisted back to ``oauth.openai``."""
    from sevn.proxy.oauth_lifecycle import ensure_fresh_oauth_credential
    from sevn.security.oauth.storage import (
        load_codex_oauth_credential,
        persist_codex_oauth_credential,
    )
    from sevn.security.oauth.token_client import TokenExchangeResult

    backend = _MemoryBackend()
    chain = SecretsChain([backend], backend_labels=["mem"])
    await persist_codex_oauth_credential(chain, expired_credential)

    refreshed = CodexOAuthCredential(
        access=fake_access_jwt(account_id="acct-refreshed"),
        refresh="rt-new",
        expires=int(__import__("time").time() * 1000) + 3_600_000,
        account_id="acct-refreshed",
    )

    refresh_calls = 0

    async def _refresh(*, refresh_token: str) -> TokenExchangeResult:
        nonlocal refresh_calls
        refresh_calls += 1
        assert refresh_token == expired_credential.refresh
        return TokenExchangeResult(type="success", credential=refreshed)

    monkeypatch.setattr("sevn.proxy.oauth_lifecycle.refresh_access_token", _refresh)

    out = await ensure_fresh_oauth_credential(chain)
    assert out.access == refreshed.access
    assert refresh_calls == 1
    stored = await load_codex_oauth_credential(chain)
    assert stored == refreshed


@pytest.mark.anyio
async def test_fresh_credential_skips_refresh(
    sample_credential: CodexOAuthCredential,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-expired credential is returned without calling the token endpoint."""
    from sevn.proxy.oauth_lifecycle import ensure_fresh_oauth_credential
    from sevn.security.oauth.storage import persist_codex_oauth_credential

    chain = SecretsChain([_MemoryBackend()], backend_labels=["mem"])
    await persist_codex_oauth_credential(chain, sample_credential)

    async def _boom(*_a: object, **_k: object) -> None:
        msg = "refresh must not run for fresh credential"
        raise AssertionError(msg)

    monkeypatch.setattr("sevn.proxy.oauth_lifecycle.refresh_access_token", _boom)

    out = await ensure_fresh_oauth_credential(chain)
    assert out == sample_credential


@pytest.mark.anyio
async def test_concurrent_refresh_is_single_flight(
    expired_credential: CodexOAuthCredential,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent callers share one refresh under the async lock (no double-refresh)."""
    from sevn.proxy.oauth_lifecycle import ensure_fresh_oauth_credential
    from sevn.security.oauth.storage import persist_codex_oauth_credential
    from sevn.security.oauth.token_client import TokenExchangeResult

    chain = SecretsChain([_MemoryBackend()], backend_labels=["mem"])
    await persist_codex_oauth_credential(chain, expired_credential)

    refresh_calls = 0
    gate = asyncio.Event()

    async def _slow_refresh(*, refresh_token: str) -> TokenExchangeResult:
        nonlocal refresh_calls
        refresh_calls += 1
        await gate.wait()
        cred = CodexOAuthCredential(
            access=fake_access_jwt(account_id="acct-concurrent"),
            refresh="rt-concurrent",
            expires=int(__import__("time").time() * 1000) + 3_600_000,
            account_id="acct-concurrent",
        )
        return TokenExchangeResult(type="success", credential=cred)

    monkeypatch.setattr("sevn.proxy.oauth_lifecycle.refresh_access_token", _slow_refresh)

    task_a = asyncio.create_task(ensure_fresh_oauth_credential(chain))
    task_b = asyncio.create_task(ensure_fresh_oauth_credential(chain))
    await asyncio.sleep(0.05)
    assert refresh_calls == 1
    gate.set()
    results = await asyncio.gather(task_a, task_b)
    assert results[0] == results[1]
    assert refresh_calls == 1


@pytest.mark.anyio
async def test_missing_oauth_credential_raises_clear_error() -> None:
    """Missing ``oauth.openai`` surfaces an operator-facing error."""
    from sevn.proxy.oauth_lifecycle import ensure_fresh_oauth_credential

    chain = SecretsChain([_MemoryBackend()], backend_labels=["mem"])
    with pytest.raises(Exception, match=r"(?i)oauth\.openai|not configured|missing"):
        await ensure_fresh_oauth_credential(chain)
