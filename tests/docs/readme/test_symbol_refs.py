"""Tests for Level 3 path and symbol reference checks."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sevn.docs.readme.symbol_refs import (
    _symbol_defined_in_file,
    extract_level3_section,
    validate_path_refs,
    validate_symbol_refs,
)


def test_extract_level3_section() -> None:
    text = "## Level 1 — Overview\n\n## Level 3 — Deep dive\n\nBody\n\n## References\n"
    assert "Body" in extract_level3_section(text)


def test_validate_path_refs_ok() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/demo/a.py"
        py.parent.mkdir(parents=True)
        py.write_text("x = 1\n", encoding="utf-8")
        assert not validate_path_refs("See `src/sevn/demo/a.py`.", repo)


def test_validate_path_refs_missing() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        assert validate_path_refs("See `src/sevn/missing/a.py`.", repo)


def test_validate_symbol_refs_ok() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/demo/a.py"
        py.parent.mkdir(parents=True)
        py.write_text("class Foo:\n    def bar(self): pass\n", encoding="utf-8")
        text = "In `src/sevn/demo/a.py`, entry point `Foo.bar`."
        assert not validate_symbol_refs(text, repo)


def test_symbol_defined_in_file_nested_class_method() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "m.py"
        path.write_text(
            "class Foo:\n    class Bar:\n        def baz(self): pass\n",
            encoding="utf-8",
        )
        assert _symbol_defined_in_file(path, "Foo.Bar.baz")
        assert not _symbol_defined_in_file(path, "Foo.Bar.missing")


def test_validate_symbol_refs_ignores_file_like_backticks() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        py = repo / "src/sevn/channels/markdown_safe.py"
        py.parent.mkdir(parents=True)
        py.write_text('"""Escape (`PROBLEMS.md` §9)."""\n', encoding="utf-8")
        text = "- `src/sevn/channels/markdown_safe.py` — (`PROBLEMS.md` §9)."
        assert not validate_symbol_refs(text, repo)
