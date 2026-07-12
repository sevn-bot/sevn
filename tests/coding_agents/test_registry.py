"""Tests for coding agent registry and Telegram binding match."""

from __future__ import annotations

from sevn.coding_agents.registry import (
    binding_matches,
    list_agent_summaries,
    match_telegram_binding,
)
from sevn.config.sections.coding_agents import TelegramBindingConfig
from sevn.config.workspace_config import WorkspaceConfig


def _workspace_with_agent(**agent_body: object) -> WorkspaceConfig:
    return WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "coding_agents": {
                "enabled": True,
                "agents": {"infra": agent_body},
            },
        },
    )


def test_binding_matches_topic_and_whole_chat() -> None:
    whole = TelegramBindingConfig(chat_id="-1001")
    assert binding_matches(whole, chat_id="-1001", topic_id=99)
    scoped = TelegramBindingConfig(chat_id="-1001", topic_ids=[42])
    assert binding_matches(scoped, chat_id="-1001", topic_id=42)
    assert not binding_matches(scoped, chat_id="-1001", topic_id=7)


def test_match_telegram_binding_returns_agent_for_forum_topic() -> None:
    ws = _workspace_with_agent(
        type="alrca",
        enabled=True,
        executor="cursor",
        telegram_bindings=[{"chat_id": "-100123", "topic_ids": [77]}],
    )
    assert match_telegram_binding(ws, channel="telegram", chat_id="-100123", topic_id=77) == "infra"
    assert match_telegram_binding(ws, channel="telegram", chat_id="-100123", topic_id=5) is None


def test_match_skips_disabled_agent() -> None:
    ws = _workspace_with_agent(
        type="alrca",
        enabled=False,
        telegram_bindings=[{"chat_id": "-100123", "topic_ids": [1]}],
    )
    assert match_telegram_binding(ws, channel="telegram", chat_id="-100123", topic_id=1) is None


def test_list_agent_summaries_includes_bindings_and_idle_run() -> None:
    ws = _workspace_with_agent(
        type="litellm_lap",
        enabled=True,
        lap_agent_id="lap-1",
        telegram_bindings=[{"chat_id": "-100123", "topic_ids": None}],
    )
    rows = list_agent_summaries(ws)
    assert len(rows) == 1
    assert rows[0]["id"] == "infra"
    assert rows[0]["type"] == "litellm_lap"
    assert rows[0]["bindings"][0]["scope"] == "whole_chat"
    assert rows[0]["last_run"]["state"] == "idle"
