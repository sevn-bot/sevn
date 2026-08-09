"""Tests for the changelog validator shim."""

from __future__ import annotations

from scripts import changelog_validate as cv


def test_shim_degrades_without_spec_kit_wave() -> None:
    assert cv.SKW_AVAILABLE is False
    assert cv.main([]) == 0
