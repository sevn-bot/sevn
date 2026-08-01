"""Thermos follow-ups for W12 isolation semantics."""

from __future__ import annotations

import pytest


def test_explicit_empty_skills_list_denies_all_skills() -> None:
    from sevn.config.routing import resolve_routing_profile_bundle
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig.minimal(routing={"profiles": {"safe": {"skills": []}}})
    bundle = resolve_routing_profile_bundle(cfg, profile_name="safe")
    assert bundle.skill_allowlist == frozenset()


def test_absent_skills_key_means_no_restriction() -> None:
    from sevn.config.routing import _skill_allowlist_for_profile
    from sevn.config.sections.routing import RoutingWorkspaceSectionConfig

    section = RoutingWorkspaceSectionConfig(
        profiles={"open": {"model": "openai/gpt-4o"}},
    )
    entry = section.profiles["open"]
    assert _skill_allowlist_for_profile(section, "open", entry) is None


def test_secrets_scope_prefixes_logical_keys_during_turn() -> None:
    from sevn.config.routing import prefix_secrets_logical_key
    from sevn.security.secrets.routing_scope import (
        bind_routing_secrets_scope,
        current_routing_secrets_scope,
        reset_routing_secrets_scope,
        scoped_secret_logical_key,
    )

    assert prefix_secrets_logical_key("research", "api.token") == "research/api.token"
    token = bind_routing_secrets_scope("research")
    try:
        assert current_routing_secrets_scope() == "research"
        assert scoped_secret_logical_key("k") == "research/k"
    finally:
        reset_routing_secrets_scope(token)
    assert current_routing_secrets_scope() is None


@pytest.mark.asyncio
async def test_triage_turn_threads_routing_profile_model_into_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile / --once overrides must reach the real structured triage call."""
    import json

    from sevn.agent.triager import run as triager_run
    from sevn.agent.triager.context import (
        ApprovedUserTurn,
        RegistryIndexEntry,
        RegistrySnapshot,
        SessionView,
        TriagePromptContext,
    )
    from sevn.agent.triager.run import StructuredOutputCallResult
    from sevn.config.workspace_config import parse_workspace_config

    monkeypatch.setenv("SEVN_TRIAGER_STUB", "0")
    seen: list[str] = []

    async def fake_call(**kwargs: object) -> StructuredOutputCallResult:
        model_id = kwargs.get("model_id")
        assert isinstance(model_id, str)
        seen.append(model_id)
        return StructuredOutputCallResult(
            json=json.dumps(
                {
                    "intent": "NEW_REQUEST",
                    "complexity": "B",
                    "first_message": "ok",
                    "tools": [],
                    "skills": [],
                    "mcp_servers_required": [],
                    "confidence": 0.9,
                    "requires_vision": False,
                    "requires_document": False,
                    "disregard": False,
                },
            ),
            prep_ms=1.0,
            model_ms=2.0,
            serialize_ms=0.1,
            model_request_count=1,
        )

    monkeypatch.setattr(triager_run, "structured_output_call", fake_call)
    ws = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {
                "fast_greeting_path": False,
                "fast_continuation_path": False,
                "cheap_model_id": "anthropic:claude-3-5-haiku",
            },
            "providers": {"tier_default": {"triager": "minimax/MiniMax-M3"}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    registry = RegistrySnapshot(
        tools=[
            RegistryIndexEntry(
                sort_name="read",
                identifier="read",
                display_line="read - file read",
            ),
        ],
        skills=[],
    )
    await triager_run.triage_turn(
        workspace=ws,
        session=SessionView(session_id="s-profile"),
        incoming=ApprovedUserTurn(text="go ahead with research"),
        registry_snapshot=registry,
        triage_context=TriagePromptContext(
            current_message="go ahead with research",
            turn_id="profile-model",
        ),
        routing_profile_model="openai/gpt-4o",
    )
    assert seen == ["openai/gpt-4o"]
