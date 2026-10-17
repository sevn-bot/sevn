"""Repo-root lookup for tests. Parents: support → tests → host → repo."""

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
