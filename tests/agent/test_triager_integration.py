"""Opt-in Triager integration slice (`specs/13-rlm-triager.md` §10.4).

Run with ``make test-integration`` or ``pytest -m integration`` (excluded from
default ``make test`` / ``make ci``).
"""

from __future__ import annotations

import json

import pytest

from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.models import ComplexityTier
from sevn.agent.triager.run import triage_turn
from sevn.config.workspace_config import parse_workspace_config


@pytest.mark.integration
@pytest.mark.asyncio
async def test_triager_stub_off_mocked_proxy_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SEVN_TRIAGER_STUB=0`` uses live pydantic-ai when the proxy transport is mocked."""
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    monkeypatch.setenv("SEVN_PROXY_URL", "http://triager-integration.test")
    triage_payload = {
        "intent": "NEW_REQUEST",
        "complexity": "B",
        "first_message": "Live path ok.",
        "tools": [],
        "skills": [],
        "mcp_servers_required": [],
        "confidence": 0.75,
        "requires_vision": False,
        "requires_document": False,
        "disregard": False,
    }

    async def fake_post(**kwargs: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(triage_payload),
                    },
                },
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3},
        }

    monkeypatch.setattr(
        "sevn.agent.providers.transport.transport_http.post_llm_json",
        fake_post,
    )
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "providers": {
                "tier_default": {"triager": "openai:gpt-4o-mini"},
                "models": {"openai:gpt-4o-mini": {"transport": "chat_completions"}},
            },
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="sess-int"),
        incoming=ApprovedUserTurn(text="ping"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="ping"),
    )
    assert out.complexity == ComplexityTier.B
    assert out.first_message == "Live path ok."
    assert out.confidence == 0.75
