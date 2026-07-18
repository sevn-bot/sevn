"""Capability manifest loader and API (`plan/onboarding-comprehensive-setup` W1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sevn.data.skills_index import read_skills_index
from sevn.onboarding.capabilities_manifest import (
    load_manifest,
    merged_capability_defaults,
    resolve_install_plan,
    skill_capability_id,
)
from sevn.onboarding.profiles import load_profile_fragment
from sevn.onboarding.web_app import create_onboarding_app


def test_every_index_skill_appears_exactly_once_in_manifest() -> None:
    """W1.6 — INDEX skill ids map 1:1 to ``skill.*`` manifest rows."""
    manifest = load_manifest()
    index = read_skills_index()
    skill_rows = [c for c in manifest.capabilities if c.capability_id.startswith("skill.")]
    by_id = {c.capability_id for c in skill_rows}
    expected = {skill_capability_id(name) for name in index}
    assert by_id == expected
    assert len(skill_rows) == len(index)


def test_resolve_install_plan_orders_dependencies() -> None:
    """``extra.browser`` actions precede dependents when both selected."""
    plan = resolve_install_plan(
        ["code_understanding.graphify", "extra.graphify"],
        {},
    )
    kinds = [a.kind for a in plan]
    assert "uv_extra" in kinds


def test_merged_capability_defaults_profile_override() -> None:
    """Profile ``capabilities_defaults`` overrides manifest defaults when allowed."""
    frag = load_profile_fragment("good_value_osx")
    defaults = merged_capability_defaults(profile_fragment=frag)
    assert defaults["extra.browser_cdp"] is True
    assert "extra.browser" not in defaults
    assert defaults["skill.printing_press_library"] is False


def test_api_capabilities_returns_grouped_manifest() -> None:
    """``GET /api/capabilities`` exposes grouped rows and merged defaults."""
    client = TestClient(create_onboarding_app("test-token"))
    res = client.get("/api/capabilities", headers={"X-Onboard-Token": "test-token"})
    assert res.status_code == 200
    body = res.json()
    assert body["schema_version"] == 1
    group_ids = {g["id"] for g in body["groups"]}
    assert group_ids == {"A", "B", "C", "D", "E", "F", "G"}
    skill_caps = [
        c
        for g in body["groups"]
        for c in g["capabilities"]
        if str(c["capability_id"]).startswith("skill.")
    ]
    assert len(skill_caps) == len(read_skills_index())
    queue = next(
        c
        for g in body["groups"]
        for c in g["capabilities"]
        if c["capability_id"] == "gateway.queue_mode"
    )
    assert queue["control"] == "select"
    assert queue["merged_default"] == "cancel"


def test_api_capabilities_profile_query_merges_defaults() -> None:
    """Optional ``profile_id`` is echoed when the fragment exists."""
    client = TestClient(create_onboarding_app("test-token"))
    res = client.get(
        "/api/capabilities?profile_id=good_value_osx",
        headers={"X-Onboard-Token": "test-token"},
    )
    assert res.status_code == 200
    assert res.json()["profile_id"] == "good_value_osx"
