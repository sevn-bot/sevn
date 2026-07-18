"""Pydantic models for ``sevn.json`` (partial validation; forward-compatible extras).

Module: sevn.config.workspace_config
Depends: pydantic, sevn.config.sections.*

Exports:
    parse_workspace_config — validate a decoded JSON dict.
    >>> parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})  # doctest: +ELLIPSIS
    WorkspaceConfig(...)
"""

from __future__ import annotations

from sevn.config.sections import accessors as _accessors_section
from sevn.config.sections.channels import (
    ChannelsWorkspaceSectionConfig,
    OwnerScannerOverrides,
    TelegramChannelConfig,
    TelegramInlineConfig,
    TelegramInlineSourcesConfig,
    TelegramQuickActionsConfig,
    TelegramReplyKeyboardConfig,
    TelegramRichConfig,
    TelegramWebappConfig,
    VoiceConfig,
    WebChatChannelConfig,
)
from sevn.config.sections.dashboard import DashboardPageAgentConfig, DashboardWorkspaceConfig
from sevn.config.sections.evolution import (
    CursorPollMode,
    EvolutionExecutorKind,
    MySevnBugsWorkspaceConfig,
    MySevnExecutorsWorkspaceConfig,
    MySevnFeaturesWorkspaceConfig,
    MySevnIssuesWorkspaceConfig,
    MySevnPipelinesWorkspaceConfig,
    MySevnPromotionWorkspaceConfig,
    MySevnSyncWorkspaceConfig,
    MySevnWorkspaceConfig,
    SpecKitOptionsWorkspaceConfig,
    SpecKitWorkspaceConfig,
)
from sevn.config.sections.executors import (
    ExecutorsWorkspaceConfig,
    PlanApprovalWorkspaceConfig,
    RlmWorkspaceConfig,
    TierCdExecutorConfig,
    TierCdLambdaRlmConfig,
)
from sevn.config.sections.features import (
    OpenUIWorkspaceConfig,
    PluginHookEntryConfig,
    SecondBrainFetchConfig,
    SecondBrainParaConfig,
    SecondBrainWorkspaceConfig,
)
from sevn.config.sections.gateway import (
    DispatcherStateWorkspaceConfig,
    GatewayBudgetConfig,
    GatewayConfig,
    GatewayFirstSessionIntroConfig,
    GatewayOutputConfig,
    GatewayRestartConfig,
    GatewaySessionMirrorConfig,
    GatewaySteerConfig,
    HarnessSnapshotSubConfig,
    HarnessWorkspaceConfig,
    ReplayWorkspaceConfig,
)
from sevn.config.sections.logging import (
    LoggingCloudConfig,
    LoggingCloudProviderConfig,
    LoggingWorkspaceConfig,
)
from sevn.config.sections.memory import (
    DreamingLlmRankerWorkspaceConfig,
    DreamingScoringWorkspaceConfig,
    DreamingWorkspaceConfig,
    LcmWorkspaceConfig,
    MemoryPreCompactionFlushWorkspaceConfig,
    MemoryWorkspaceSectionConfig,
    UserModelWorkspaceConfig,
)
from sevn.config.sections.ops import (
    BrowserWorkspaceConfig,
    OnboardingWorkspaceSectionConfig,
    TelemetryWorkspaceSectionConfig,
    TriggersWorkspaceConfig,
    WorkspaceOutputSectionConfig,
)
from sevn.config.sections.root import JsonDict, WorkspaceConfig
from sevn.config.sections.secrets import (
    BackendEntry,
    EncryptedFileBackendEntry,
    EncryptedFileSubtreeDefaults,
    LinuxSecretServiceBackendEntry,
    MacOSKeychainBackendEntry,
    OpenBaoBackendEntry,
    ProtonPassBackendEntry,
    SecretsBackendSectionConfig,
    _coerce_secrets_backend_model,
    effective_encrypted_file_key_source,
)
from sevn.config.sections.security import (
    DeploymentConfig,
    SandboxConfig,
    SecurityAuditSubConfig,
    SecurityLlmignoreRetentionSubConfig,
    SecurityLlmignoreSubConfig,
    SecurityReplSubConfig,
    SecuritySandboxSubConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
)
from sevn.config.sections.self_improve import (
    SelfImproveEvalWorkspaceConfig,
    SelfImproveExportWorkspaceConfig,
    SelfImproveHubWorkspaceConfig,
    SelfImproveJobsWorkspaceConfig,
    SelfImproveSamplerCoverageWorkspaceConfig,
    SelfImproveSamplerWorkspaceConfig,
    SelfImproveSpecKitConfig,
    SelfImproveWorkspaceConfig,
)
from sevn.config.sections.skills_google_workspace import (
    GoogleWorkspaceServiceSet,
    GoogleWorkspaceSkillConfig,
)
from sevn.config.sections.skills_social_media import (
    PlatformMediumConfig,
    SocialMediaManagerSkillConfig,
    SocialMedium,
    TwexApiSkillBlock,
)
from sevn.config.sections.subagents import (
    Role as SubAgentRole,
)
from sevn.config.sections.subagents import (
    SpecialistConfig,
    SubAgentRoleLimits,
    SubAgentsWorkspaceConfig,
)
from sevn.config.sections.subagents import (
    resolve_limits as resolve_subagent_limits,
)
from sevn.config.sections.tracing import TraceRedactionConfig, TraceSinkEntry, TracingConfig
from sevn.config.sections.triager import TriagerTimeoutConfig, TriagerWorkspaceConfig

