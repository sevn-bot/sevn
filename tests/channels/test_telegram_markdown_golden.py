"""Golden regression for Markdown escape used before Telegram send (`specs/18` §10.4)."""

from __future__ import annotations

from pathlib import Path

import sevn.channels.telegram as telegram_mod

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "channels" / "telegram"


def test_markdown_escape_matches_golden_files() -> None:
    raw_in = (_FIXTURES / "markdown_escape_in.txt").read_text(encoding="utf-8")
    expected = (_FIXTURES / "markdown_escape_out.txt").read_text(encoding="utf-8")
    assert telegram_mod._markdown_escape(raw_in.rstrip("\n")) == expected.rstrip("\n")
