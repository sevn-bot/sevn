"""Bot-evolution subtree models for ``sevn.json``.

Module: sevn.config.sections.evolution
Depends: pydantic, sevn.config.defaults

Exports:
    SpecKitOptionsWorkspaceConfig — ``spec_kit.options`` dry-run defaults (`specs/35-bot-evolution.md`).
    SpecKitWorkspaceConfig — ``spec_kit`` subtree (`specs/35-bot-evolution.md`).
    MySevnSyncWorkspaceConfig — ``my_sevn.sync`` (`specs/35-bot-evolution.md`).
    MySevnBugsWorkspaceConfig — ``my_sevn.bugs`` (`specs/35-bot-evolution.md`).
    MySevnExecutorsWorkspaceConfig — ``my_sevn.executors`` (`specs/35-bot-evolution.md`).
    MySevnFeaturesWorkspaceConfig — ``my_sevn.features`` (`specs/35-bot-evolution.md`).
    MySevnPromotionWorkspaceConfig — ``my_sevn.promotion`` (`specs/35-bot-evolution.md`).
    MySevnWorkspaceBackupConfig — ``my_sevn.workspace_backup`` (`specs/22-onboarding.md` W1).
    MySevnIssuesWorkspaceConfig — ``my_sevn.issues`` (`specs/35-bot-evolution.md`).
    MySevnPipelinesWorkspaceConfig — ``my_sevn.pipelines`` (`specs/35-bot-evolution.md`).
    MySevnWorkspaceConfig — ``my_sevn`` subtree (`specs/35-bot-evolution.md`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_MY_SEVN_EXECUTOR_CURSOR_POLL_MODE,
    DEFAULT_MY_SEVN_ISSUES_AUTO_FILE_ON_FAILURE,
    DEFAULT_MY_SEVN_ISSUES_AUTO_RUN_ON_IMPORT,
    DEFAULT_MY_SEVN_ISSUES_SYNC_CRON,
    DEFAULT_MY_SEVN_ISSUES_SYNC_ENABLED,
    DEFAULT_MY_SEVN_ISSUES_WEBHOOK_IMPORT,
    DEFAULT_MY_SEVN_PIPELINES_CI_DRY_RUN,
    DEFAULT_MY_SEVN_PIPELINES_LOCAL_IMPLEMENT_MAX_TURNS,
    DEFAULT_MY_SEVN_PIPELINES_PROMOTION_DRY_RUN,
    DEFAULT_MY_SEVN_PIPELINES_SPEC_KIT_DRY_RUN,
    DEFAULT_SPEC_KIT_CONSTITUTION_PATH,
    DEFAULT_SPEC_KIT_DRY_RUN_DEFAULT,
    DEFAULT_SPEC_KIT_ENABLED,
    DEFAULT_SPEC_KIT_INTEGRATION,
)

EvolutionExecutorKind = Literal["local", "cursor_cloud", "chat"]
"""Runtime executor kind.

