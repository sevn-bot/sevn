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


def _seed_curated_repo(repo: Path, *, curated: bool = True) -> None:
    """Create a tmp repo with one curated (or generated) manifest entry."""
    _seed_sevn_repo(repo)
    manifest_dir = repo / "docs/readmes"
    manifest_dir.mkdir(parents=True)
    hand_src = repo / "src/sevn/hand"
    hand_src.mkdir(parents=True)
    (hand_src / "mod.py").write_text("v = 1\n", encoding="utf-8")
    curated_line = "curated = true\n" if curated else ""
    manifest_dir.joinpath("manifest.toml").write_text(
        "version = 1\n"
        "[[readme]]\n"
        'slug = "hand"\n'
        'title = "Hand"\n'
        'summary = "Hand-authored README."\n'
        'profile = "freeform"\n'
        'tier_owner = "docs"\n'
        'output = "docs/readmes/hand.md"\n'
        'source_globs = ["src/sevn/hand/**"]\n'
        f"{curated_line}",
        encoding="utf-8",
    )
    readme_path = manifest_dir / "hand.md"
    readme_path.write_text(
        "<!-- curated: hand-authored body -->\n> **Summary.** Hand body must stay byte-stable.\n",
        encoding="utf-8",
    )


def test_readme_fingerprint_stamps_without_body_change(runner: CliRunner) -> None:
    """D1: ``sevn readme fingerprint <slug>`` updates digest only (body unchanged)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_curated_repo(repo, curated=True)
        readme_path = repo / "docs/readmes/hand.md"
        before_text = readme_path.read_text(encoding="utf-8")
        before_mtime = readme_path.stat().st_mtime_ns
        result = runner.invoke(
            get_command(app),
            ["readme", "fingerprint", "hand", "--repo", str(repo)],
        )
        assert result.exit_code == 0
        assert "stamped hand" in result.stdout
        assert readme_path.read_text(encoding="utf-8") == before_text
        assert readme_path.stat().st_mtime_ns == before_mtime


def test_readme_update_curated_exits_without_force(runner: CliRunner) -> None:
    """D2: ``sevn readme update`` on curated entry exits 2 with hint unless ``--force``."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_curated_repo(repo, curated=True)
        before = (repo / "docs/readmes/hand.md").read_text(encoding="utf-8")
        result = runner.invoke(
            get_command(app),
            ["readme", "update", "hand", "--offline", "--repo", str(repo)],
        )
        assert result.exit_code == 2
        assert "curated" in result.stderr.lower() or "curated" in result.stdout.lower()
        assert (repo / "docs/readmes/hand.md").read_text(encoding="utf-8") == before


def test_readme_update_curated_force_writes(runner: CliRunner) -> None:
    """D2: ``sevn readme update --force`` regenerates a curated README body."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_curated_repo(repo, curated=True)
        result = runner.invoke(
            get_command(app),
            ["readme", "update", "hand", "--force", "--offline", "--repo", str(repo)],
        )
        assert result.exit_code == 0
        body = (repo / "docs/readmes/hand.md").read_text(encoding="utf-8")
        assert "Hand body must stay byte-stable." not in body


def test_readme_generate_all_skips_curated_body_but_stamps(runner: CliRunner) -> None:
    """D2: ``sevn readme generate --all`` stamps curated slugs without rewriting bodies."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_curated_repo(repo, curated=True)
        gen_src = repo / "src/sevn/gen"
        gen_src.mkdir(parents=True)
        (gen_src / "a.py").write_text("x = 1\n", encoding="utf-8")
        manifest_path = repo / "docs/readmes/manifest.toml"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8") + "\n[[readme]]\n"
            'slug = "gen"\n'
            'title = "Gen"\n'
            'summary = "Generated entry."\n'
            'profile = "freeform"\n'
            'tier_owner = "docs"\n'
            'output = "docs/readmes/gen.md"\n'
            'source_globs = ["src/sevn/gen/**"]\n',
            encoding="utf-8",
        )
        hand_before = (repo / "docs/readmes/hand.md").read_text(encoding="utf-8")
        result = runner.invoke(
            get_command(app),
            ["readme", "generate", "--all", "--offline", "--repo", str(repo)],
        )
        assert result.exit_code == 0
        assert "skipped hand (curated)" in result.stdout
        assert (repo / "docs/readmes/hand.md").read_text(encoding="utf-8") == hand_before
        assert (repo / "docs/readmes/gen.md").is_file()


def test_precommit_main_leaves_curated_body_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """D2: ``readme_precommit.main`` stamps curated slugs without ``write_readme`` body churn."""
    from scripts import readme_precommit

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_curated_repo(repo, curated=True)
        before = (repo / "docs/readmes/hand.md").read_text(encoding="utf-8")
        # Force agent-off so the stamp-only path is deterministic regardless of
        # whether a curator runner (cursor-agent/claude) is installed on the host.
        monkeypatch.setenv("SEVN_README_AGENT", "0")
        monkeypatch.setattr(readme_precommit, "_resolve_repo_root", lambda _repo: repo)
        exit_code = readme_precommit.main(["src/sevn/hand/mod.py"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "stamped hand (curated, agent off)" in captured.out
        assert (repo / "docs/readmes/hand.md").read_text(encoding="utf-8") == before


def test_check_stale_hint_text_for_curated_vs_generated(runner: CliRunner) -> None:
    """D3: stale errors suggest ``fingerprint`` for curated and ``update`` for generated."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _seed_curated_repo(repo, curated=True)
        gen_src = repo / "src/sevn/gen"
        gen_src.mkdir(parents=True)
        gen_py = gen_src / "a.py"
        gen_py.write_text("x = 1\n", encoding="utf-8")
        manifest_path = repo / "docs/readmes/manifest.toml"
        manifest_path.write_text(
            manifest_path.read_text(encoding="utf-8") + "\n[[readme]]\n"
            'slug = "gen"\n'
            'title = "Gen"\n'
            'summary = "Generated entry."\n'
            'profile = "freeform"\n'
            'tier_owner = "docs"\n'
            'output = "docs/readmes/gen.md"\n'
            'source_globs = ["src/sevn/gen/**"]\n',
            encoding="utf-8",
        )
        gen_write = runner.invoke(
            get_command(app),
            ["readme", "generate", "--slug", "gen", "--offline", "--repo", str(repo)],
        )
        assert gen_write.exit_code == 0
        (repo / "src/sevn/hand/mod.py").write_text("v = 2\n", encoding="utf-8")
        gen_py.write_text("x = 2\n", encoding="utf-8")
        fail = runner.invoke(get_command(app), ["readme", "check", "--repo", str(repo)])
        assert fail.exit_code == 1
        output = fail.stdout + fail.stderr
        assert "sevn readme fingerprint hand" in output
        assert "sevn readme update gen" in output
