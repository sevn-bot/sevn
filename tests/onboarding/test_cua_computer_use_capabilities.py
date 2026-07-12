"""Onboarding capability rows and install actions for cua skills (W0.4 / W1.4)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sevn.onboarding.capabilities_manifest import load_manifest, skill_capability_id
from sevn.onboarding.seed import _CAPABILITY_OPT_IN_SKILL_IDS, _OPT_IN_CORE_SKILL_IDS


def test_skill_capability_id_mapping() -> None:
    """Kebab skill names map to manifest capability ids."""
    assert skill_capability_id("computer-use") == "skill.computer_use"
    assert skill_capability_id("cua-agent") == "skill.cua_agent"
    assert skill_capability_id("lume") == "skill.lume"


def test_computer_use_capability_row_exists() -> None:
    manifest = load_manifest()
    ids = {row.capability_id for row in manifest.capabilities}
    assert "skill.computer_use" in ids


@pytest.mark.parametrize("capability_id", ["skill.cua_agent", "skill.lume"])
def test_new_capability_rows_present(capability_id: str) -> None:
    manifest = load_manifest()
    ids = {row.capability_id for row in manifest.capabilities}
    assert capability_id in ids


def test_computer_use_has_cua_cli_install_action() -> None:
    manifest = load_manifest()
    row = next(c for c in manifest.capabilities if c.capability_id == "skill.computer_use")
    action_ids = {a.id for a in row.install_actions}
    assert "skill.computer_use.cua_cli" in action_ids


@pytest.mark.parametrize(
    ("capability_id", "noop_id", "validator_attr"),
    [
        ("skill.cua_agent", "skill.cua_agent.noop", "run_cua_agent_validate"),
        ("skill.lume", "skill.lume.noop", "run_lume_validate"),
    ],
)
def test_new_noop_install_actions_dispatch_validators(
    capability_id: str,
    noop_id: str,
    validator_attr: str,
) -> None:
    manifest = load_manifest()
    row = next(c for c in manifest.capabilities if c.capability_id == capability_id)
    assert any(a.id == noop_id for a in row.install_actions)

    import sevn.onboarding.install_actions.special as special

    assert hasattr(special, validator_attr)


@pytest.mark.asyncio
async def test_executor_runs_cua_agent_noop_validator() -> None:
    from sevn.onboarding.capabilities_manifest import InstallAction
    from sevn.onboarding.install_actions.executors import _collect_events, execute_install_action

    noop = InstallAction(
        id="skill.cua_agent.noop",
        kind="noop",
        argv=[],
        fatal=False,
    )
    with (
        patch(
            "sevn.onboarding.install_actions.executors.run_computer_use_validate",
            return_value=(0, "unused"),
        ),
        patch(
            "sevn.onboarding.install_actions.special.run_cua_agent_validate",
            return_value=(0, "ok"),
        ) as mocked,
    ):
        events = await _collect_events(
            execute_install_action(
                noop,
                install_root=__import__("pathlib").Path("."),
                capability_id="skill.cua_agent",
                merged_config={"skills": {}},
            )
        )
    assert events[-1]["status"] == "ok"
    mocked.assert_called_once()


@pytest.mark.asyncio
async def test_live_validate_dispatches_cua_agent_noop() -> None:
    from sevn.onboarding.live_validate import run_live_validation

    merged = {
        "schema_version": 1,
        "skills": {"cua_agent": {"enabled": True}, "computer_use": {"enabled": True}},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with patch(
        "sevn.onboarding.install_actions.special.run_cua_agent_validate",
        return_value=(0, "validated"),
    ):
        report = await run_live_validation(
            workspace_root=__import__("tempfile").mkdtemp(),
            merged_preview=merged,
            profile_id=None,
        )
    assert any(c.detail == "validated" for c in report.checks)


@pytest.mark.parametrize("skill_id", ["cua-agent", "lume"])
def test_seed_opt_in_core_skill_ids(skill_id: str) -> None:
    assert skill_id in _OPT_IN_CORE_SKILL_IDS


@pytest.mark.parametrize(
    ("capability_id", "skill_id"),
    [
        ("skill.cua_agent", "cua-agent"),
        ("skill.lume", "lume"),
    ],
)
def test_seed_capability_opt_in_map(capability_id: str, skill_id: str) -> None:
    assert _CAPABILITY_OPT_IN_SKILL_IDS.get(capability_id) == skill_id
