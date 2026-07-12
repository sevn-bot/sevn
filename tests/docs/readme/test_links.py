"""Tests for README relative link validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sevn.docs.readme.links import validate_markdown_links


def test_relative_link_resolves() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        (repo / "README.md").write_text("# Root\n", encoding="utf-8")
        errors = validate_markdown_links("[root](../../README.md)", readme, repo)
        assert not errors


def test_broken_link_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        errors = validate_markdown_links("[missing](../missing.md)", readme, repo)
        assert errors


def test_external_links_skipped() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        readme = repo / "docs/readmes/demo.md"
        readme.parent.mkdir(parents=True)
        readme.write_text("# Demo\n", encoding="utf-8")
        errors = validate_markdown_links("[ext](https://example.com)", readme, repo)
        assert not errors
