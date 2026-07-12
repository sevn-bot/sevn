"""Feature subtree models for ``sevn.json``.

Module: sevn.config.sections.features
Depends: pydantic, sevn.config.defaults

Exports:
    SecondBrainFetchConfig — ``second_brain.fetch`` allowlist + HTTP caps (`specs/27-second-brain.md` §5).
    SecondBrainPathsConfig — ``second_brain.paths`` vault root (`specs/27-second-brain.md` §5).
    SecondBrainWorkspaceConfig — ``second_brain`` subtree (`specs/27-second-brain.md` §5).
    OpenUIWorkspaceConfig — ``openui`` subtree (`specs/29-openui.md` §5).
    PluginHookEntryConfig — ``plugin_hooks.<plugin_id>`` gate (`specs/34-plugin-hooks.md` §3.1).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sevn.config.defaults import (
    DEFAULT_OPENUI_CALLBACK_TIMEOUT_SECONDS,
    DEFAULT_OPENUI_HARD_CAP_BYTES,
    DEFAULT_OPENUI_SOFT_CAP_BYTES,
    DEFAULT_OPENUI_TOKEN_TTL_SECONDS,
    DEFAULT_SECOND_BRAIN_ENABLED,
    DEFAULT_SECOND_BRAIN_FETCH_MAX_RESPONSE_MIB,
    DEFAULT_SECOND_BRAIN_FETCH_TIMEOUT_S,
    DEFAULT_SECOND_BRAIN_OUTPUTS_RETENTION_DAYS,
)


class SecondBrainFetchConfig(BaseModel):
    """``second_brain.fetch`` allowlist and HTTP caps (`specs/27-second-brain.md` §5)."""

    model_config = ConfigDict(extra="allow")

    allow_domains: list[str] = Field(
        default_factory=list,
        description="HTTPS hostnames permitted for URL→raw fetch (exact or subdomain match).",
    )
    max_response_mib: int = Field(
        default=DEFAULT_SECOND_BRAIN_FETCH_MAX_RESPONSE_MIB,
        ge=1,
        le=256,
    )
    timeout_seconds: int = Field(
        default=DEFAULT_SECOND_BRAIN_FETCH_TIMEOUT_S,
        ge=1,
        le=600,
    )

    @field_validator("allow_domains", mode="before")
    @classmethod
    def _coerce_allow_domains(cls, v: object) -> object:
        """Normalise ``allow_domains`` to a list of bare hostnames.

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON value (``None``, list, or invalid).

        Returns:
            object: Coerced list or raises ``ValueError``.

        Examples:
            >>> SecondBrainFetchConfig._coerce_allow_domains(["Example.COM"])
            ['example.com']
        """
        if v is None:
            return []
        if not isinstance(v, list):
            msg = "second_brain.fetch.allow_domains must be a JSON array of hostname strings"
            raise ValueError(msg)
        out: list[str] = []
        for i, item in enumerate(v):
            if not isinstance(item, str) or not item.strip():
                msg = (
                    f"second_brain.fetch.allow_domains[{i}] must be a non-empty string "
                    "(hostname, no scheme or path)"
                )
                raise ValueError(msg)
            host = item.strip().lower().rstrip("/")
            if "://" in host or "/" in host or host.startswith("*"):
                msg = (
                    f"second_brain.fetch.allow_domains[{i}] must be a bare hostname "
                    f"(got {item!r}); omit https:// and paths"
                )
                raise ValueError(msg)
            out.append(host.lstrip("."))
        return out


def _normalise_vault_path(value: str) -> str:
    """Validate and normalise a workspace-relative vault path segment chain.

    Args:
        value (str): Raw ``second_brain.paths.vault`` value.

    Returns:
        str: POSIX-normalised relative path under the workspace content root.

    Raises:
        ValueError: When the path is empty, absolute, or escapes via ``..``.

    Examples:
        >>> _normalise_vault_path("obsidian/alex_AI")
        'obsidian/alex_AI'
    """
    text = value.strip().replace("\\", "/")
    if text.startswith("/") or "://" in text:
        msg = "second_brain.paths.vault must be workspace-relative (no leading / or scheme)"
        raise ValueError(msg)
    text = text.lstrip("/")
    parts = [p for p in text.split("/") if p]
    if ".." in parts or not parts:
        msg = "second_brain.paths.vault must not contain '..' components"
        raise ValueError(msg)
    return "/".join(parts)


class SecondBrainPathsConfig(BaseModel):
    """``second_brain.paths`` — custom Obsidian vault root (`specs/27-second-brain.md` §5)."""

    model_config = ConfigDict(extra="allow")

    vault: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_wiki_alias(cls, data: Any) -> Any:
        """Map legacy ``paths.wiki`` to ``vault`` on read; drop ``wiki`` when ``vault`` is set.

        Args:
            cls (type): Pydantic model class.
            data (Any): Raw JSON object or value.

        Returns:
            Any: Coerced mapping for field validation.

        Examples:
            >>> SecondBrainPathsConfig._coerce_wiki_alias({"wiki": "obsidian/x"})
            {'vault': 'obsidian/x'}
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        vault_raw = out.get("vault")
        wiki_raw = out.pop("wiki", None)
        if vault_raw in (None, "") and wiki_raw not in (None, ""):
            out["vault"] = wiki_raw
        return out

    @field_validator("vault", mode="before")
    @classmethod
    def _validate_vault(cls, v: object) -> object:
        """Normalise ``vault`` when present.

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON value.

        Returns:
            object: Normalised path string or ``None``.

        Examples:
            >>> SecondBrainPathsConfig._validate_vault("obsidian/alex_AI")
            'obsidian/alex_AI'
        """
        if v is None:
            return None
        if not isinstance(v, str):
            msg = "second_brain.paths.vault must be a string when set"
            raise ValueError(msg)
        if not v.strip():
            return None
        return _normalise_vault_path(v)


