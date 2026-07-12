"""Tests for legacy ``claude_agent_topic_id`` migration into coding_agents bindings."""

from __future__ import annotations

from sevn.coding_agents.migrate import migrate_legacy_claude_agent_topic


def test_migrate_legacy_topic_into_coding_agents_binding() -> None:
    doc = {
        "schema_version": 1,
        "telegram": {"claude_agent_topic_id": 42},
        "channels": {"telegram": {"allowed_groups": [-100999]}},
    }
    out, changed = migrate_legacy_claude_agent_topic(doc)
    assert changed is True
    agent = out["coding_agents"]["agents"]["legacy-claude-agent"]
    assert agent["telegram_bindings"] == [{"chat_id": "-100999", "topic_ids": [42]}]
    assert "claude_agent_topic_id" not in out["telegram"]


def test_migrate_noop_when_agents_already_configured() -> None:
    doc = {
        "schema_version": 1,
        "telegram": {"claude_agent_topic_id": 42},
        "coding_agents": {"agents": {"existing": {"type": "alrca", "enabled": True}}},
        "channels": {"telegram": {"allowed_groups": [-100999]}},
    }
    _out, changed = migrate_legacy_claude_agent_topic(doc)
    assert changed is False
