"""Tests for USER.md bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from sevn.gateway.bootstrap.bootstrap_state import operator_name_from_user_md


def test_operator_name_from_user_md_returns_name(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text("- **Name:** Alex\n", encoding="utf-8")
    assert operator_name_from_user_md(tmp_path) == "Alex"


def test_operator_name_from_user_md_rejects_placeholder(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text(
        "- **Name:** _(your preferred name)_\n",
        encoding="utf-8",
    )
    assert operator_name_from_user_md(tmp_path) is None
