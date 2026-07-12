"""Tests for mtime-keyed BOOTSTRAP.md read cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.gateway.first_session import (
    clear_bootstrap_markdown_cache,
    load_bootstrap_markdown,
    load_bootstrap_markdown_cached,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_bootstrap_markdown_cache()


def test_bootstrap_cache_reuses_body_without_touch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = {"n": 0}
    real_load = load_bootstrap_markdown

    def _counting_load(content_root: Path) -> str | None:
        reads["n"] += 1
        return real_load(content_root)

    monkeypatch.setattr(
        "sevn.gateway.first_session.load_bootstrap_markdown",
        _counting_load,
    )
    (tmp_path / "BOOTSTRAP.md").write_text("first body", encoding="utf-8")
    assert load_bootstrap_markdown_cached(tmp_path) == "first body"
    assert load_bootstrap_markdown_cached(tmp_path) == "first body"
    assert reads["n"] == 1


def test_bootstrap_cache_refreshes_after_mtime_change(tmp_path: Path) -> None:
    path = tmp_path / "BOOTSTRAP.md"
    path.write_text("version one", encoding="utf-8")
    assert load_bootstrap_markdown_cached(tmp_path) == "version one"
    path.write_text("version two", encoding="utf-8")
    assert load_bootstrap_markdown_cached(tmp_path) == "version two"


def test_bootstrap_cache_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_bootstrap_markdown_cached(tmp_path) is None
