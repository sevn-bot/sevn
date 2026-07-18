"""Presence/shape contracts for Discogs docs and onboarding (W1.12 / D22/D23)."""

from __future__ import annotations

import json

import pytest
from tests.skills.discogs.conftest import DISCOGS_SKILL_IDS, REPO_ROOT

INDEX_PATH = REPO_ROOT / "src" / "sevn" / "data" / "skills" / "INDEX.md"
ONBOARDING_PATH = REPO_ROOT / "src" / "sevn" / "data" / "onboarding_capabilities.json"
README_CANDIDATES = (
    REPO_ROOT / "docs" / "readmes" / "discogs.md",
    REPO_ROOT / "about-sevn.bot" / "docs" / "discogs-skills.md",
)


@pytest.mark.parametrize("skill_id", DISCOGS_SKILL_IDS)
def test_index_lists_discogs_skill(skill_id: str) -> None:
    text = INDEX_PATH.read_text(encoding="utf-8")
    assert skill_id in text


def test_onboarding_has_discogs_group_b_row() -> None:
    raw = json.loads(ONBOARDING_PATH.read_text(encoding="utf-8"))
    caps = raw.get("capabilities", [])
    assert isinstance(caps, list)
    discogs_caps = [
        c
        for c in caps
        if isinstance(c, dict)
        and (
            str(c.get("capability_id", "")).startswith("skill.discogs")
            or "skills.discogs.enabled" in (c.get("config_paths") or [])
        )
    ]
    assert discogs_caps, "missing Group-B Discogs onboarding capability"


def test_discogs_readme_exists_with_both_auth_sections() -> None:
    readme = next((path for path in README_CANDIDATES if path.is_file()), None)
    assert readme is not None, f"expected README at one of {README_CANDIDATES}"
    text = readme.read_text(encoding="utf-8").lower()
    assert "user" in text
    assert "token" in text
    assert "oauth" in text
    assert "verifier" in text or "authorize" in text
