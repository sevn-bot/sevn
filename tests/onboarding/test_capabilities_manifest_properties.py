"""Property-based tests for onboarding capability id helpers."""

from __future__ import annotations

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sevn.data.skills_index import read_skills_index
from sevn.onboarding.capabilities_manifest import load_manifest, skill_capability_id

_SKILL_NAME = st.from_regex(re.compile(r"[a-z][a-z0-9-]{0,30}"), fullmatch=True)


@given(name=_SKILL_NAME)
def test_skill_capability_id_is_stable_snake(name: str) -> None:
    first = skill_capability_id(name)
    second = skill_capability_id(name)
    assert first == second
    assert first.startswith("skill.")
    assert "-" not in first.split(".", 1)[1]


def test_manifest_covers_every_index_skill() -> None:
    index = read_skills_index()
    manifest = load_manifest()
    manifest_skill_ids = {
        cap.capability_id for cap in manifest.capabilities if cap.capability_id.startswith("skill.")
    }
    missing = [
        skill_capability_id(name)
        for name in index
        if skill_capability_id(name) not in manifest_skill_ids
    ]
    assert missing == [], f"missing manifest rows: {missing}"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("computer-use", "skill.computer_use"),
        ("cua-agent", "skill.cua_agent"),
        ("job-ops", "skill.job_ops"),
        ("graphify", "skill.graphify"),
    ],
)
def test_skill_capability_id_examples(name: str, expected: str) -> None:
    assert skill_capability_id(name) == expected
