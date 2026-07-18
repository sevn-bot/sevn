"""Gate contracts for bundled Discogs core skills (W1.2 / D3)."""

from __future__ import annotations

from pathlib import Path

from tests.skills.discogs.conftest import (
    DISCOGS_SKILL_IDS,
    enabled_discogs_config,
    import_discogs_module,
)

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.skills.manager import SkillsManager


def _discogs_mod() -> object:
    return import_discogs_module("sevn.skills.discogs")


def test_discogs_skill_ids_cover_five_domains() -> None:
    mod = _discogs_mod()
    assert tuple(mod.DISCOGS_SKILL_IDS) == DISCOGS_SKILL_IDS


def test_gate_skips_when_config_absent() -> None:
    mod = _discogs_mod()
    assert mod.gate_discogs_core_skills(None) == "skip"


def test_gate_loads_when_group_enabled() -> None:
    mod = _discogs_mod()
    assert mod.gate_discogs_core_skills(enabled_discogs_config()) == "load"


def test_discogs_config_enabled_defaults_false() -> None:
    mod = _discogs_mod()
    assert mod.discogs_config_enabled(None) is False
    assert mod.discogs_config_enabled(enabled_discogs_config(group_enabled=False)) is False
    assert mod.discogs_config_enabled(enabled_discogs_config()) is True


def test_manager_omits_all_discogs_skills_when_disabled(tmp_path: Path) -> None:
    _discogs_mod()
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    for skill_id in DISCOGS_SKILL_IDS:
        assert skill_id not in mgr._records


def test_manager_loads_all_discogs_skills_when_enabled(tmp_path: Path) -> None:
    _discogs_mod()
    mgr = SkillsManager.shared(
        tmp_path,
        (BUNDLED_SKILLS_ROOT,),
        config=enabled_discogs_config(),
    )
    for skill_id in DISCOGS_SKILL_IDS:
        assert skill_id in mgr._records


def test_manager_skips_single_skill_when_sub_flag_false(tmp_path: Path) -> None:
    _discogs_mod()
    cfg = enabled_discogs_config(sub_flags={"database": False})
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,), config=cfg)
    assert "discogs-database" not in mgr._records
    assert "discogs-marketplace" in mgr._records
