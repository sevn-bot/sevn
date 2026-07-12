"""Tests for ``sevn.skills.openwiki_secrets``."""

from __future__ import annotations

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.chain import SecretsChain
from sevn.skills.openwiki_secrets import (
    OPENWIKI_LLM_API_KEY_SECRET,
    merge_openwiki_proc_env,
    openwiki_credentials_hint,
)


class _MemBackend:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.mark.asyncio
async def test_merge_openwiki_proc_env_injects_provider_and_api_key(tmp_path) -> None:
    """Resolved ``api_key`` ref is forwarded to the provider env var."""
    store = {OPENWIKI_LLM_API_KEY_SECRET: "sk-openwiki-test"}
    chain = SecretsChain([_MemBackend(store)])
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={
            "openwiki": {
                "enabled": True,
                "provider": "openrouter",
                "model_id": "z-ai/glm-5.2",
                "api_key": f"${{SECRET:{OPENWIKI_LLM_API_KEY_SECRET}}}",
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    env: dict[str, str] = {}
    # Patch chain factory used inside merge_openwiki_proc_env
    from sevn.skills import openwiki_secrets as mod

    original = mod.secrets_chain_from_workspace

    def _fake_chain(_root, _backend):
        return chain

    mod.secrets_chain_from_workspace = _fake_chain  # type: ignore[assignment]
    try:
        await merge_openwiki_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    assert env["OPENWIKI_PROVIDER"] == "openrouter"
    assert env["OPENWIKI_MODEL_ID"] == "z-ai/glm-5.2"
    assert env["OPENROUTER_API_KEY"] == "sk-openwiki-test"


@pytest.mark.asyncio
async def test_merge_openwiki_proc_env_does_not_override_existing_env(tmp_path) -> None:
    """Existing subprocess env values take precedence over resolved secrets."""
    store = {OPENWIKI_LLM_API_KEY_SECRET: "from-secret"}
    chain = SecretsChain([_MemBackend(store)])
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={
            "openwiki": {
                "enabled": True,
                "provider": "openai",
                "api_key": f"${{SECRET:{OPENWIKI_LLM_API_KEY_SECRET}}}",
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    env = {"OPENAI_API_KEY": "from-operator"}
    from sevn.skills import openwiki_secrets as mod

    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    try:
        await merge_openwiki_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    assert env["OPENAI_API_KEY"] == "from-operator"


@pytest.mark.asyncio
async def test_merge_openwiki_proc_env_auto_maps_assigned_provider(tmp_path) -> None:
    """When ``api_key`` is omitted, assigned provider secrets are forwarded."""
    store = {"SEVN_SECRET_OPENAI": "sk-assigned-openai"}
    chain = SecretsChain([_MemBackend(store)])
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={"openwiki": {"enabled": True, "provider": "openai"}},
        providers={
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"},
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    env: dict[str, str] = {}
    from sevn.skills import openwiki_secrets as mod

    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    try:
        await merge_openwiki_proc_env(env, content_root=tmp_path, cfg=cfg)
    finally:
        mod.secrets_chain_from_workspace = original

    assert env["OPENAI_API_KEY"] == "sk-assigned-openai"
    assert env["OPENWIKI_PROVIDER"] == "openai"


def test_openwiki_credentials_hint_mentions_sevn_secrets() -> None:
    """Missing-credentials hint references sevn secrets workflow."""
    hint = openwiki_credentials_hint()
    assert "sevn secrets set" in hint
    assert OPENWIKI_LLM_API_KEY_SECRET in hint


@pytest.mark.asyncio
async def test_openwiki_credentials_resolved_rejects_langsmith_only(tmp_path) -> None:
    """Optional LangSmith keys do not satisfy LLM provider credential probes."""
    store = {"ls-secret": "ls-test"}
    chain = SecretsChain([_MemBackend(store)])
    cfg = WorkspaceConfig(
        schema_version=1,
        skills={
            "openwiki": {
                "enabled": True,
                "provider": "openai",
                "api_keys": {"langsmith_api_key": "${SECRET:ls-secret}"},
            },
        },
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    from sevn.skills import openwiki_secrets as mod

    original = mod.secrets_chain_from_workspace
    mod.secrets_chain_from_workspace = lambda _r, _b: chain  # type: ignore[assignment]
    try:
        ok, detail = await mod.openwiki_credentials_resolved(cfg, content_root=tmp_path)
    finally:
        mod.secrets_chain_from_workspace = original

    assert ok is False
    assert "sevn secrets set" in detail
