"""W8.7 — routing profile config key disambiguation (D14 → W12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_EXISTING_PROFILE_DOT_PATHS = frozenset(
    {
        "onboarding.applied_profile",
        "permissions.profiles",
        "deployment.profile",
        "skills.browser.profile_dir",
    },
)


@pytest.mark.xfail(reason="green after W12: routing profile config namespace", strict=False)
def test_routing_profile_dot_paths_do_not_collide_with_existing_profile_keys() -> None:
    from sevn.config.sections.routing import routing_profile_config_paths

    paths = routing_profile_config_paths()
    assert paths.profiles_dot_path not in _EXISTING_PROFILE_DOT_PATHS
    assert paths.channel_map_dot_path not in _EXISTING_PROFILE_DOT_PATHS
    assert paths.profiles_dot_path.startswith("routing.")
    assert paths.channel_map_dot_path.startswith("routing.")
    assert paths.profiles_dot_path != "permissions.profiles"


@pytest.mark.xfail(
    reason="green after W12: schema exposes routing.profiles distinctly", strict=False
)
def test_schema_routing_profiles_is_separate_from_permissions_profiles() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    schema = json.loads((repo_root / "infra" / "sevn.schema.json").read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    assert "routing" in props
    routing_props = props["routing"].get("properties", {})
    assert "profiles" in routing_props
    permissions_props = props.get("permissions", {}).get("properties", {})
    assert "profiles" in permissions_props
    assert routing_props["profiles"] is not permissions_props["profiles"]


@pytest.mark.xfail(reason="green after W12: routing module documents disambiguation", strict=False)
def test_routing_profile_disambiguation_doc_lists_four_existing_concepts() -> None:
    from sevn.config.sections.routing import routing_profile_disambiguation_notes

    notes = routing_profile_disambiguation_notes()
    for path in _EXISTING_PROFILE_DOT_PATHS:
        assert path in notes