rlm_json_dict = _accessors_section.rlm_json_dict
tier_b_skill_cap = _accessors_section.tier_b_skill_cap
tier_b_rounds = _accessors_section.tier_b_rounds
browser_settings = _accessors_section.browser_settings
google_workspace_settings = _accessors_section.google_workspace_settings
social_media_manager_settings = _accessors_section.social_media_manager_settings
tier_b_rounds_expanded = _accessors_section.tier_b_rounds_expanded
tier_b_count_planning = _accessors_section.tier_b_count_planning
tool_debug_result_max_chars = _accessors_section.tool_debug_result_max_chars
tool_as_skill_auto_route_enabled = _accessors_section.tool_as_skill_auto_route_enabled
tier_b_max_output_tokens = _accessors_section.tier_b_max_output_tokens
agent_max_output_tokens_ceiling = _accessors_section.agent_max_output_tokens_ceiling
complexity_clamp_confidence_threshold = _accessors_section.complexity_clamp_confidence_threshold
complexity_clamp_short_word_limit = _accessors_section.complexity_clamp_short_word_limit
tier_b_executor_timeout_s = _accessors_section.tier_b_executor_timeout_s
tier_cd_executor_timeout_s = _accessors_section.tier_cd_executor_timeout_s
cascade_budget_s = _accessors_section.cascade_budget_s
tier_b_answer_mode = _accessors_section.tier_b_answer_mode
show_intent_footer = _accessors_section.show_intent_footer


def parse_workspace_config(data: JsonDict) -> WorkspaceConfig:
    """Validate and normalize a decoded ``sevn.json`` object.

        Args:
    data (dict[str, Any]): Raw JSON object (after ``json.loads``).

        Returns:
        WorkspaceConfig: Parsed config with extras retained for round-trip.

        Examples:
            >>> c = parse_workspace_config({
            ...     "schema_version": 1,
            ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            ...     "foo": 1,
            ... })
            >>> c.model_extra.get("foo")
            1
    """
    return WorkspaceConfig.model_validate(data)


