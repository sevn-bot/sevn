"""Process-level settings from the curated ``SEVN_*`` environment allowlist.

Module: sevn.config.settings
Depends: pydantic-settings

``PROCESS_SETTINGS_ENV_VAR_NAMES`` lists env vars parsed into ``ProcessSettings``;
keep it aligned with ``x-sevn-process-settings-env`` / ``process_settings`` rows in
``infra/sevn.schema.json`` (``specs/02-config-and-workspace.md`` §2.5,
``specs/23-cli.md`` §2.2-§2.5).

Exports:
    ProcessSettings — parsed env vars (never reads per-directory ``.env`` files).

Examples:
    >>> from sevn.config.settings import ProcessSettings
    >>> ProcessSettings.model_config["env_file"] is None
    True
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Curated allowlist for ``ProcessSettings`` / ``sevn onboard --from-env`` (02 §2.5, 23-cli §2.5).
PROCESS_SETTINGS_ENV_VAR_NAMES: frozenset[str] = frozenset(
    {
        "SEVN_HOME",
        "SEVN_GATEWAY_TOKEN",
        "SEVN_GATEWAY_URL",
        "SEVN_PROXY_URL",
        "SEVN_SESSION_TOKEN",
        "SEVN_WORKSPACE",
        "SEVN_UNSAFE_PARTIAL_HOOKS",
    },
)


class ProcessSettings(BaseSettings):
    """Operator and gateway bootstrap from environment (allowlist only).

    Precedence for HTTP URLs and tokens: these values win over ``sevn.json``
    when implementing merge logic in the gateway (this type only parses env).
    Per-directory ``.env`` files are never loaded — only real process environ.
    Field ↔ env mapping is listed in ``specs/02-config-and-workspace.md`` §2.5;
    CLI URL/auth resolution uses ``gateway_url`` / ``gateway_token`` per
    ``specs/23-cli.md`` §2.3.

    Examples:
        >>> ProcessSettings.model_config["env_file"] is None
        True
    """

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    home: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_HOME"),
        description="Operator state root; default ~/.sevn when unset elsewhere.",
    )
    gateway_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_GATEWAY_TOKEN"),
    )
    gateway_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_GATEWAY_URL"),
    )
    proxy_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_PROXY_URL"),
    )
    session_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_SESSION_TOKEN"),
    )
    workspace_shadow: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("SEVN_WORKSPACE"),
        description="Runtime shadow workspace for subprocess tools; not the config root.",
    )
    unsafe_partial_plugin_hooks: bool = Field(
        default=False,
        validation_alias=AliasChoices("SEVN_UNSAFE_PARTIAL_HOOKS"),
        description=(
            "When true, skip broken setuptools plugin hook entry points at gateway startup "
            "instead of failing fast (`specs/34-plugin-hooks.md` §5)."
        ),
    )
