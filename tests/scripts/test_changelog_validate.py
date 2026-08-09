"""Tests for the changelog validator shim."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import changelog_validate as cv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKW_SRC = _REPO_ROOT / "spec-kit-wave" / "src"


def test_shim_availability_tracks_kit_directory() -> None:
    assert cv.SKW_AVAILABLE is _SKW_SRC.is_dir()


@pytest.mark.skipif(_SKW_SRC.is_dir(), reason="spec-kit-wave present")
def test_shim_cli_noop_when_kit_absent() -> None:
    assert cv.main([]) == 0
