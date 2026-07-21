"""PR #35 / W2 — ``obsidian-cli`` must honour ``skills.obsidian_cli.enabled``.

RED until Wave W2 adds a gate mirroring ``gate_openwiki_core_skill``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager

_OBSIDIAN_CLI_ID = "obsidian-cli"


def _enabled_config() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={"obsidian_cli": {"enabled": True}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


def _disabled_config() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={"obsidian_cli": {"enabled": False}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


@pytest.mark.xfail(reason="green after W2: obsidian-cli opt-in gate", strict=False)
def test_manager_omits_obsidian_cli_when_disabled(tmp_path: Path) -> None:
    """Opt-in default:false — skill must not load without an explicit enable."""
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,), config=_disabled_config())
    assert _OBSIDIAN_CLI_ID not in mgr._records


@pytest.mark.xfail(reason="green after W2: obsidian-cli opt-in gate", strict=False)
def test_manager_omits_obsidian_cli_when_config_absent(tmp_path: Path) -> None:
    """No skills.obsidian_cli block → treat as disabled (mirrors openwiki)."""
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert _OBSIDIAN_CLI_ID not in mgr._records


@pytest.mark.xfail(reason="green after W2: obsidian-cli opt-in gate", strict=False)
def test_manager_includes_obsidian_cli_when_enabled(tmp_path: Path) -> None:
    """When ``skills.obsidian_cli.enabled`` is true the skill is discoverable."""
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,), config=_enabled_config())
    assert _OBSIDIAN_CLI_ID in mgr._records
    record = mgr.get_record(_OBSIDIAN_CLI_ID)
    assert record.canonical_id == _OBSIDIAN_CLI_ID
