"""Provider ``auth_mode`` resolution tests (W1.6 — D1/D4)."""

from __future__ import annotations

import pytest

from sevn.config.sections.providers import resolve_auth_mode
from sevn.config.workspace_config import WorkspaceConfig
from sevn.proxy.credentials import ProviderCredentials, resolve_request_credential
from sevn.proxy.settings import ProxySettings


def test_resolve_auth_mode_defaults_to_api_key() -> None:
    """Unset ``auth_mode`` resolves to ``api_key`` (D4 back-compat)."""
    assert resolve_auth_mode({"openai": {}}, "openai") == "api_key"
    assert resolve_auth_mode(None, "openai") == "api_key"


def test_resolve_auth_mode_explicit_oauth() -> None:
    """``auth_mode: oauth`` is honored for OpenAI."""
    assert resolve_auth_mode({"openai": {"auth_mode": "oauth"}}, "openai") == "oauth"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("oauth", "oauth"),
        ("OAUTH", "oauth"),
        (" api_key ", "api_key"),
        ("unknown", "api_key"),
    ],
)
def test_resolve_auth_mode_normalizes_values(raw: str, expected: str) -> None:
    """Unknown values fall back to ``api_key``; oauth is case-insensitive."""
    assert resolve_auth_mode({"openai": {"auth_mode": raw}}, "openai") == expected


def test_oauth_mode_resolves_bearer_over_api_key_binding() -> None:
    """``auth_mode=oauth`` selects OAuth bearer instead of ``providers.openai.api_key``."""
    from sevn.proxy.credentials import resolve_oauth_request_credential

    cfg = WorkspaceConfig.minimal(
        providers={
            "openai": {
                "auth_mode": "oauth",
                "api_key": "${SECRET:SEVN_SECRET_OPENAI}",
            },
        },
    )
    app_state = type(
        "S",
        (),
        {
            "settings": ProxySettings(openai_api_key="sk-env-fallback"),
            "provider_credentials": ProviderCredentials(),
        },
    )()
    bearer, account_id, base_url = resolve_oauth_request_credential(
        cfg,
        app_state,
        "openai/gpt-4o",
        "/llm/openai/chat/completions",
    )
    assert bearer
    assert account_id
    assert "chatgpt.com" in base_url


def test_oauth_mode_ignores_sevn_provider_api_key_env() -> None:
    """OAuth path must not fall back to ``SEVN_PROVIDER_API_KEY`` / route buckets."""
    from sevn.proxy.credentials import resolve_oauth_request_credential

    cfg = WorkspaceConfig.minimal(providers={"openai": {"auth_mode": "oauth"}})
    app_state = type(
        "S",
        (),
        {
            "settings": ProxySettings(openai_api_key="sk-should-not-be-used"),
            "provider_credentials": ProviderCredentials(),
        },
    )()
    bearer, _account_id, _base = resolve_oauth_request_credential(
        cfg,
        app_state,
        "openai/gpt-4o",
        "/llm/openai/chat/completions",
    )
    assert bearer != "sk-should-not-be-used"


def test_api_key_mode_preserves_legacy_resolution() -> None:
    """``auth_mode=api_key`` keeps today's ``resolve_request_credential`` path (D4)."""
    cfg = WorkspaceConfig.minimal()
    app_state = type(
        "S",
        (),
        {
            "settings": ProxySettings(openai_api_key="sk-legacy"),
            "provider_credentials": ProviderCredentials(),
        },
    )()
    key, base = resolve_request_credential(
        cfg,
        app_state,
        "openai/gpt-4o",
        "/llm/openai/chat/completions",
    )
    assert key == "sk-legacy"
    assert base.endswith("/v1")
