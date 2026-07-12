"""Tests for CLI terminal formatting helpers."""

from __future__ import annotations

from sevn.cli.terminal_util import terminal_hyperlink


def test_terminal_hyperlink_includes_label() -> None:
    assert "Example" in terminal_hyperlink("https://example.com", "Example")
