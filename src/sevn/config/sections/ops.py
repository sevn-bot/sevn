"""Operational subtree models for ``sevn.json``.

Module: sevn.config.sections.ops
Depends: pydantic, sevn.config.defaults

Exports:
    WorkspaceOutputSectionConfig — ``workspace.output_dir`` artifact confinement.
    OnboardingPersonalityDraftConfig — wizard-only personality draft fields.
    OnboardingWorkspaceSectionConfig — ``onboarding.applied_profile`` (`specs/22-onboarding.md` §3.2).
    TelemetryWorkspaceSectionConfig — ``telemetry.enabled`` opt-in (same).
    TriggersWorkspaceConfig — ``triggers`` subtree (`specs/30-non-interactive-triggers.md` §5).
    BrowserWorkspaceConfig — ``skills.browser`` subtree (browser session lifecycle W5).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sevn.config.defaults import (
    DEFAULT_TRIGGERS_MAX_CONCURRENT,
    DEFAULT_TRIGGERS_MAX_INLINE_BYTES,
    DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S,
    DEFAULT_WORKSPACE_OUTPUT_DIR,
)

JsonDict = dict[str, Any]


class WorkspaceOutputSectionConfig(BaseModel):
    """``workspace`` subtree — artifact output directory (`specs/02-config-and-workspace.md`)."""

    model_config = ConfigDict(extra="allow")

    output_dir: str = Field(default=DEFAULT_WORKSPACE_OUTPUT_DIR, min_length=1)
    per_session: bool = Field(
        default=True,
        description="When true, confine artifacts under ``output_dir/<session_id>/``.",
    )

    @field_validator("output_dir", mode="before")
    @classmethod
    def _normalise_output_dir(cls, v: object) -> object:
        """Reject absolute paths and ``..`` segments in ``workspace.output_dir``.

        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.

        Returns:
            object: Normalised relative path string.

        Examples:
            >>> WorkspaceOutputSectionConfig._normalise_output_dir("out/")
            'out'
        """
        from sevn.workspace.artifact_output import normalise_output_dir_rel

        if v is None:
            return DEFAULT_WORKSPACE_OUTPUT_DIR
        if not isinstance(v, str):
            return v
        return normalise_output_dir_rel(v)


class OnboardingPersonalityDraftConfig(BaseModel):
    """Wizard-only personality draft (`specs/22-onboarding.md` comprehensive setup W8)."""

    model_config = ConfigDict(extra="allow")

    name: str | None = None
    role: str | None = None
    timezone: str | None = None
    style: str | None = None
    style_detail: str | None = None
    language: str | None = None
    preferences: str | None = None
    preferences_detail: str | None = None
    vibe: str | None = None
    emoji: str | None = None


class OnboardingWorkspaceSectionConfig(BaseModel):
    """``onboarding`` subtree — wizard provenance (`specs/22-onboarding.md` §3.2)."""

    model_config = ConfigDict(extra="allow")

    applied_profile: str | None = None
    personality: OnboardingPersonalityDraftConfig | None = None
    capability_selections: dict[str, bool | str] | None = None


class TelemetryWorkspaceSectionConfig(BaseModel):
    """``telemetry`` subtree — explicit product telemetry opt-in (`specs/22-onboarding.md` §3.2)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False


class TriggersWorkspaceConfig(BaseModel):
    """Non-interactive triggers subtree (`specs/30-non-interactive-triggers.md` §5)."""

    model_config = ConfigDict(extra="allow")

    paused: bool = False
    max_concurrent: int = Field(default=DEFAULT_TRIGGERS_MAX_CONCURRENT, ge=1)
    max_parallel_runs: int | None = Field(default=None, ge=1)
    max_inline_bytes: int = Field(default=DEFAULT_TRIGGERS_MAX_INLINE_BYTES, ge=256)
    webhook_dedupe_ttl_s: int = Field(default=DEFAULT_TRIGGERS_WEBHOOK_DEDUPE_TTL_S, ge=60)
    webhooks: JsonDict | None = None
    sources: JsonDict | None = None
    cron: JsonDict | None = None
    api: JsonDict | None = None

    @model_validator(mode="before")
    @classmethod
    def _alias_max_parallel(cls, data: object) -> object:
        """Map legacy ``max_parallel_runs`` to ``max_concurrent`` when needed.

        Args:
            cls (type): Model class.
            data (object): Raw validator input (dict or passthrough).

        Returns:
            object: Shallow-copied dict with ``max_concurrent`` filled, or unchanged ``data``.

        Examples:
            >>> out = TriggersWorkspaceConfig._alias_max_parallel({"max_parallel_runs": 7})
            >>> out["max_concurrent"]
            7
        """

        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("max_concurrent") is None and out.get("max_parallel_runs") is not None:
            out["max_concurrent"] = out["max_parallel_runs"]
        return out


class BrowserWorkspaceConfig(BaseModel):
    """``skills.browser`` subtree (session-scoped Playwright lifecycle).

    Attributes:
        profile_dir: Optional override for Chrome ``user-data-dir``.
        idle_close_seconds: Gateway idle-close TTL; ``0`` disables (D8).
        headless: When true, spawn headless Chrome (D13).

    Examples:
        >>> BrowserWorkspaceConfig().idle_close_seconds
        0
    """

    model_config = ConfigDict(extra="allow")

    profile_dir: str | None = None
    idle_close_seconds: int = Field(default=0, ge=0)
    headless: bool = False
