"""OpenWiki onboarding install integration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.onboarding.capabilities_manifest import InstallAction
from sevn.onboarding.install_actions.executors import execute_install_action
from sevn.onboarding.install_actions.special import run_openwiki_validate
from sevn.onboarding.install_orchestrator import build_install_plan


def test_build_install_plan_includes_openwiki_when_skill_enabled() -> None:
    plan = build_install_plan({"skills": {"openwiki": {"enabled": True}}})
    selected = set(plan.selected_capability_ids)
    assert "extra.openwiki" in selected
    assert "skill.openwiki" in selected
    action_ids = [step.action.id for step in plan.steps]
    assert "extra.openwiki.npm" in action_ids
    assert "skill.openwiki.secret" in action_ids


@pytest.mark.asyncio
async def test_secret_required_accepts_auto_mapped_provider_secret(tmp_path: Path) -> None:
    action = InstallAction(
        id="skill.openwiki.secret",
        kind="secret_required",
        argv=["integration.openwiki.llm_api_key"],
        fatal=False,
    )
    merged = WorkspaceConfig.minimal(
        skills={"openwiki": {"enabled": True, "provider": "openai"}},
        providers={"openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"}},
    ).model_dump(mode="json")

    async def _collect_events(aiter):
        return [event async for event in aiter]

    with patch(
        "sevn.skills.openwiki_secrets.openwiki_credentials_resolved",
        new=AsyncMock(return_value=(True, "auto-mapped from provider openai")),
    ):
        events = await _collect_events(
            execute_install_action(
                action,
                install_root=Path("."),
                capability_id="skill.openwiki",
                merged_config=merged,
                content_root=tmp_path,
            )
        )
    assert events[-1]["status"] == "ok"


def test_run_openwiki_validate_skips_when_skill_disabled() -> None:
    merged = WorkspaceConfig.minimal(skills={"openwiki": {"enabled": False}}).model_dump(
        mode="json"
    )
    code, detail = run_openwiki_validate(merged_config=merged)
    assert code == 0
    assert "not enabled" in detail


@pytest.mark.asyncio
async def test_run_openwiki_validate_works_inside_running_event_loop(
    tmp_path: Path,
) -> None:
    """Regression: nested ``asyncio.run`` must not abort install orchestration."""
    merged = WorkspaceConfig.minimal(
        skills={"openwiki": {"enabled": True, "provider": "openai"}},
    ).model_dump(mode="json")
    with (
        patch(
            "sevn.skills.openwiki_install.openwiki_cli_installed",
            return_value=True,
        ),
        patch(
            "sevn.skills.openwiki_secrets.openwiki_credentials_resolved",
            new=AsyncMock(return_value=(True, "credentials ready")),
        ),
    ):
        code, detail = run_openwiki_validate(merged_config=merged, content_root=tmp_path)
    assert code == 0
    assert "ready" in detail
