"""Self-improve subtree models for ``sevn.json``.

Module: sevn.config.sections.self_improve
Depends: pydantic, sevn.config.defaults

Exports:
    SelfImproveHubWorkspaceConfig — ``self_improve.hub`` forge hints (`specs/33-self-improvement.md` §5).
    SelfImproveSamplerCoverageWorkspaceConfig — ``self_improve.sampler.coverage`` (`specs/33-self-improvement.md` §3.2).
    SelfImproveSamplerWorkspaceConfig — ``self_improve.sampler`` (`specs/33-self-improvement.md` §5).
    SelfImproveJobsWorkspaceConfig — ``self_improve.jobs`` queue limits (`specs/33-self-improvement.md` §5).
    SelfImproveEvalWorkspaceConfig — ``self_improve.eval`` (`specs/33-self-improvement.md` §5).
    SelfImproveExportWorkspaceConfig — ``self_improve.export`` scaffold (`specs/33-self-improvement.md` §4.6).
    SelfImproveTrajectoriesWorkspaceConfig — ``self_improve.trajectories`` ingest automation.
    SelfImproveSpecKitConfig — ``self_improve.spec_kit`` optional plan stage (`specs/33-self-improvement.md`).
    SelfImproveWorkspaceConfig — ``self_improve`` subtree (`specs/33-self-improvement.md` §5).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sevn.config.defaults import (
    DEFAULT_SELF_IMPROVE_CLEAN_PRE_FILTER_RATIO,
    DEFAULT_SELF_IMPROVE_ENABLED,
    DEFAULT_SELF_IMPROVE_EVAL_DOCKER_REQUIRED,
    DEFAULT_SELF_IMPROVE_EXPLICIT_FEEDBACK_FLOOR_PCT,
    DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS,
    DEFAULT_SELF_IMPROVE_JOBS_MAX_CONCURRENT_WRITERS,
    DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MAX,
    DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MIN_VOICE,
    DEFAULT_SELF_IMPROVE_PER_INTENT_PCT_MAX,
    DEFAULT_SELF_IMPROVE_PER_TIER_PCT_MAX,
    DEFAULT_SELF_IMPROVE_SAMPLER_MAX_CANDIDATES,
    DEFAULT_SELF_IMPROVE_SPEC_KIT_ENABLED,
    DEFAULT_SELF_IMPROVE_SPEC_KIT_REQUIRE_HITL_PLAN,
    DEFAULT_SELF_IMPROVE_SPEC_KIT_REQUIRE_PLAN,
    DEFAULT_SELF_IMPROVE_TRAJECTORIES_INGEST_CRON,
    DEFAULT_SELF_IMPROVE_TRAJECTORIES_INGEST_ON_TURN,
    SELF_IMPROVE_SAMPLER_MAX_CANDIDATES_MAX,
    SELF_IMPROVE_SAMPLER_MAX_CANDIDATES_MIN,
)


class SelfImproveHubWorkspaceConfig(BaseModel):
    """``self_improve.hub`` forge hints (`specs/33-self-improvement.md` §5)."""

    model_config = ConfigDict(extra="allow")

    use_github: bool = True
    provider: Literal["github", "gitlab", "forgejo"] = "github"
    repo: str = ""
    default_branch: str = "main"


class SelfImproveSamplerCoverageWorkspaceConfig(BaseModel):
    """Per-axis sampler caps (`specs/33-self-improvement.md` §3.2)."""

    model_config = ConfigDict(extra="allow")

    per_channel_pct_max: float = Field(
        default=DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MAX,
        ge=0.0,
        le=1.0,
    )
    per_channel_pct_min: dict[str, float] = Field(
        default_factory=lambda: {"voice": DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MIN_VOICE},
    )
    per_intent_pct_max: float = Field(
        default=DEFAULT_SELF_IMPROVE_PER_INTENT_PCT_MAX,
        ge=0.0,
        le=1.0,
    )
    per_tier_pct_max: float = Field(
        default=DEFAULT_SELF_IMPROVE_PER_TIER_PCT_MAX,
        ge=0.0,
        le=1.0,
    )


class SelfImproveSamplerWorkspaceConfig(BaseModel):
    """Deterministic sampler knobs (`specs/33-self-improvement.md` §5)."""

    model_config = ConfigDict(extra="allow")

    max_candidates: int = Field(
        default=DEFAULT_SELF_IMPROVE_SAMPLER_MAX_CANDIDATES,
        ge=SELF_IMPROVE_SAMPLER_MAX_CANDIDATES_MIN,
        le=SELF_IMPROVE_SAMPLER_MAX_CANDIDATES_MAX,
    )
    seed_rotate_daily: bool = True
    explicit_feedback_floor_pct: float = Field(
        default=DEFAULT_SELF_IMPROVE_EXPLICIT_FEEDBACK_FLOOR_PCT,
        ge=0.0,
        le=1.0,
    )
    clean_pre_filter_ratio: float = Field(
        default=DEFAULT_SELF_IMPROVE_CLEAN_PRE_FILTER_RATIO,
        ge=0.0,
        le=1.0,
    )
    coverage: SelfImproveSamplerCoverageWorkspaceConfig | None = None


class SelfImproveJobsWorkspaceConfig(BaseModel):
    """Job queue writers (`specs/33-self-improvement.md` §5)."""

    model_config = ConfigDict(extra="allow")

    max_git_operations_per_day: int | None = Field(default=None, ge=1)
    max_concurrent_writers: int = Field(
        default=DEFAULT_SELF_IMPROVE_JOBS_MAX_CONCURRENT_WRITERS,
        ge=1,
    )


class SelfImproveEvalWorkspaceConfig(BaseModel):
    """Docker-first evaluation posture (`specs/33-self-improvement.md` §5)."""

    model_config = ConfigDict(extra="allow")

    token_budget_daily: str | int = "100k"
    docker_required: bool = DEFAULT_SELF_IMPROVE_EVAL_DOCKER_REQUIRED
    eval_network: Literal["offline", "replay", "live_budget"] = "offline"


class SelfImproveExportWorkspaceConfig(BaseModel):
    """Scaffold trajectory export (`specs/33-self-improvement.md` §4.6)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    allow_user_lines: bool = False
    ttl_days: int = Field(default=DEFAULT_SELF_IMPROVE_EXPORT_TTL_DAYS, ge=1)


