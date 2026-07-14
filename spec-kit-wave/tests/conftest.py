"""Fixtures for spec-kit-wave RED tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Minimal repo tree with one Python module for interface resolution."""
    root = tmp_path / "repo"
    root.mkdir()
    module_dir = root / "src" / "sevn" / "gateway"
    module_dir.mkdir(parents=True)
    (module_dir / "agent_turn.py").write_text(
        "def run_turn() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (root / "Makefile").write_text("ci:\n\ttrue\n", encoding="utf-8")
    return root
