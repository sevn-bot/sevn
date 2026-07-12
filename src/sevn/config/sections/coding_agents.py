"""``coding_agents`` subtree models for ``sevn.json`` (Coding Agents hub).

Module: sevn.config.sections.coding_agents
Depends: pydantic

Exports:
    TelegramBindingConfig — per-agent Telegram chat/topic binding.
    AlrcaAgentConfig — ALRCA coding agent instance.
    LitellmLapAgentConfig — LiteLLM LAP bridge agent instance.
    CodingAgentsWorkspaceConfig — top-level ``coding_agents`` section.
    parse_coding_agents_section — coerce raw JSON into typed section.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

JsonDict = dict[str, Any]

EXECUTOR_IDS = frozenset({"claude_code", "cursor", "codex"})
AGENT_TYPES = frozenset({"alrca", "litellm_lap"})


class TelegramBindingConfig(BaseModel):
    """One Telegram chat/topic binding for a coding agent."""

    model_config = ConfigDict(extra="forbid")

    chat_id: str
    topic_ids: list[int] | None = None


class AlrcaAgentConfig(BaseModel):
    """ALRCA long-running coding agent instance."""

    model_config = ConfigDict(extra="allow")

    type: Literal["alrca"] = "alrca"
    enabled: bool = True
    executor: Literal["claude_code", "cursor", "codex"] = "cursor"
    telegram_bindings: list[TelegramBindingConfig] = Field(default_factory=list)
    evaluator_model: str | None = None
    verifiers: list[str] = Field(default_factory=list)


class LitellmLapAgentConfig(BaseModel):
    """LiteLLM Agent Control Plane bridge instance."""

    model_config = ConfigDict(extra="allow")

    type: Literal["litellm_lap"] = "litellm_lap"
    enabled: bool = True
    base_url: str | None = None
    runtime_id: str | None = None
    lap_agent_id: str | None = None
    api_key_secret: str | None = None
    telegram_bindings: list[TelegramBindingConfig] = Field(default_factory=list)


CodingAgentConfig = Annotated[
    AlrcaAgentConfig | LitellmLapAgentConfig,
    Field(discriminator="type"),
]

_AGENT_ADAPTER: TypeAdapter[CodingAgentConfig] = TypeAdapter(CodingAgentConfig)


class CodingAgentsWorkspaceConfig(BaseModel):
    """Top-level ``coding_agents`` workspace section."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    agents: dict[str, CodingAgentConfig] = Field(default_factory=dict)


def parse_coding_agents_section(raw: object) -> CodingAgentsWorkspaceConfig | None:
    """Parse optional ``coding_agents`` JSON into a typed section.

    Args:
        raw (object): Raw ``coding_agents`` subtree or ``None``.

    Returns:
        CodingAgentsWorkspaceConfig | None: Parsed section when ``raw`` is a mapping.

    Examples:
        >>> sec = parse_coding_agents_section({"enabled": True, "agents": {}})
        >>> sec is not None and sec.enabled
        True
        >>> parse_coding_agents_section(None) is None
        True
    """
    if raw is None:
        return None
    if isinstance(raw, CodingAgentsWorkspaceConfig):
        return raw
    if not isinstance(raw, dict):
        msg = f"invalid coding_agents section type: {type(raw).__name__}"
        raise ValueError(msg)
    agents_raw = raw.get("agents")
    agents: dict[str, CodingAgentConfig] = {}
    if isinstance(agents_raw, dict):
        for agent_id, entry in agents_raw.items():
            if isinstance(entry, dict):
                agents[str(agent_id)] = _AGENT_ADAPTER.validate_python(entry)
    return CodingAgentsWorkspaceConfig(
        enabled=bool(raw.get("enabled", True)),
        agents=agents,
    )


__all__ = [
    "AGENT_TYPES",
    "EXECUTOR_IDS",
    "AlrcaAgentConfig",
    "CodingAgentConfig",
    "CodingAgentsWorkspaceConfig",
    "LitellmLapAgentConfig",
    "TelegramBindingConfig",
    "parse_coding_agents_section",
]
