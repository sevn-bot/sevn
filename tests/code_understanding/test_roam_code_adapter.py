"""Tests for the roam-code adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sevn.code_understanding.roam_code_adapter import RoamCodeAdapter


def test_roam_code_adapter_returns_prefixed_text() -> None:
    with patch(
        "sevn.code_understanding.roam_code_adapter.run_roam_query",
        return_value=(True, "roam_code: answer text"),
    ):
        adapter = RoamCodeAdapter(Path("/some/root"))
        text = adapter.query("any?")
    assert text == "roam_code: answer text"


def test_roam_code_adapter_accepts_none_query() -> None:
    with patch(
        "sevn.code_understanding.roam_code_adapter.run_roam_query",
        return_value=(True, "roam_code: briefing"),
    ):
        adapter = RoamCodeAdapter(Path("/r"))
        text = adapter.query(None)
    assert text == "roam_code: briefing"


def test_roam_code_adapter_stores_root() -> None:
    adapter = RoamCodeAdapter(Path("/repo/root"))
    assert adapter.root == Path("/repo/root")
