"""Agent subtree models for ``sevn.json``.

Module: sevn.config.sections.agent
Depends: pydantic, sevn.config.defaults

Exports:
    AgentCodemodeConfig — ``agent.codemode`` (``specs/14-executor-tier-b.md`` W8).
    AgentHistoryCompactionConfig — ``agent.history_compaction`` (W6 opt-in, D9).
    AgentCacheStabilityConfig — ``agent.cache_stability`` (W7 opt-in, D9).
    AgentDiagnosticsConfig — ``agent.diagnostics`` slot for ``sevn doctor --with-agent``.
    AgentWorkspaceConfig — typed ``agent`` subtree.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_CODEMODE_DYNAMIC_CATALOG,
    DEFAULT_CODEMODE_MAX_RETRIES,
    DEFAULT_DIAGNOSTICS_AGENT_ENABLED,
    DEFAULT_TIER_B_CACHE_STABILITY_MONITOR_ENABLED,
    DEFAULT_TIER_B_HISTORY_COMPACTION_ENABLED,
    DEFAULT_TIER_B_HISTORY_COMPACTION_STRATEGY,
    DEFAULT_TIER_B_HISTORY_COMPACTION_TARGET_TOKENS,
)


class AgentCodemodeConfig(BaseModel):
    """``agent.codemode`` subtree (CodeMode opt-in for tier-B).

    Sandbox resource caps (``max_duration_secs`` / ``max_memory_bytes`` /
    ``max_allocations``) are read as ``extra`` keys by
    :func:`sevn.config.model_resolution.codemode_resource_limits` (which applies defaults and
    rejects non-positive values), so they are not declared as typed fields here.
    """

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    max_retries: int = Field(default=DEFAULT_CODEMODE_MAX_RETRIES, ge=1)
    dynamic_catalog: bool = Field(default=DEFAULT_CODEMODE_DYNAMIC_CATALOG)


class AgentHistoryCompactionConfig(BaseModel):
    """``agent.history_compaction`` subtree (W6 opt-in, D9 default off)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_TIER_B_HISTORY_COMPACTION_ENABLED)
    strategy: Literal["tiered", "summarizing", "clear_tool_results", "clamp_oversized"] = (
        DEFAULT_TIER_B_HISTORY_COMPACTION_STRATEGY
    )
    target_tokens: int = Field(default=DEFAULT_TIER_B_HISTORY_COMPACTION_TARGET_TOKENS, ge=1)


class AgentCacheStabilityConfig(BaseModel):
    """``agent.cache_stability`` subtree (W7 opt-in, D9 default off)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_TIER_B_CACHE_STABILITY_MONITOR_ENABLED)


class AgentDiagnosticsConfig(BaseModel):
    """``agent.diagnostics`` model slot for the CLI diagnostic agent."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_DIAGNOSTICS_AGENT_ENABLED)
    model: str | None = None


class AgentWorkspaceConfig(BaseModel):
    """Typed ``agent`` subtree in ``sevn.json``."""

    model_config = ConfigDict(extra="allow")

    codemode: AgentCodemodeConfig | None = None
    history_compaction: AgentHistoryCompactionConfig | None = None
    cache_stability: AgentCacheStabilityConfig | None = None
    diagnostics: AgentDiagnosticsConfig | None = None


__all__ = [
    "AgentCacheStabilityConfig",
    "AgentCodemodeConfig",
    "AgentDiagnosticsConfig",
    "AgentHistoryCompactionConfig",
    "AgentWorkspaceConfig",
]
