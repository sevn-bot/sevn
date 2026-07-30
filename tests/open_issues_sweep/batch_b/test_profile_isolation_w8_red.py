"""W8.6 — profile-based routing isolation (#79 → W12, D14)."""

from __future__ import annotations

import pytest
from tests.open_issues_sweep.batch_b.conftest import baseline_minimal_workspace


def _routing_profiles_workspace() -> object:
    doc = baseline_minimal_workspace().model_dump()
    doc["routing"] = {
        "default_profile": "safe",
        "unknown_route": "default",
        "profiles": {
            "research": {
                "model": "anthropic/claude-sonnet-4-20250514",
                "system_prompt": "Research profile.",
                "skills": ["web-search"],
                "memory_namespace": "research",
                "permissions_profile": "research_perms",
            },
            "ops": {
                "model": "openai/gpt-4o",
                "system_prompt": "Ops profile.",
                "skills": ["log_query"],
                "memory_namespace": "ops",
                "permissions_profile": "ops_perms",
            },
            "safe": {
                "model": "minimax/MiniMax-M2.7",
                "skills": [],
                "memory_namespace": "default",
                "permissions_profile": "safe_perms",
            },
        },
        "channel_map": {
            "telegram:forum:1:42": "research",
            "webhook:ingress-a": "ops",
        },
    }
    doc["permissions"] = {
        "default_profile": "safe_perms",
        "profiles": {
            "research_perms": {"deny_tools": ["terminal_run"]},
            "ops_perms": {"deny_tools": ["browser"]},
            "safe_perms": {"mode": "deny_all"},
        },
    }
    from sevn.config.workspace_config import WorkspaceConfig

    return WorkspaceConfig.model_validate(doc)


def test_two_profiles_have_distinct_memory_skill_and_permission_sets() -> None:
    from sevn.config.routing import resolve_routing_profile_bundle

    cfg = _routing_profiles_workspace()
    research = resolve_routing_profile_bundle(cfg, profile_name="research")
    ops = resolve_routing_profile_bundle(cfg, profile_name="ops")
    assert research.memory_namespace != ops.memory_namespace
    assert research.skill_allowlist != ops.skill_allowlist
    assert research.permission_policy.may_invoke(
        "terminal_run"
    ) != ops.permission_policy.may_invoke(
        "terminal_run",
    )


def test_channel_map_selects_expected_profile() -> None:
    from sevn.config.routing import resolve_routing_profile_for_turn

    cfg = _routing_profiles_workspace()
    assert (
        resolve_routing_profile_for_turn(
            cfg,
            channel="telegram",
            scope_key="forum:1:42",
        )
        == "research"
    )
    assert (
        resolve_routing_profile_for_turn(
            cfg,
            channel="webhook",
            scope_key="ingress-a",
        )
        == "ops"
    )


def test_unknown_route_hits_configured_default_profile() -> None:
    from sevn.config.routing import resolve_routing_profile_for_turn

    cfg = _routing_profiles_workspace()
    assert (
        resolve_routing_profile_for_turn(
            cfg,
            channel="telegram",
            scope_key="forum:9:999",
        )
        == "safe"
    )


def test_unknown_route_deny_mode_blocks_turn() -> None:
    from sevn.config.routing import (
        RoutingProfileDenied,
        resolve_routing_profile_for_turn,
    )

    doc = _routing_profiles_workspace().model_dump()
    doc["routing"]["unknown_route"] = "deny"
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = WorkspaceConfig.model_validate(doc)
    with pytest.raises(RoutingProfileDenied, match="unknown route"):
        resolve_routing_profile_for_turn(cfg, channel="telegram", scope_key="forum:9:999")
