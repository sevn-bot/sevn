"""Legacy config migration for Coding Agents hub (CA2.3).

Module: sevn.coding_agents.migrate
Depends: typing

Exports:
    migrate_legacy_claude_agent_topic — promote ``claude_agent_topic_id`` to bindings.
"""

from __future__ import annotations

from typing import Any

JsonDict = dict[str, Any]

_LEGACY_AGENT_ID = "legacy-claude-agent"


def _first_telegram_chat_id(doc: JsonDict) -> str | None:
    """Infer a Telegram group chat id from legacy workspace keys.

    Args:
        doc (JsonDict): Full ``sevn.json`` document.

    Returns:
        str | None: Chat id string when discoverable from allowlist/topics.

    Examples:
        >>> _first_telegram_chat_id({"channels": {"telegram": {"allowed_groups": [-100123]}}})
        '-100123'
    """
    channels = doc.get("channels")
    if isinstance(channels, dict):
        telegram = channels.get("telegram")
        if isinstance(telegram, dict):
            groups = telegram.get("allowed_groups")
            if isinstance(groups, list):
                for item in groups:
                    if isinstance(item, int):
                        return str(item)
                    if isinstance(item, str) and item.strip():
                        return item.strip()
            topics = telegram.get("topics")
            if isinstance(topics, dict):
                for key in topics:
                    if str(key).lstrip("-").isdigit():
                        return str(key)
    return None


def _legacy_topic_id(doc: JsonDict) -> int | None:
    """Read deprecated ``claude_agent_topic_id`` from known legacy locations.

    Args:
        doc (JsonDict): Full ``sevn.json`` document.

    Returns:
        int | None: Legacy topic id when configured.

    Examples:
        >>> _legacy_topic_id({"telegram": {"claude_agent_topic_id": 42}})
        42
    """
    telegram_top = doc.get("telegram")
    if isinstance(telegram_top, dict):
        raw = telegram_top.get("claude_agent_topic_id")
        if isinstance(raw, int):
            return raw
    channels = doc.get("channels")
    if isinstance(channels, dict):
        telegram = channels.get("telegram")
        if isinstance(telegram, dict):
            raw = telegram.get("claude_agent_topic_id")
            if isinstance(raw, int):
                return raw
    return None


def migrate_legacy_claude_agent_topic(doc: JsonDict) -> tuple[JsonDict, bool]:
    """Move ``telegram.claude_agent_topic_id`` into ``coding_agents`` bindings.

    When ``claude_agent_topic_id`` is set and no ``coding_agents.agents`` exist yet,
    seed a disabled-by-default ALRCA agent with one topic binding. Legacy keys are
    removed from the document on success.

    Args:
        doc (JsonDict): Mutable workspace document copy.

    Returns:
        tuple[JsonDict, bool]: Updated document and whether a migration was applied.

    Examples:
        >>> out, changed = migrate_legacy_claude_agent_topic({
        ...     "schema_version": 1,
        ...     "telegram": {"claude_agent_topic_id": 42},
        ...     "channels": {"telegram": {"allowed_groups": [-1001234567890]}},
        ... })
        >>> changed
        True
        >>> out["coding_agents"]["agents"]["legacy-claude-agent"]["telegram_bindings"][0][
        ...     "topic_ids"
        ... ]
        [42]
    """
    topic_id = _legacy_topic_id(doc)
    if topic_id is None:
        return doc, False
    coding = doc.get("coding_agents")
    if isinstance(coding, dict):
        agents = coding.get("agents")
        if isinstance(agents, dict) and agents:
            return doc, False
    chat_id = _first_telegram_chat_id(doc)
    if chat_id is None:
        return doc, False

    out = dict(doc)
    section: JsonDict = {
        "enabled": True,
        "agents": {
            _LEGACY_AGENT_ID: {
                "type": "alrca",
                "enabled": False,
                "executor": "cursor",
                "telegram_bindings": [
                    {"chat_id": chat_id, "topic_ids": [int(topic_id)]},
                ],
            },
        },
    }
    out["coding_agents"] = section

    telegram_top = out.get("telegram")
    if isinstance(telegram_top, dict) and "claude_agent_topic_id" in telegram_top:
        cleaned = dict(telegram_top)
        cleaned.pop("claude_agent_topic_id", None)
        out["telegram"] = cleaned

    channels = out.get("channels")
    if isinstance(channels, dict):
        telegram = channels.get("telegram")
        if isinstance(telegram, dict) and "claude_agent_topic_id" in telegram:
            ch_copy = dict(channels)
            tg_copy = dict(telegram)
            tg_copy.pop("claude_agent_topic_id", None)
            ch_copy["telegram"] = tg_copy
            out["channels"] = ch_copy

    return out, True


__all__ = ["migrate_legacy_claude_agent_topic"]