__all__ = [
    "BackendEntry",
    "BrowserWorkspaceConfig",
    "ChannelsWorkspaceSectionConfig",
    "CursorPollMode",
    "DashboardPageAgentConfig",
    "DashboardWorkspaceConfig",
    "DeploymentConfig",
    "DispatcherStateWorkspaceConfig",
    "DreamingLlmRankerWorkspaceConfig",
    "DreamingScoringWorkspaceConfig",
    "DreamingWorkspaceConfig",
    "EncryptedFileBackendEntry",
    "EncryptedFileSubtreeDefaults",
    "EvolutionExecutorKind",
    "ExecutorsWorkspaceConfig",
    "GatewayBudgetConfig",
    "GatewayConfig",
    "GatewayFirstSessionIntroConfig",
    "GatewayOutputConfig",
    "GatewayRestartConfig",
    "GatewaySessionMirrorConfig",
    "GatewaySteerConfig",
    "GoogleWorkspaceServiceSet",
    "GoogleWorkspaceSkillConfig",
    "HarnessSnapshotSubConfig",
    "HarnessWorkspaceConfig",
    "JsonDict",
    "LcmWorkspaceConfig",
    "LinuxSecretServiceBackendEntry",
    "LoggingCloudConfig",
    "LoggingCloudProviderConfig",
    "LoggingWorkspaceConfig",
    "MacOSKeychainBackendEntry",
    "MemoryPreCompactionFlushWorkspaceConfig",
    "MemoryWorkspaceSectionConfig",
    "MySevnBugsWorkspaceConfig",
    "MySevnExecutorsWorkspaceConfig",
    "MySevnFeaturesWorkspaceConfig",
    "MySevnIssuesWorkspaceConfig",
    "MySevnPipelinesWorkspaceConfig",
    "MySevnPromotionWorkspaceConfig",
    "MySevnSyncWorkspaceConfig",
    "MySevnWorkspaceConfig",
    "OnboardingWorkspaceSectionConfig",
    "OpenBaoBackendEntry",
    "OpenUIWorkspaceConfig",
    "OwnerScannerOverrides",
    "PlanApprovalWorkspaceConfig",
    "PlatformMediumConfig",
    "PluginHookEntryConfig",
    "ProtonPassBackendEntry",
    "ReplayWorkspaceConfig",
    "RlmWorkspaceConfig",
    "SandboxConfig",
    "SecondBrainFetchConfig",
    "SecondBrainParaConfig",
    "SecondBrainWorkspaceConfig",
    "SecretsBackendSectionConfig",
    "SecurityAuditSubConfig",
    "SecurityLlmignoreRetentionSubConfig",
    "SecurityLlmignoreSubConfig",
    "SecurityReplSubConfig",
    "SecuritySandboxSubConfig",
    "SecurityScannerSubConfig",
    "SecurityWorkspaceConfig",
    "SelfImproveEvalWorkspaceConfig",
    "SelfImproveExportWorkspaceConfig",
    "SelfImproveHubWorkspaceConfig",
    "SelfImproveJobsWorkspaceConfig",
    "SelfImproveSamplerCoverageWorkspaceConfig",
    "SelfImproveSamplerWorkspaceConfig",
    "SelfImproveSpecKitConfig",
    "SelfImproveWorkspaceConfig",
    "SocialMediaManagerSkillConfig",
    "SocialMedium",
    "SpecKitOptionsWorkspaceConfig",
    "SpecKitWorkspaceConfig",
    "SpecialistConfig",
    "SubAgentRole",
    "SubAgentRoleLimits",
    "SubAgentsWorkspaceConfig",
    "TelegramChannelConfig",
    "TelegramInlineConfig",
    "TelegramInlineSourcesConfig",
    "TelegramQuickActionsConfig",
    "TelegramReplyKeyboardConfig",
    "TelegramRichConfig",
    "TelegramWebappConfig",
    "TelemetryWorkspaceSectionConfig",
    "TierCdExecutorConfig",
    "TierCdLambdaRlmConfig",
    "TraceRedactionConfig",
    "TraceSinkEntry",
    "TracingConfig",
    "TriagerTimeoutConfig",
    "TriagerWorkspaceConfig",
    "TriggersWorkspaceConfig",
    "TwexApiSkillBlock",
    "UserModelWorkspaceConfig",
    "VoiceConfig",
    "WebChatChannelConfig",
    "WorkspaceConfig",
    "WorkspaceOutputSectionConfig",
    "_coerce_secrets_backend_model",
    "agent_max_output_tokens_ceiling",
    "browser_settings",
    "cascade_budget_s",
    "complexity_clamp_confidence_threshold",
    "complexity_clamp_short_word_limit",
    "effective_encrypted_file_key_source",
    "google_workspace_settings",
    "parse_workspace_config",
    "resolve_subagent_limits",
    "rlm_json_dict",
    "show_intent_footer",
    "social_media_manager_settings",
    "tier_b_answer_mode",
    "tier_b_count_planning",
    "tier_b_executor_timeout_s",
    "tier_b_max_output_tokens",
    "tier_b_rounds",
    "tier_b_rounds_expanded",
    "tier_b_skill_cap",
    "tier_cd_executor_timeout_s",
    "tool_as_skill_auto_route_enabled",
    "tool_debug_result_max_chars",
]
