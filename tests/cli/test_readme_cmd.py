"""Tests for ``sevn readme`` CLI commands."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from typer.main import get_command

from sevn.cli.app import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_readme_help_lists_subcommands(runner: CliRunner) -> None:
    result = runner.invoke(get_command(app), ["readme", "--help"])
    assert result.exit_code == 0
    assert "generate" in result.stdout
    assert "update" in result.stdout
    assert "check" in result.stdout
    assert "scaffold" in result.stdout
    assert "index" in result.stdout


def _seed_sevn_repo(repo: Path) -> None:
    """Create minimal git + pyproject markers for ``resolve_sevn_repo_root``."""
    (repo / "pyproject.toml").write_text('name = "sevn"\n', encoding="utf-8")
    (repo / ".git").mkdir()


def test_readme_generate_slug_writes_file(runner: CliRunner) -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_sevn_repo(repo)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        (repo / "src/sevn/demo").mkdir(parents=True)
        (repo / "src/sevn/demo/a.py").write_text("x = 1\n", encoding="utf-8")
        manifest_dir.joinpath("manifest.toml").write_text(
            """
version = 1
[[readme]]
slug = "demo"
title = "Demo"
summary = "Demo summary."
profile = "freeform"
tier_owner = "docs"
output = "docs/readmes/demo.md"
source_globs = ["src/sevn/demo/**"]
""",
            encoding="utf-8",
        )
        result = runner.invoke(
            get_command(app),
            ["readme", "generate", "--slug", "demo", "--offline", "--repo", str(repo)],
        )
        assert result.exit_code == 0
        assert (repo / "docs/readmes/demo.md").is_file()


def test_readme_check_fails_then_passes_after_update(runner: CliRunner) -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_sevn_repo(repo)
        manifest_dir = repo / "docs/readmes"
        manifest_dir.mkdir(parents=True)
        (repo / "src/sevn/demo").mkdir(parents=True)
        py_file = repo / "src/sevn/demo/a.py"
        py_file.write_text("x = 1\n", encoding="utf-8")
        manifest_dir.joinpath("manifest.toml").write_text(
            """
version = 1
[[readme]]
slug = "demo"
title = "Demo"
summary = "Demo summary."
profile = "freeform"
tier_owner = "docs"
output = "docs/readmes/demo.md"
source_globs = ["src/sevn/demo/**"]
""",
            encoding="utf-8",
        )
        gen = runner.invoke(
            get_command(app),
            ["readme", "generate", "--slug", "demo", "--offline", "--repo", str(repo)],
        )
        assert gen.exit_code == 0
        py_file.write_text("x = 2\n", encoding="utf-8")
        fail = runner.invoke(get_command(app), ["readme", "check", "--repo", str(repo)])
        assert fail.exit_code == 1
        fix = runner.invoke(
            get_command(app),
            ["readme", "update", "demo", "--offline", "--repo", str(repo)],
        )
        assert fix.exit_code == 0
        ok = runner.invoke(get_command(app), ["readme", "check", "--repo", str(repo)])
        assert ok.exit_code == 0