class SecondBrainWorkspaceConfig(BaseModel):
    """Typed ``second_brain`` subtree (`specs/27-second-brain.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_SECOND_BRAIN_ENABLED)
    topology: Literal["single_instance", "per_user", "shared_core_overlay"] = "single_instance"
    default_scope: str = Field(default="owner", min_length=1)
    outputs_retention_days: int = Field(
        default=DEFAULT_SECOND_BRAIN_OUTPUTS_RETENTION_DAYS,
        ge=1,
        le=3650,
    )
    conflict_strategy: Literal["atomic_reject", "git_merge"] = "atomic_reject"
    fetch: SecondBrainFetchConfig = Field(default_factory=SecondBrainFetchConfig)
    paths: SecondBrainPathsConfig = Field(default_factory=SecondBrainPathsConfig)
    ingest_batch_cron: str = Field(default="weekly", min_length=1)
    lint_cron: str = Field(default="first_sunday_09:00_local", min_length=1)

    @field_validator("default_scope", mode="before")
    @classmethod
    def _scope_token(cls, v: object) -> object:
        """Validate ``default_scope`` as a single safe path segment.

        Args:
            cls (type): Pydantic model class.
            v (object): Raw JSON value.

        Returns:
            object: Normalised scope string or raises ``ValueError``.

        Examples:
            >>> SecondBrainWorkspaceConfig._scope_token("owner")
            'owner'
        """
        if v is None:
            return "owner"
        if not isinstance(v, str) or not v.strip():
            msg = "second_brain.default_scope must be a non-empty string"
            raise ValueError(msg)
        s = v.strip()
        if s in (".", "..") or "/" in s or "\\" in s:
            msg = f"second_brain.default_scope must be a single path segment (got {v!r})"
            raise ValueError(msg)
        return s


class OpenUIWorkspaceConfig(BaseModel):
    """Typed ``openui`` subtree (`specs/29-openui.md` §5)."""

    model_config = ConfigDict(extra="allow")

    token_ttl_seconds: int = Field(default=DEFAULT_OPENUI_TOKEN_TTL_SECONDS, ge=60, le=86_400)
    callback_timeout_seconds: int = Field(
        default=DEFAULT_OPENUI_CALLBACK_TIMEOUT_SECONDS,
        ge=60,
        le=86_400,
    )
    soft_cap_bytes: int = Field(default=DEFAULT_OPENUI_SOFT_CAP_BYTES, ge=1024)
    hard_cap_bytes: int = Field(default=DEFAULT_OPENUI_HARD_CAP_BYTES, ge=4096)
    allowed_asset_origins: list[str] = Field(default_factory=list)
    rasteriser: Literal["weasyprint", "playwright"] = Field(default="weasyprint")

    @model_validator(mode="after")
    def _v1_rasteriser_only(self) -> OpenUIWorkspaceConfig:
        """Reject reserved rasteriser backends until implemented (`specs/29-openui.md` §4.4).

        Returns:
            OpenUIWorkspaceConfig: Validated ``self``.

        Examples:
            >>> OpenUIWorkspaceConfig().rasteriser
            'weasyprint'
        """

        if self.rasteriser == "playwright":
            msg = (
                "openui.rasteriser=playwright is reserved and not implemented in v1 "
                "(specs/29-openui.md §4.4); use weasyprint or omit the key."
            )
            raise ValueError(msg)
        if self.soft_cap_bytes > self.hard_cap_bytes:
            msg = "openui.soft_cap_bytes must be <= openui.hard_cap_bytes"
            raise ValueError(msg)
        return self


class PluginHookEntryConfig(BaseModel):
    """``plugin_hooks.<plugin_id>`` workspace gate (`specs/34-plugin-hooks.md` §3.1)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    trust_level: Literal["default", "owner"] = "default"
    timeout_s: float | None = Field(default=None, gt=0)
    runs_after: list[str] = Field(default_factory=list)
