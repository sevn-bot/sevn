"""Coding agent registry lookups for MC and gateway binding match.

Module: sevn.coding_agents.registry
Depends: sevn.config.sections.coding_agents, sevn.config.workspace_config

Exports:
    match_telegram_binding — map Telegram chat/topic to configured agent id.
    list_agent_summaries — serialise agents for Mission Control list API.
    binding_matches — test one binding row against chat/topic ids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.config.sections.coding_agents import (
    CodingAgentConfig,
    CodingAgentsWorkspaceConfig,
    TelegramBindingConfig,
    parse_coding_agents_section,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

JsonDict = dict[str, Any]


def _coding_agents_section(workspace: WorkspaceConfig) -> CodingAgentsWorkspaceConfig | None:
    """Return typed ``coding_agents`` section from workspace extras.

    Args:
        workspace (WorkspaceConfig): Parsed workspace root.

    Returns:
        CodingAgentsWorkspaceConfig | None: Section when present in document.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _coding_agents_section(WorkspaceConfig.minimal()) is None
        True
    """
    extra = workspace.model_extra or {}
    return parse_coding_agents_section(extra.get("coding_agents"))


def binding_matches(
    binding: TelegramBindingConfig,
    *,
    chat_id: str,
    topic_id: int | None,
) -> bool:
    """Return whether ``binding`` covers the inbound Telegram route.

    Args:
        binding (TelegramBindingConfig): Configured binding row.
        chat_id (str): Normalised Telegram chat id string.
        topic_id (int | None): Forum topic id (``None`` for general/DM thread).

    Returns:
        bool: ``True`` when the binding accepts this inbound route.

    Examples:
        >>> b = TelegramBindingConfig(chat_id="-1001", topic_ids=[42])
        >>> binding_matches(b, chat_id="-1001", topic_id=42)
        True
        >>> binding_matches(b, chat_id="-1001", topic_id=None)
        False
        >>> binding_matches(TelegramBindingConfig(chat_id="-1001"), chat_id="-1001", topic_id=7)
        True
    """
    if str(binding.chat_id) != str(chat_id):
        return False
    if binding.topic_ids is None:
        return True
    if topic_id is None:
        return False
    return int(topic_id) in binding.topic_ids


def match_telegram_binding(
    workspace: WorkspaceConfig,
    *,
    channel: str,
    chat_id: str | int,
    topic_id: int | None,
) -> str | None:
    """Resolve configured coding agent id for an inbound Telegram message.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        channel (str): Inbound adapter key (only ``telegram`` matches today).
        chat_id (str | int): Telegram chat id from message metadata.
        topic_id (int | None): Normalised forum topic id.

    Returns:
        str | None: First matching enabled agent id, else ``None``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "coding_agents": {
        ...         "enabled": True,
        ...         "agents": {
        ...             "a1": {
        ...                 "type": "alrca",
        ...                 "enabled": True,
        ...                 "telegram_bindings": [{"chat_id": "-1001", "topic_ids": [5]}],
        ...             }
        ...         },
        ...     },
        ... })
        >>> match_telegram_binding(ws, channel="telegram", chat_id="-1001", topic_id=5)
        'a1'
        >>> match_telegram_binding(ws, channel="webchat", chat_id="-1001", topic_id=5) is None
        True
    """
    if channel != "telegram":
        return None
    section = _coding_agents_section(workspace)
    if section is None or not section.enabled:
        return None
    chat_key = str(chat_id)
    for agent_id, agent in section.agents.items():
        if not agent.enabled:
            continue
        for binding in agent.telegram_bindings:
            if binding_matches(binding, chat_id=chat_key, topic_id=topic_id):
                return agent_id
    return None


def _bindings_summary(agent: CodingAgentConfig) -> list[JsonDict]:
    """Summarise Telegram bindings for API responses.

    Args:
        agent (CodingAgentConfig): Agent configuration row.

    Returns:
        list[JsonDict]: Binding summaries with chat id and topic scope.

    Examples:
        >>> from sevn.config.sections.coding_agents import AlrcaAgentConfig, TelegramBindingConfig
        >>> agent = AlrcaAgentConfig(
        ...     type="alrca",
        ...     enabled=True,
        ...     executor="cursor",
        ...     telegram_bindings=[TelegramBindingConfig(chat_id="-1", topic_ids=[1])],
        ... )
        >>> _bindings_summary(agent)[0]["chat_id"]
        '-1'
    """
    rows: list[JsonDict] = []
    for binding in agent.telegram_bindings:
        rows.append(
            {
                "chat_id": binding.chat_id,
                "topic_ids": binding.topic_ids,
                "scope": "whole_chat" if binding.topic_ids is None else "topics",
            },
        )
    return rows


def _last_run_status(agent_id: str) -> JsonDict:
    """Placeholder run status until ALRCA loop worker ships (CA3).

    Args:
        agent_id (str): Registry agent id.

    Returns:
        JsonDict: Idle status envelope for MC list API.

    Examples:
        >>> _last_run_status("demo")["state"]
        'idle'
    """
    _ = agent_id
    return {"state": "idle", "detail": "no runs yet"}


def list_agent_summaries(workspace: WorkspaceConfig) -> list[JsonDict]:
    """Build Mission Control list rows for configured coding agents.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        list[JsonDict]: Agent cards with type, enabled flag, bindings, run status.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> rows = list_agent_summaries(WorkspaceConfig.minimal())
        >>> rows == []
        True
    """
    section = _coding_agents_section(workspace)
    if section is None:
        return []
    rows: list[JsonDict] = []
    for agent_id, agent in section.agents.items():
        base: JsonDict = {
            "id": agent_id,
            "type": agent.type,
            "enabled": agent.enabled,
            "bindings": _bindings_summary(agent),
            "last_run": _last_run_status(agent_id),
        }
        if agent.type == "alrca":
            base["executor"] = agent.executor
            base["evaluator_model"] = agent.evaluator_model
            base["verifiers"] = list(agent.verifiers)
        else:
            base["base_url"] = agent.base_url
            base["runtime_id"] = agent.runtime_id
            base["lap_agent_id"] = agent.lap_agent_id
        rows.append(base)
    return rows


__all__ = [
    "binding_matches",
    "list_agent_summaries",
    "match_telegram_binding",
]
