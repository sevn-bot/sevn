"""Tests for ``_resolve_skill_descriptions`` (`PROBLEMS.md` §Priority 1, V1)."""

from __future__ import annotations

from sevn.agent.executors.b_harness import _resolve_skill_descriptions


def test_empty_allowlist_returns_full_registry() -> None:
    """No triager narrowing → executor sees the full registry (existing behaviour)."""
    out = _resolve_skill_descriptions(allowed=[], registry={"a": "x", "b": "y"})
    assert out == {"a": "x", "b": "y"}


def test_allowlist_misses_index_falls_back_to_registry() -> None:
    """Allowlist with names not in the shipped INDEX → keep full registry.

    Defensive: the index might be stale relative to the registry. We'd rather
    show too many descriptions than break the agent's ability to call skills.
    """
    out = _resolve_skill_descriptions(
        allowed=["nonexistent-skill"],
        registry={"a": "x"},
    )
    assert out == {"a": "x"}


def test_allowlist_intersects_index_narrows_view() -> None:
    """Allowlist that resolves to an index entry that is also registered narrows."""
    # graphify is in skills/INDEX.md and is registered as a real skill.
    out = _resolve_skill_descriptions(
        allowed=["graphify"],
        registry={"graphify": "registry-desc", "mycode": "other-desc"},
    )
    assert list(out) == ["graphify"]
    # Description comes from the INDEX (workspace-authoritative), not the registry.
    assert out["graphify"] != "registry-desc"


def test_allowlist_with_subset_of_index_only_returns_intersection() -> None:
    """If allowlist names exist in index but not in tool_set, drop them (intersect)."""
    out = _resolve_skill_descriptions(
        allowed=["graphify", "mycode"],
        registry={"graphify": "x"},  # mycode not registered this turn
    )
    assert set(out) == {"graphify"}


def test_index_only_descriptions_when_intersection_nonempty() -> None:
    """When the intersection is non-empty the result is the index descriptions only."""
    out = _resolve_skill_descriptions(
        allowed=["graphify"],
        registry={"graphify": "stale-registry-desc", "extra": "ignored"},
    )
    assert "extra" not in out
    assert out["graphify"]
