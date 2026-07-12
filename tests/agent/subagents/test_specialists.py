"""Unit tests for specialist resolution and gating (W3.2/W3.4, D8)."""

from __future__ import annotations

from sevn.agent.subagents.specialists import (
    resolve_specialist,
    resolve_specialist_executor,
    resolve_specialist_transport,
    specialist_spawn_allowed,
)
from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig


def test_resolve_specialist_transport_precedence() -> None:
    spec = SpecialistConfig(model="minimax-3", provider="minimax")
    assert resolve_specialist_transport({}, spec) == "chat_completions"
    assert (
        resolve_specialist_transport({"minimax": {"transport": "anthropic"}}, spec) == "anthropic"
    )
    assert (
        resolve_specialist_transport(
            {"models": {"minimax-3": {"transport": "responses"}}},
            spec,
        )
        == "responses"
    )


def test_resolve_specialist_executor_round_trip() -> None:
    cfg = SubAgentsWorkspaceConfig(
        specialists={
            "media_generator": SpecialistConfig(
                model="minimax-3",
                provider="minimax",
                assigned_to=["tier_b"],
                requestable_by=["triager", "tier_b"],
            ),
        },
    )
    entry = resolve_specialist(cfg, "media_generator")
    assert entry is not None
    resolved = resolve_specialist_executor("media_generator", entry)
    assert resolved.name == "media_generator"
    assert resolved.provider == "minimax"
    assert resolved.transport_name == "chat_completions"


def test_specialist_spawn_allowed_assigned_requestable_and_grant() -> None:
    spec = SpecialistConfig(
        model="minimax-3",
        provider="minimax",
        assigned_to=["tier_b"],
        requestable_by=["triager"],
    )
    assert specialist_spawn_allowed(spec, role="tier_b")
    assert not specialist_spawn_allowed(spec, role="tier_c")
    assert specialist_spawn_allowed(spec, role="tier_c", granted_by_triager=True)
    assert not specialist_spawn_allowed(spec, role="tier_c", granted_by_triager=False)
