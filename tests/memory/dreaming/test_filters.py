"""Unit tests for Dreaming filters (`specs/31-memory-dreaming.md` §8)."""

from __future__ import annotations

from sevn.memory.dreaming.filters import (
    content_has_llmignore_provenance,
    lcm_channel_allows_dreaming,
    session_allows_dreaming,
)


def test_dm_session_allowed() -> None:
    assert session_allows_dreaming("dm:u1", None) is True


def test_group_session_rejected() -> None:
    assert session_allows_dreaming("grp:room1", None) is False


def test_metadata_scope_group() -> None:
    assert session_allows_dreaming("x", '{"scope": "group"}') is False


def test_llmignore_path_detected() -> None:
    assert content_has_llmignore_provenance("safe", None) is False
    assert content_has_llmignore_provenance("see .llmignore/x", None) is True


def test_lcm_channel_supergroup_rejected() -> None:
    assert lcm_channel_allows_dreaming("supergroup") is False
    assert lcm_channel_allows_dreaming("private") is True
