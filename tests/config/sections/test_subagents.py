"""Sub-agents (L1/L2) section config tests (`specs/36-sub-agents.md` D2/D8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.sections.subagents import (
    SpecialistConfig,
    SubAgentRoleLimits,
    SubAgentsWorkspaceConfig,
    resolve_limits,
)
from sevn.config.workspace_config import parse_workspace_config


def test_resolve_limits_defaults_when_cfg_is_none() -> None:
    assert resolve_limits(None, "tier_b") == (5, 3)


def test_subagents_config_defaults() -> None:
    cfg = SubAgentsWorkspaceConfig()
    assert cfg.enabled is True
    assert cfg.max_level1_default == 5
    assert cfg.max_level2_default == 3
    assert cfg.max_override is None
    assert cfg.agents == {}
    assert cfg.specialists == {}
    assert resolve_limits(cfg, "triager") == (5, 3)


def test_resolve_limits_per_role_override() -> None:
    cfg = SubAgentsWorkspaceConfig(
        agents={"tier_b": SubAgentRoleLimits(max_level1=2, max_level2=1)},
    )
    assert resolve_limits(cfg, "tier_b") == (2, 1)
    # Unconfigured roles keep the workspace defaults.
    assert resolve_limits(cfg, "tier_c") == (5, 3)


def test_resolve_limits_per_role_partial_override_falls_back_per_field() -> None:
    """Only ``max_level1`` set on the role; ``max_level2`` still uses the default."""
    cfg = SubAgentsWorkspaceConfig(
        max_level2_default=4,
        agents={"tier_d": SubAgentRoleLimits(max_level1=1)},
    )
    assert resolve_limits(cfg, "tier_d") == (1, 4)


def test_resolve_limits_max_override_ceiling_wins_over_per_role() -> None:
    """D2 precedence: ``max_override`` is a ceiling over every resolved limit."""
    cfg = SubAgentsWorkspaceConfig(
        max_override=1,
        agents={"tier_b": SubAgentRoleLimits(max_level1=2, max_level2=1)},
    )
    assert resolve_limits(cfg, "tier_b") == (1, 1)


def test_resolve_limits_max_override_ceiling_wins_over_defaults() -> None:
    cfg = SubAgentsWorkspaceConfig(max_override=2)
    assert resolve_limits(cfg, "triager") == (2, 2)


def test_resolve_limits_max_override_above_effective_limit_is_a_noop() -> None:
    """A ceiling higher than the resolved limit never raises it."""
    cfg = SubAgentsWorkspaceConfig(max_override=99)
    assert resolve_limits(cfg, "triager") == (5, 3)


def test_resolve_limits_invalid_role_rejected() -> None:
    with pytest.raises(ValueError, match="unknown subagents role"):
        resolve_limits(None, "bogus")


def test_subagents_agents_dict_rejects_invalid_role_key() -> None:
    with pytest.raises(ValidationError):
        SubAgentsWorkspaceConfig.model_validate({"agents": {"bogus": {"max_level1": 1}}})


def test_subagents_agents_dict_rejects_invalid_role_key_via_workspace_config() -> None:
    with pytest.raises(ValidationError):
        parse_workspace_config(
            {
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "subagents": {"agents": {"bogus": {"max_level1": 1}}},
            },
        )


def test_specialist_config_round_trip() -> None:
    specialist = SpecialistConfig(
        model="minimax-3",
        provider="minimax",
        assigned_to=["tier_b"],
        requestable_by=["triager", "tier_b"],
        max_concurrent=2,
    )
    cfg = SubAgentsWorkspaceConfig(specialists={"media_generator": specialist})
    assert cfg.specialists["media_generator"].model == "minimax-3"
    assert cfg.specialists["media_generator"].provider == "minimax"
    assert cfg.specialists["media_generator"].assigned_to == ["tier_b"]
    assert cfg.specialists["media_generator"].requestable_by == ["triager", "tier_b"]
    assert cfg.specialists["media_generator"].max_concurrent == 2

    dumped = cfg.model_dump(mode="python")
    restored = SubAgentsWorkspaceConfig.model_validate(dumped)
    assert restored.specialists["media_generator"].model == "minimax-3"


def test_specialists_default_empty_via_workspace_config() -> None:
    """W1.4: specialists default empty — no ``media_generator`` shipped as a default."""
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert cfg.subagents is None


def test_workspace_config_subagents_round_trip() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "subagents": {
                "enabled": True,
                "max_level1_default": 5,
                "max_level2_default": 3,
                "max_override": None,
                "agents": {"tier_b": {"max_level1": 2}},
                "specialists": {
                    "media_generator": {
                        "model": "minimax-3",
                        "provider": "minimax",
                        "assigned_to": ["tier_b"],
                        "requestable_by": ["triager", "tier_b"],
                    },
                },
            },
        },
    )
    assert cfg.subagents is not None
    assert cfg.subagents.enabled is True
    assert resolve_limits(cfg.subagents, "tier_b") == (2, 3)
    assert "media_generator" in cfg.subagents.specialists
