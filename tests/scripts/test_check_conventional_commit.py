"""Tests for Conventional Commits commit-msg validation."""

from __future__ import annotations

import pytest
from scripts.check_conventional_commit import validate_commit_message


@pytest.mark.parametrize(
    "message",
    [
        "feat: add hook",
        "feat(gateway): add hook",
        "fix!: drop legacy API",
        "revert: undo menu change\n\nRefs: abc1234",
    ],
)
def test_validate_accepts_good_subjects(message: str) -> None:
    assert validate_commit_message(message) == []


@pytest.mark.parametrize(
    "message",
    [
        "",
        "WIP",
        "feat: trailing period.",
        "feat:no space after colon",
        "feet: typo type",
        "feat: " + "x" * 80,
    ],
)
def test_validate_rejects_bad_subjects(message: str) -> None:
    assert validate_commit_message(message) != []


def test_validate_skips_merge_commits() -> None:
    assert validate_commit_message("Merge branch 'main' into feature") == []


def test_validate_ignores_comment_lines() -> None:
    msg = "# template\n\nfeat(docs): update guide\n"
    assert validate_commit_message(msg) == []
