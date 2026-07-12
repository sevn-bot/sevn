"""``sevn sync`` Typer entry (`specs/23-cli.md` §2.4.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.repo_sync import SyncResult


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_sync_dry_run_exits_zero(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sevn.bot"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")
    monkeypatch.setattr(
        "sevn.cli.commands.sync_cmd.sync_source_tree",
        lambda **kwargs: SyncResult(
            updated=False,
            local_rev="dry-run",
            remote_rev="dry-run",
            detail="dry-run: git fetch origin test-pre; update checkout; make sync-cli (install-cli-browser); refresh skills/core",
        ),
    )
    result = runner.invoke(
        get_command(app),
        ["sync", "--repo", str(root), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "dry-run" in result.stdout
