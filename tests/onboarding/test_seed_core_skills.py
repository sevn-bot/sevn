"""Onboarding seed deploys bundled core skills into workspace."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

from sevn.onboarding.seed import (
    expected_core_skill_ids,
    list_deployed_core_skill_ids,
    seed_bundled_skills,
    verify_core_skills_deployed,
)


def test_seed_bundled_skills_then_verify_empty_missing(tmp_path: Path) -> None:
    """Fresh workspace receives all required core skill packages."""
    written = seed_bundled_skills(tmp_path)
    assert written
    missing = verify_core_skills_deployed(tmp_path)
    assert missing == []
    assert len(expected_core_skill_ids()) >= 20


def test_refresh_bundled_core_skills_overwrites_stale_package(tmp_path: Path) -> None:
    """Sync refresh replaces an existing core skill tree from the bundled source."""
    from sevn.onboarding.seed import refresh_bundled_core_skills

    seed_bundled_skills(tmp_path)
    pw = tmp_path / "skills" / "core" / "playwright-browser"
    stale = pw / "scripts" / "click.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("# stale marker\n", encoding="utf-8")
    refreshed = refresh_bundled_core_skills(tmp_path)
    assert "playwright-browser" in refreshed
    assert not stale.exists()
    assert (pw / "scripts" / "click_element.py").is_file()


def test_list_deployed_core_skill_ids_empty_without_core_dir(tmp_path: Path) -> None:
    """Missing skills/core returns an empty list instead of raising."""
    assert list_deployed_core_skill_ids(tmp_path) == []


def test_seed_bundled_skills_creates_core_dir_when_bundle_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Save/promote must not fail when packaged core skills tree is absent."""
    monkeypatch.setattr(
        "sevn.onboarding.seed.BUNDLED_SKILLS_ROOT",
        tmp_path / "no_bundled_skills",
    )
    seed_bundled_skills(tmp_path)
    assert (tmp_path / "skills" / "core").is_dir()
    assert list_deployed_core_skill_ids(tmp_path) == []
