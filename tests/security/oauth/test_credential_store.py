"""Credential persistence tests at ``oauth.openai`` (W1.3)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from tests.security.oauth.conftest import fake_access_jwt

from sevn.security.oauth.constants import OAUTH_OPENAI_SECRET_ALIAS
from sevn.security.oauth.credential import CodexOAuthCredential, oauth_openai_secret_alias
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


def test_oauth_openai_secret_alias_is_canonical() -> None:
    """Secret alias matches D2 locked constant."""
    assert oauth_openai_secret_alias() == OAUTH_OPENAI_SECRET_ALIAS == "oauth.openai"


def test_codex_oauth_credential_json_roundtrip() -> None:
    """Credential model serializes to the D2 blob shape."""
    cred = CodexOAuthCredential(
        access=fake_access_jwt(account_id="acct-rt"),
        refresh="rt-1",
        expires=1_700_000_000_000,
        account_id="acct-rt",
    )
    payload = cred.model_dump()
    assert set(payload) == {"access", "refresh", "expires", "account_id"}
    restored = CodexOAuthCredential.model_validate_json(json.dumps(payload))
    assert restored == cred


def test_codex_oauth_credential_rejects_extra_fields() -> None:
    """Extra JSON keys are forbidden on the credential model."""
    with pytest.raises(ValidationError, match="extra"):
        CodexOAuthCredential.model_validate(
            {
                "access": "a",
                "refresh": "r",
                "expires": 1,
                "account_id": "x",
                "access_token": "legacy",
            },
        )


@pytest.mark.anyio
async def test_persist_and_load_oauth_credential_roundtrip(
    sample_credential: CodexOAuthCredential,
) -> None:
    """``persist_codex_oauth_credential`` / ``load_codex_oauth_credential`` round-trip via chain."""
    from sevn.security.oauth.storage import (
        load_codex_oauth_credential,
        persist_codex_oauth_credential,
    )

    backend = _MemoryBackend()
    chain = SecretsChain([backend], backend_labels=["mem"])

    await persist_codex_oauth_credential(chain, sample_credential)
    assert OAUTH_OPENAI_SECRET_ALIAS in backend.data

    loaded = await load_codex_oauth_credential(chain)
    assert loaded == sample_credential


@pytest.mark.anyio
async def test_load_oauth_credential_returns_none_when_missing() -> None:
    """Missing alias returns ``None`` without raising."""
    from sevn.security.oauth.storage import load_codex_oauth_credential

    chain = SecretsChain([_MemoryBackend()], backend_labels=["mem"])
    assert await load_codex_oauth_credential(chain) is None


@pytest.mark.anyio
async def test_persist_oauth_credential_overwrites_existing(
    sample_credential: CodexOAuthCredential,
) -> None:
    """Second persist replaces the prior blob at ``oauth.openai``."""
    from sevn.security.oauth.storage import (
        load_codex_oauth_credential,
        persist_codex_oauth_credential,
    )

    backend = _MemoryBackend()
    chain = SecretsChain([backend], backend_labels=["mem"])
    await persist_codex_oauth_credential(chain, sample_credential)

    rotated = sample_credential.model_copy(
        update={"refresh": "rt-rotated", "expires": sample_credential.expires + 60_000},
    )
    await persist_codex_oauth_credential(chain, rotated)
    loaded = await load_codex_oauth_credential(chain)
    assert loaded == rotated


@pytest.mark.anyio
async def test_load_oauth_credential_raises_on_corrupt_json() -> None:
    """Corrupt JSON at ``oauth.openai`` raises a parse error."""
    from sevn.security.oauth.storage import load_codex_oauth_credential

    backend = _MemoryBackend()
    backend.data[OAUTH_OPENAI_SECRET_ALIAS] = "{not-json"
    chain = SecretsChain([backend], backend_labels=["mem"])
    with pytest.raises((ValueError, json.JSONDecodeError)):
        await load_codex_oauth_credential(chain)
