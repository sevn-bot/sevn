"""Environment-backed settings for the egress LLM proxy.

Module: sevn.proxy.settings
Depends: pydantic, pydantic-settings

Exports:
    ProxySettings — keys, base URLs, optional shared-secret guard.

Examples:
    >>> from sevn.proxy.settings import ProxySettings
    >>> ProxySettings.model_config["env_file"] is None
    True
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProxySettings(BaseSettings):
    """Process env for proxy-only secrets (never loaded from ``.env`` files)."""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
        arbitrary_types_allowed=True,
    )

    anthropic_api_key: str | None = Field(default=None)
    anthropic_base_url: str = Field(default="https://api.anthropic.com")
    anthropic_version: str = Field(default="2023-06-01")

    openai_api_key: str | None = Field(default=None)
    openai_base_url: str = Field(default="https://api.openai.com/v1")

    proxy_shared_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_PROXY_SHARED_SECRET", "proxy_shared_secret"),
    )

    brave_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BRAVE_API_KEY", "brave_api_key"),
    )

    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION", "aws_region"),
    )
    aws_access_key_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AWS_ACCESS_KEY_ID", "aws_access_key_id"),
    )
    aws_secret_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AWS_SECRET_ACCESS_KEY", "aws_secret_access_key"),
    )

    provider_credentials: Any = Field(
        default=None,
        exclude=True,
        repr=False,
    )
