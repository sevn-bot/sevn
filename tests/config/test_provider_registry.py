"""Unit tests for provider registry config layer (W1 / contracts 1-4; green after W2)."""

from __future__ import annotations

import pytest

from sevn.config.provider_registry import (
    ProviderBinding,
    provider_credential_ref,
    resolve_provider_binding,
    resolve_provider_for_model_id,
)
from sevn.config.workspace_config import WorkspaceConfig


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("minimax/MiniMax-M2", "minimax"),
        ("openai/gpt-4o", "openai"),
        ("gpt-4o", "openai"),
        # Bare MiniMax wire name (prefix stripped by adapt_request_for_transport) must route to
        # MiniMax, not default to OpenAI (transcript-review-2026-06-22).
        ("MiniMax-M3", "minimax"),
        ("minimax-m2.7", "minimax"),
    ],
)
def test_resolve_provider_for_model_id_prefix_mapping(model_id: str, expected: str) -> None:
    """Contract 1: prefix-derived provider name (D1)."""
    cfg = WorkspaceConfig.minimal()
    assert resolve_provider_for_model_id(cfg, model_id) == expected


def test_resolve_provider_for_model_id_explicit_override() -> None:
    """Contract 2: ``providers.models.<id>.provider`` wins over prefix rule."""
    cfg = WorkspaceConfig.minimal(
        providers={
            "models": {"gpt-4o": {"provider": "custom_vendor"}},
            "custom_vendor": {"base_url": "https://vendor.example"},
        },
    )
    assert resolve_provider_for_model_id(cfg, "gpt-4o") == "custom_vendor"
    assert resolve_provider_for_model_id(cfg, "openai/gpt-4o") == "openai"


def test_resolve_provider_binding_returns_typed_fields() -> None:
    """Contract 3: binding resolution surfaces D2 sub-keys."""
    cfg = WorkspaceConfig.minimal(
        providers={
            "minimax": {
                "api_key": "${SECRET:SEVN_SECRET_MINIMAX}",
                "base_url": "https://api.minimax.io/anthropic/v1",
                "openai_base_url": "https://api.minimax.io/v1",
                "anthropic_base_url": "https://api.minimax.io/anthropic/v1",
                "transport": "anthropic",
            },
        },
    )
    binding = resolve_provider_binding(cfg, "minimax")
    assert isinstance(binding, ProviderBinding)
    assert binding.name == "minimax"
    assert binding.api_key_ref == "${SECRET:SEVN_SECRET_MINIMAX}"
    assert binding.base_url == "https://api.minimax.io/anthropic/v1"
    assert binding.openai_base_url == "https://api.minimax.io/v1"
    assert binding.anthropic_base_url == "https://api.minimax.io/anthropic/v1"
    assert binding.transport == "anthropic"


@pytest.mark.parametrize(
    ("provider_name", "providers_block", "expected"),
    [
        ("openai", {"openai": {"api_key": "${SECRET:OAI}"}}, "${SECRET:OAI}"),
        ("anthropic", {"anthropic": {"api_key": "sk-literal"}}, "sk-literal"),
        ("unused", {"openai": {"api_key": "sk-x"}}, None),
    ],
)
def test_provider_credential_ref(
    provider_name: str,
    providers_block: dict[str, object],
    expected: str | None,
) -> None:
    """Contract 4: secret ref, literal, or absent ``api_key``."""
    cfg = WorkspaceConfig.minimal(providers=providers_block)
    assert provider_credential_ref(cfg, provider_name) == expected
