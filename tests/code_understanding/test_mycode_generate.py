"""Tests for the MYCODE markdown generator + atomic writer."""

from __future__ import annotations

from pathlib import Path

from sevn.code_understanding.models import MycodeFileEntry, MycodeScanDigest
from sevn.code_understanding.mycode_generate import (
    generate_mycode_markdown,
    write_mycode,
)


def _sample_digest() -> MycodeScanDigest:
    return MycodeScanDigest(
        root="/repo",
        files=[
            MycodeFileEntry(
                path="alpha.py",
                language="python",
                line_count=12,
                symbols=["Alpha", "beta"],
                imports=["os"],
            ),
            MycodeFileEntry(
                path="web/widget.ts",
                language="typescript",
                line_count=4,
                symbols=["Widget"],
            ),
        ],
        ignored=["*.tmp"],
    )


def test_generate_markdown_contains_digest_symbols() -> None:
    md = generate_mycode_markdown(_sample_digest())
    assert md.startswith("# MYCODE")
    assert "alpha.py" in md
    assert "Alpha" in md
    assert "beta" in md
    assert "web/widget.ts" in md
    assert "Widget" in md


def test_generate_markdown_notes_cgr_json_size() -> None:
    md = generate_mycode_markdown(_sample_digest(), cgr_json=b"x" * 7)
    assert "7 bytes" in md


def test_generate_markdown_falls_back_when_transport_raises() -> None:
    class _Boom:
        def complete(self, prompt: str) -> str:
            raise RuntimeError("upstream down")

    md = generate_mycode_markdown(_sample_digest(), transport=_Boom())
    assert md.startswith("# MYCODE")
    assert "alpha.py" in md


def test_generate_markdown_uses_transport_when_provided() -> None:
    class _Echo:
        def complete(self, prompt: str) -> str:
            return "# UPSTREAM\nbody\n"

    md = generate_mycode_markdown(_sample_digest(), transport=_Echo())
    assert md == "# UPSTREAM\nbody\n"


def test_write_mycode_atomic_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "MYCODE.md"
    write_mycode(target, "# MYCODE\nhello\n")

    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "# MYCODE\nhello\n"
    siblings = [p.name for p in target.parent.iterdir()]
    assert "MYCODE.md" in siblings
    assert all(not name.endswith(".tmp") for name in siblings)


def test_write_mycode_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "MYCODE.md"
    write_mycode(target, "old\n")
    write_mycode(target, "new\n")
    assert target.read_text(encoding="utf-8") == "new\n"
