"""Coding Agents hub — registry, bindings, and operator routing helpers.

Module: sevn.coding_agents
Depends: sevn.config.sections.coding_agents

Exports:
    match_telegram_binding — resolve bound agent id for inbound Telegram traffic.
    list_agent_summaries — MC/API agent rows with bindings and run status.
    migrate_legacy_claude_agent_topic — move ``claude_agent_topic_id`` into bindings.
"""

from sevn.coding_agents.migrate import migrate_legacy_claude_agent_topic
from sevn.coding_agents.registry import list_agent_summaries, match_telegram_binding

__all__ = [
    "list_agent_summaries",
    "match_telegram_binding",
    "migrate_legacy_claude_agent_topic",
]
