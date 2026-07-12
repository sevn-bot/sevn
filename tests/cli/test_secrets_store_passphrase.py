"""Tests for ``sevn secrets store-passphrase`` stdin / TTY handling."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


@pytest.mark.skipif(sys.platform != "darwin", reason="store-passphrase is macOS-only")
def test_store_passphrase_stdin_pipe(runner: ClickCliRunner) -> None:
    with patch("sevn.cli.asyncio_util.run_sync_coro") as run_sync:
        result = runner.invoke(
            get_command(app),
            ["secrets", "store-passphrase", "--stdin"],
            input="pw-from-pipe\n",
        )
    assert result.exit_code == 0
    run_sync.assert_called_once()
