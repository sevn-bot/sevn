"""Config tests for ``agent.diagnostics`` slot (W4)."""

from __future__ import annotations

from sevn.config.model_resolution import (
    diagnostics_agent_enabled,
    resolve_diagnostics_model,
)
from sevn.config.workspace_config import WorkspaceConfig


def test_diagnostics_agent_enabled_defaults_true() -> None:
    assert diagnostics_agent_enabled(WorkspaceConfig.minimal()) is True


def test_diagnostics_agent_enabled_respects_false() -> None:
    cfg = WorkspaceConfig.minimal(agent={"diagnostics": {"enabled": False}})
    assert diagnostics_agent_enabled(cfg) is False


def test_resolve_diagnostics_model_defaults_to_tier_b_slot() -> None:
    cfg = WorkspaceConfig.minimal(
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": "openai/gpt-4o-mini"},
        },
    )
    assert resolve_diagnostics_model(cfg) == "openai/gpt-4o-mini"


def test_resolve_diagnostics_model_slot_override() -> None:
    cfg = WorkspaceConfig.minimal(
        agent={"diagnostics": {"model": "anthropic/claude-sonnet-4"}},
        providers={"tier_default": {"triager": "openai/gpt-4o-mini"}},
    )
    assert resolve_diagnostics_model(cfg) == "anthropic/claude-sonnet-4"


def test_resolve_diagnostics_model_cli_override_wins() -> None:
    cfg = WorkspaceConfig.minimal(
        agent={"diagnostics": {"model": "anthropic/claude-sonnet-4"}},
        providers={"tier_default": {"triager": "openai/gpt-4o-mini"}},
    )
    assert resolve_diagnostics_model(cfg, override="openai/gpt-4o") == "openai/gpt-4o"
