"""Tests for allowlisted ``roam`` subprocess helpers."""

from __future__ import annotations

import pytest

from sevn.code_understanding.roam_runner import build_roam_argv


def test_build_roam_argv_understand() -> None:
    assert build_roam_argv("understand") == ["roam", "understand"]


def test_build_roam_argv_retrieve() -> None:
    assert build_roam_argv("retrieve", query="where is auth?") == [
        "roam",
        "retrieve",
        "where is auth?",
    ]


def test_build_roam_argv_retrieve_requires_query() -> None:
    with pytest.raises(ValueError, match="roam_code:"):
        build_roam_argv("retrieve", query="")
