"""Batch A W1.2 — ``sevn --version`` branch-commit format (#123, D8)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app

_BRANCH_COMMIT_RE = re.compile(r"^[^/\s]+(?:/[^/\s]+)*-[0-9a-f]{8}$")


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _init_git_repo(root: Path, *, commit_message: str = "init") -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", commit_message],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_root_version_flag_uses_branch_commit_format(runner: ClickCliRunner) -> None:
    """``sevn --version`` emits ``<branch>-<commit8>`` inside a git checkout."""
    result = runner.invoke(get_command(app), ["--version"])
    assert result.exit_code == 0, result.stdout
    version = result.stdout.strip()
    assert version != "0.0.1", "placeholder package version must not be printed"
    assert _BRANCH_COMMIT_RE.match(version), f"unexpected version format: {version!r}"


def test_version_subcommand_uses_branch_commit_format(runner: ClickCliRunner) -> None:
    """``sevn version`` matches root ``--version`` format."""
    result = runner.invoke(get_command(app), ["version"])
    assert result.exit_code == 0, result.stdout
    version = result.stdout.strip().splitlines()[0]
    assert _BRANCH_COMMIT_RE.match(version), f"unexpected version format: {version!r}"


def test_version_json_includes_branch_commit_cli_version(runner: ClickCliRunner) -> None:
    """``sevn version --json`` exposes branch-commit ``cli_version``."""
    result = runner.invoke(get_command(app), ["version", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    cli_version = str(payload.get("cli_version", ""))
    assert _BRANCH_COMMIT_RE.match(cli_version), f"unexpected cli_version: {cli_version!r}"


def test_resolve_cli_version_string_falls_back_to_package_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed wheel path: git metadata unavailable → ``importlib.metadata`` version."""
    from sevn.cli.version import resolve_cli_version_string

    monkeypatch.setattr(
        "sevn.cli.version._git_branch_commit_version",
        lambda *_a, **_k: None,
    )
    assert resolve_cli_version_string() == "0.0.1"


def test_resolve_cli_version_string_from_git(tmp_path: Path) -> None:
    """Unit: helper prefers git-derived ``<branch>-<commit8>`` when repo root is known."""
    from sevn.cli.version import resolve_cli_version_string

    _init_git_repo(tmp_path)
    version = resolve_cli_version_string(repo_root=tmp_path)
    assert isinstance(version, str)
    assert version
    assert _BRANCH_COMMIT_RE.match(version), f"unexpected git version: {version!r}"


def test_version_json_still_collects_on_baseline(runner: ClickCliRunner) -> None:
    """JSON envelope shape includes ``cli_version`` and ``python_version``."""
    result = runner.invoke(get_command(app), ["version", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "cli_version" in payload
    assert "python_version" in payload


def test_root_version_does_not_invoke_git_when_print_version_false(runner: ClickCliRunner) -> None:
    """Guard: unrelated subcommands must not shell out to git (W3 adds explicit helper)."""
    with patch("subprocess.run") as run:
        result = runner.invoke(get_command(app), ["--help"])
    assert result.exit_code == 0
    git_calls = [c for c in run.call_args_list if "git" in str(c)]
    assert git_calls == []
