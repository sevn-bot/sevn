"""Tests for packaged Conventional Commits standard loader."""

from __future__ import annotations

from sevn.standards.conventional_commits import (
    conventional_commits_markdown,
    conventional_commits_prompt_block,
)


def test_conventional_commits_markdown_loads() -> None:
    body = conventional_commits_markdown()
    assert "Conventional Commits" in body
    assert "feat" in body


def test_conventional_commits_prompt_block() -> None:
    block = conventional_commits_prompt_block()
    assert block.startswith("## Git commits")
    assert "feat" in block
