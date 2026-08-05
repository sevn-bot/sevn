"""Prod-ready Batch A W1.2 RED — gateway secrets-chain resolution (C1.5).

Contracts: ``resolve_proxy_shared_secret`` consults the workspace secrets chain when
process env is empty, mirroring ``_resolve_proxy_shared_secret`` in
``src/sevn/proxy/credentials.py``. Explicit env still wins. Green after W2.
"""

from __future__ import annotations

import inspect

import pytest

from sevn.agent.adapters.egress_bridge import resolve_proxy_shared_secret
from sevn.security.secrets.chain import SecretsChain

_XFAIL_W2 = pytest.mark.xfail(strict=True, reason="prod-ready W2")


class _MemoryBackend:
    def __init__(self, data: dict[str, str] | None = None) -> None:
        self.data: dict[str, str] = dict(data or {})

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


def _chain_with(secret: str) -> SecretsChain:
    backend = _MemoryBackend({"SEVN_PROXY_SHARED_SECRET": secret})
    return SecretsChain([backend], backend_labels=["mem"])


@_XFAIL_W2
def test_resolve_proxy_shared_secret_accepts_chain_parameter() -> None:
    """W1.2: gateway resolver gains a secrets-chain seam (not env-only)."""
    params = inspect.signature(resolve_proxy_shared_secret).parameters
    assert "chain" in params


@_XFAIL_W2
@pytest.mark.anyio
async def test_resolve_uses_secrets_chain_when_env_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.2 / C1.5: chain value is returned when process env has no secret."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    chain = _chain_with("chain-only-secret")
    result = resolve_proxy_shared_secret(chain=chain)
    if inspect.isawaitable(result):
        result = await result
    assert result == "chain-only-secret"


@_XFAIL_W2
@pytest.mark.anyio
async def test_resolve_explicit_env_wins_over_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.2: operator-supplied env (external secret manager) still takes precedence."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", "env-wins")
    chain = _chain_with("chain-value")
    result = resolve_proxy_shared_secret(chain=chain)
    if inspect.isawaitable(result):
        result = await result
    assert result == "env-wins"


@_XFAIL_W2
@pytest.mark.anyio
async def test_resolve_empty_env_and_empty_chain_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.2 edge: no env and no chain entry → None (callers fail closed elsewhere)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    chain = SecretsChain([_MemoryBackend()], backend_labels=["mem"])
    result = resolve_proxy_shared_secret(chain=chain)
    if inspect.isawaitable(result):
        result = await result
    assert result is None
