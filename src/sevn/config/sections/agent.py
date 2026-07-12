"""Agent subtree models for ``sevn.json``.

Module: sevn.config.sections.agent
Depends: pydantic, sevn.config.defaults

Exports:
    AgentCodemodeConfig — ``agent.codemode`` (``specs/14-executor-tier-b.md`` W8).
    AgentDiagnosticsConfig — ``agent.diagnostics`` slot for ``sevn doctor --with-agent``.
    AgentWorkspaceConfig — typed ``agent`` subtree.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from sevn.config.defaults import (
    DEFAULT_CODEMODE_MAX_RETRIES,
    DEFAULT_DIAGNOSTICS_AGENT_ENABLED,
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


class AgentDiagnosticsConfig(BaseModel):
    """``agent.diagnostics`` model slot for the CLI diagnostic agent."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_DIAGNOSTICS_AGENT_ENABLED)
    model: str | None = None


class AgentWorkspaceConfig(BaseModel):
    """Typed ``agent`` subtree in ``sevn.json``."""

    model_config = ConfigDict(extra="allow")

    codemode: AgentCodemodeConfig | None = None
    diagnostics: AgentDiagnosticsConfig | None = None


__all__ = [
    "AgentCodemodeConfig",
    "AgentDiagnosticsConfig",
    "AgentWorkspaceConfig",
]
