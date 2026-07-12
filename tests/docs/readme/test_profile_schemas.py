"""Tests for §C0 profile schema registry."""

from __future__ import annotations

import pytest

from sevn.docs.readme.profile_schemas import PROFILE_SCHEMAS, get_profile_schema


def test_all_profiles_registered() -> None:
    assert set(PROFILE_SCHEMAS) == {
        "root",
        "subsystem",
        "index",
        "catalog",
        "guide",
        "freeform",
    }


def test_subsystem_requires_tiers_and_symbols() -> None:
    schema = get_profile_schema("subsystem")
    assert schema.needs_tiers
    assert schema.verify_symbol_refs
    assert "Level 3 — Deep dive" in schema.required_headings


def test_root_skips_summary() -> None:
    assert not get_profile_schema("root").requires_summary


def test_unknown_profile_raises() -> None:
    with pytest.raises(KeyError, match="unknown README profile"):
        get_profile_schema("nope")
