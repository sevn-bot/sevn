"""Tests for shell history scrub helpers."""

from __future__ import annotations

from pathlib import Path

from sevn.cli.shell_history import (
    ADD_GITHUB_TOKEN_HISTORY_MARKER,
    STORE_PASSPHRASE_HISTORY_MARKER,
    _history_command_text,
    scrub_shell_history,
)


def test_history_command_text_zsh_extended() -> None:
    assert (
        _history_command_text(": 1718123456:0;sevn gh add-github-token --value ghp_x")
        == "sevn gh add-github-token --value ghp_x"
    )


def test_scrub_shell_history_removes_matching_lines(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / ".zsh_history"
    hist.write_text(
        ": 1:0;ls\n: 2:0;sevn gh add-github-token --value ghp_leak\n: 3:0;echo ok\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sevn.cli.shell_history.resolve_shell_history_path", lambda: hist)
    removed = scrub_shell_history(
        containing=ADD_GITHUB_TOKEN_HISTORY_MARKER,
        extra_substrings=("ghp_leak",),
    )
    assert removed == 1
    text = hist.read_text(encoding="utf-8")
    assert ADD_GITHUB_TOKEN_HISTORY_MARKER not in text
    assert "ls" in text
    assert "echo ok" in text


def test_scrub_shell_history_store_passphrase_marker(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / ".zsh_history"
    hist.write_text(
        ": 1:0;sevn secrets store-passphrase --stdin\n"
        ": 2:0;sevn secrets store-passphrase --passphrase secret\n"
        ": 3:0;echo ok\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sevn.cli.shell_history.resolve_shell_history_path", lambda: hist)
    removed = scrub_shell_history(
        containing=STORE_PASSPHRASE_HISTORY_MARKER,
        extra_substrings=("secret",),
    )
    assert removed == 2
    text = hist.read_text(encoding="utf-8")
    assert STORE_PASSPHRASE_HISTORY_MARKER not in text
    assert "echo ok" in text