class SelfImproveTrajectoriesWorkspaceConfig(BaseModel):
    """Trajectory ingest automation (`specs/33-self-improvement.md` §3.1)."""

    model_config = ConfigDict(extra="allow")

    ingest_on_turn: bool = DEFAULT_SELF_IMPROVE_TRAJECTORIES_INGEST_ON_TURN
    ingest_cron: str = DEFAULT_SELF_IMPROVE_TRAJECTORIES_INGEST_CRON


class SelfImproveSpecKitConfig(BaseModel):
    """``self_improve.spec_kit`` — optional plan before patch (`specs/33-self-improvement.md`)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_SELF_IMPROVE_SPEC_KIT_ENABLED
    require_plan_before_patch: bool = DEFAULT_SELF_IMPROVE_SPEC_KIT_REQUIRE_PLAN
    require_hitl_for_plan: bool = DEFAULT_SELF_IMPROVE_SPEC_KIT_REQUIRE_HITL_PLAN


class SelfImproveWorkspaceConfig(BaseModel):
    """Closed-loop self-improve toggles (`specs/33-self-improvement.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_SELF_IMPROVE_ENABLED
    preset: Literal["A", "B", "C"] = "A"
    auto_merge_enabled: bool = False
    sampler: SelfImproveSamplerWorkspaceConfig | None = None
    jobs: SelfImproveJobsWorkspaceConfig | None = None
    eval: SelfImproveEvalWorkspaceConfig | None = None
    hub: SelfImproveHubWorkspaceConfig | None = None
    allowed_globs: list[str] | None = None
    deny_globs: list[str] | None = None
    allow_dependency_changes: bool = False
    allow_config_changes: bool = False
    allow_lcm_memory_changes: bool = False
    require_human_approval: bool = False
    patch_author: Literal["pydantic_agent"] = "pydantic_agent"
    ASK_FOR_FEEDBACK: bool = False
    spec_kit: SelfImproveSpecKitConfig | None = None
    export: SelfImproveExportWorkspaceConfig | None = None
    trajectories: SelfImproveTrajectoriesWorkspaceConfig | None = None

    @model_validator(mode="after")
    def _force_human_when_lcm_writes(self) -> Self:
        """LCM mutations always need human approval (`specs/33-self-improvement.md` §5).

        Args:
            self (SelfImproveWorkspaceConfig): Validated subtree.

        Returns:
            SelfImproveWorkspaceConfig: Possibly updated copy.

        Examples:
            >>> SelfImproveWorkspaceConfig(
            ...     allow_lcm_memory_changes=True,
            ...     require_human_approval=False,
            ... ).require_human_approval
            True
        """
        if self.allow_lcm_memory_changes and not self.require_human_approval:
            self.require_human_approval = True
        return self

    @model_validator(mode="after")
    def _hub_repo_for_bc_presets(self) -> Self:
        """Preset B/C requires a non-empty forge repository id.

        Args:
            self (SelfImproveWorkspaceConfig): Validated subtree.

        Returns:
            SelfImproveWorkspaceConfig: Unchanged ``self``.

        Raises:
            ValueError: When hub.repo is blank while git presets are enabled.

        Examples:
            >>> SelfImproveWorkspaceConfig(
            ...     enabled=False,
            ...     preset="B",
            ... ).preset
            'B'
            >>> from pydantic import ValidationError
            >>> try:
            ...     SelfImproveWorkspaceConfig(enabled=True, preset="B")
            ... except ValidationError:
            ...     True
            ... else:
            ...     False
            True
        """
        if not self.enabled or self.preset not in ("B", "C"):
            return self
        hub = self.hub if self.hub is not None else SelfImproveHubWorkspaceConfig()
        if not hub.repo.strip():
            msg = "self_improve.hub.repo must be non-empty when self_improve.enabled with preset B or C"
            raise ValueError(msg)
        return self
