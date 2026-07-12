"""``sevn sync`` Graphify build step (best-effort, non-fatal)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sevn.cli.repo_sync import _maybe_build_graphify


def test_dry_run_reports_intent(tmp_path: Path) -> None:
    assert (
        _maybe_build_graphify(tmp_path, dry_run=True)
        == "dry-run: graphify update (build .index/graphify)"
    )


def test_skips_when_cli_missing(tmp_path: Path) -> None:
    with patch("sevn.cli.repo_sync.shutil.which", return_value=None):
        assert _maybe_build_graphify(tmp_path) is None


def test_builds_when_cli_present(tmp_path: Path) -> None:
    with (
        patch("sevn.cli.repo_sync.shutil.which", return_value="/usr/bin/graphify"),
        patch(
            "sevn.code_understanding.graphify_seed.build_graphify_index",
            return_value=True,
        ) as build,
    ):
        assert _maybe_build_graphify(tmp_path) == "built .index/graphify"
    build.assert_called_once_with(tmp_path)


def test_build_failure_returns_none(tmp_path: Path) -> None:
    with (
        patch("sevn.cli.repo_sync.shutil.which", return_value="/usr/bin/graphify"),
        patch(
            "sevn.code_understanding.graphify_seed.build_graphify_index",
            return_value=False,
        ),
    ):
        assert _maybe_build_graphify(tmp_path) is None
