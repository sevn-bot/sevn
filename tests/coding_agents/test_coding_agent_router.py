"""Tests for CodingAgentRouter operator commands and conversational surface."""

from __future__ import annotations

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.routing.coding_agent_router import CodingAgentRouter


def _router() -> CodingAgentRouter:
    ws = WorkspaceConfig.model_validate(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "coding_agents": {
                "enabled": True,
                "agents": {
                    "alrca-infra": {
                        "type": "alrca",
                        "enabled": True,
                        "executor": "cursor",
                        "telegram_bindings": [{"chat_id": "-1001", "topic_ids": [5]}],
                    },
                    "lap-opencode": {
                        "type": "litellm_lap",
                        "enabled": True,
                        "lap_agent_id": "uuid-1",
                        "telegram_bindings": [{"chat_id": "-1002", "topic_ids": [9]}],
                    },
                },
            },
        },
    )
    return CodingAgentRouter(workspace=ws, trace=NullTraceSink())


def test_match_binding_on_telegram_metadata() -> None:
    router = _router()
    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="hello",
        metadata={"chat_id": -1001, "topic_id": 5},
    )
    assert router.match_binding(msg) == "alrca-infra"


def test_alrca_status_command_reply() -> None:
    router = _router()
    reply = router._handle_alrca_command("alrca-infra", "/status")
    assert reply is not None
    assert "ALRCA agent" in reply
    assert "cursor" in reply


def test_lap_passthrough_conversational_reply() -> None:
    router = _router()
    text = router._handle_conversational("lap-opencode", "ship it")
    assert "LAP passthrough" in text
    assert "uuid-1" in text


@pytest.mark.asyncio
async def test_handle_operator_message_emits_without_adapter() -> None:
    router = _router()
    msg = IncomingMessage(
        channel="telegram",
        user_id="1",
        text="/loop start",
        metadata={"chat_id": -1001, "topic_id": 5},
    )
    await router.handle_operator_message(
        msg,
        agent_id="alrca-infra",
        session_id="sess-1",
        correlation_id="turn-1",
        adapter=None,
    )
    assert "alrca-infra" in router._loop_active