``local`` and ``cursor_cloud`` are persisted config values; ``chat`` is a
runtime-only override passed explicitly to ``run_pipeline`` — it is never
returned by ``resolve_executor`` and never stored in ``my_sevn.executors``
(`specs/35-bot-evolution.md` FL-2, C3).
"""

# Config-level executor subset: chat is runtime-only (C3/L3).
_ConfigExecutorKind = Literal["local", "cursor_cloud"]

CursorPollMode = Literal["background", "inline", "manual"]
"""Poll mode for cursor_cloud issues — `background` (background scheduler), `inline`
(block dispatch call), or `manual` (operator must call POST /poll) (`specs/35-bot-evolution.md` FL-4C.2)."""


class SpecKitOptionsWorkspaceConfig(BaseModel):
    """``spec_kit.options`` — MC dry-run defaults (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    dry_run_default: bool = DEFAULT_SPEC_KIT_DRY_RUN_DEFAULT
    pin_spec_kit_version: str | None = None


class SpecKitWorkspaceConfig(BaseModel):
    """``spec_kit`` — constitution paths and CLI integration (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = DEFAULT_SPEC_KIT_ENABLED
    constitution_path: str = DEFAULT_SPEC_KIT_CONSTITUTION_PATH
    features_dir: str = "evolution/features"
    improve_dir: str = "workspace/.sevn/improve/spec-kit"
    cli_command: str | None = None
    integration: str = DEFAULT_SPEC_KIT_INTEGRATION
    options: SpecKitOptionsWorkspaceConfig | None = None


class MySevnSyncWorkspaceConfig(BaseModel):
    """``my_sevn.sync`` — daily source checkout sync (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    cron: str = "0 4 * * *"


class MySevnBugsWorkspaceConfig(BaseModel):
    """``my_sevn.bugs`` — bug pipeline gates (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    require_approval: bool = False
    use_spec_kit: bool = False


class MySevnExecutorsWorkspaceConfig(BaseModel):
    """``my_sevn.executors`` — bug/feature implement routing (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    bug: _ConfigExecutorKind = "local"
    feature: _ConfigExecutorKind = "cursor_cloud"
    cursor_poll_mode: CursorPollMode = DEFAULT_MY_SEVN_EXECUTOR_CURSOR_POLL_MODE  # type: ignore[assignment]


class MySevnFeaturesWorkspaceConfig(BaseModel):
    """``my_sevn.features`` — feature pipeline gates (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    require_approval: bool = True


class MySevnPromotionWorkspaceConfig(BaseModel):
    """``my_sevn.promotion`` — worktree promotion mode (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    mode: str = "pr"


class MySevnWorkspaceBackupConfig(BaseModel):
    """``my_sevn.workspace_backup`` — private GitHub backup repo (`specs/22-onboarding.md` W1)."""

    model_config = ConfigDict(extra="allow")

    repo_url: str = ""
    branch: str = "main"
    auto_push: bool = False


def _default_issue_label_map() -> dict[str, str]:
    """Return the default GitHub label → evolution kind mapping.

    Returns:
        dict[str, str]: Label-to-kind defaults (`specs/35-bot-evolution.md` FL-1).

    Examples:
        >>> _default_issue_label_map()["enhancement"]
        'feature'
    """
    return {"bug": "bug", "enhancement": "feature", "feature": "feature"}


class MySevnIssuesWorkspaceConfig(BaseModel):
    """``my_sevn.issues`` — local registry + GitHub ingest options (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    prefer_github: bool = True
    auto_file_on_failure: bool = DEFAULT_MY_SEVN_ISSUES_AUTO_FILE_ON_FAILURE
    sync_enabled: bool = DEFAULT_MY_SEVN_ISSUES_SYNC_ENABLED
    sync_cron: str = DEFAULT_MY_SEVN_ISSUES_SYNC_CRON
    webhook_import: bool = DEFAULT_MY_SEVN_ISSUES_WEBHOOK_IMPORT
    auto_run_on_import: bool = DEFAULT_MY_SEVN_ISSUES_AUTO_RUN_ON_IMPORT
    label_map: dict[str, str] = Field(default_factory=_default_issue_label_map)


class MySevnPipelinesWorkspaceConfig(BaseModel):
    """``my_sevn.pipelines`` — dry-run defaults and budget knobs (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    ci_dry_run_default: bool = DEFAULT_MY_SEVN_PIPELINES_CI_DRY_RUN
    promotion_dry_run_default: bool = DEFAULT_MY_SEVN_PIPELINES_PROMOTION_DRY_RUN
    spec_kit_dry_run_default: bool = DEFAULT_MY_SEVN_PIPELINES_SPEC_KIT_DRY_RUN
    local_implement_max_turns: int = Field(
        default=DEFAULT_MY_SEVN_PIPELINES_LOCAL_IMPLEMENT_MAX_TURNS,
        ge=1,
        le=200,
    )


class MySevnWorkspaceConfig(BaseModel):
    """``my_sevn`` — operator binding (`specs/35-bot-evolution.md`)."""

    model_config = ConfigDict(extra="allow")

    repo_url: str = "https://github.com/sevn-bot/sevn"
    repo_path: str | None = None
    sync: MySevnSyncWorkspaceConfig | None = None
    issues: MySevnIssuesWorkspaceConfig | None = None
    pipelines: MySevnPipelinesWorkspaceConfig | None = None
    bugs: MySevnBugsWorkspaceConfig | None = None
    features: MySevnFeaturesWorkspaceConfig | None = None
    executors: MySevnExecutorsWorkspaceConfig | None = None
    promotion: MySevnPromotionWorkspaceConfig | None = None
    workspace_backup: MySevnWorkspaceBackupConfig | None = None
