"""Triager persona ``system_prompt`` and anti-vendor routing (recovery Wave A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.run import structured_output_call, triage_turn
from sevn.config.workspace_config import parse_workspace_config

_PROVIDER_BRANDS = ("MiniMax", "Claude", "GPT", "Anthropic", "OpenAI")


@pytest.mark.asyncio
async def test_structured_output_call_sets_persona_system_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("TriagerPersonaMarker", encoding="utf-8")
    captured: dict[str, object] = {}

    async def _fake_run(_prompt: str) -> object:
        class _Result:
            output = parse_workspace_config(
                {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
            )

        return _Result()

    class _FakeAgent:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def run(self, _prompt: str) -> object:
            triage_payload = {
                "intent": "NEW_REQUEST",
                "complexity": "B",
                "first_message": "Hello from Sevn.",
                "tools": [],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.9,
                "requires_vision": False,
                "requires_document": False,
                "disregard": False,
            }

            class _Out:
                def model_dump_json(self) -> str:
                    return json.dumps(triage_payload)

            class _Result:
                output = _Out()

            return _Result()

    monkeypatch.setattr("sevn.agent.triager.run.resolve_model", lambda **_: (None, object()))
    monkeypatch.setattr("sevn.agent.triager.run.build_tier_b_function_model", lambda **_: object())
    monkeypatch.setattr("sevn.agent.triager.run.Agent", _FakeAgent)

    await structured_output_call(
        workspace=parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
        ),
        model_id="openai:gpt-4o-mini",
        transport_name="chat_completions",
        user_prompt="route",
        seed=None,
        content_root=root,
    )

    system_prompt = str(captured.get("system_prompt", ""))
    assert "TriagerPersonaMarker" in system_prompt
    assert "TriageResult" in system_prompt


@pytest.mark.asyncio
async def test_triage_turn_first_message_avoids_provider_brands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "IDENTITY.md").write_text("Name: Sevn", encoding="utf-8")
    monkeypatch.setenv("SEVN_TRIAGER_STUB", "1")
    monkeypatch.setenv(
        "SEVN_TRIAGER_STUB_JSON",
        json.dumps(
            {
                "intent": "NEW_REQUEST",
                "complexity": "B",
                "first_message": "I am Sevn, your workspace assistant.",
                "tools": [],
                "skills": [],
                "mcp_servers_required": [],
                "confidence": 0.9,
                "requires_vision": False,
                "requires_document": False,
                "disregard": False,
            },
        ),
    )
    ws = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    out = await triage_turn(
        workspace=ws,
        session=SessionView(session_id="s"),
        incoming=ApprovedUserTurn(text="who are you?"),
        registry_snapshot=RegistrySnapshot(),
        triage_context=TriagePromptContext(current_message="who are you?"),
        content_root=root,
    )
    lowered = out.first_message.lower()
    for brand in _PROVIDER_BRANDS:
        assert brand.lower() not in lowered
