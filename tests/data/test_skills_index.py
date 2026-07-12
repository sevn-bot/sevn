"""Tests for ``sevn.data.skills_index`` (`PROBLEMS.md` §Priority 1.a)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.data.skills_index import (
    _PACKAGED_STARTER_INDEX,
    REPO_STARTER_INDEX,
    SkillsStarterMissingError,
    _resolve_repo_starter_index,
    ensure_workspace_index,
    read_skills_index,
)


def test_read_skills_index_starter_full() -> None:
    """The shipped starter is parseable and non-empty."""
    idx = read_skills_index()
    assert isinstance(idx, dict)
    assert len(idx) > 0
    assert "graphify" in idx
    assert idx["graphify"]


def test_read_skills_index_subset() -> None:
    """Requesting specific names returns only those entries."""
    all_idx = read_skills_index()
    subset = read_skills_index(names=["graphify", "mycode"])
    assert set(subset) == {"graphify", "mycode"}
    assert subset["graphify"] == all_idx["graphify"]


def test_read_skills_index_unknown_names_silently_omitted() -> None:
    """Unknown names are not in the result; no exception."""
    out = read_skills_index(names=["does-not-exist", "graphify"])
    assert "does-not-exist" not in out
    assert "graphify" in out


def test_read_skills_index_workspace_authoritative(tmp_path: Path) -> None:
    """When the workspace has its own INDEX, the function reads it (not the starter)."""
    ws = tmp_path / "ws"
    ws_index = ws / "skills" / "INDEX.md"
    ws_index.parent.mkdir(parents=True)
    ws_index.write_text(
        "| name | description |\n|---|---|\n| only-workspace | hello |\n",
        encoding="utf-8",
    )
    out = read_skills_index(workspace_root=ws)
    assert out == {"only-workspace": "hello"}


def test_read_skills_index_falls_back_to_starter_when_workspace_missing(
    tmp_path: Path,
) -> None:
    """No workspace INDEX → starter is used."""
    ws = tmp_path / "ws"
    out = read_skills_index(workspace_root=ws)
    starter = read_skills_index()
    assert out == starter


def test_ensure_workspace_index_creates_then_idempotent(tmp_path: Path) -> None:
    """First call copies starter; second call leaves the file alone."""
    ws = tmp_path / "ws"
    target = ensure_workspace_index(ws)
    assert target == ws / "skills" / "INDEX.md"
    assert target.is_file()
    first_content = target.read_text(encoding="utf-8")
    # Edit it; second ensure must not overwrite.
    target.write_text(first_content + "| edited | row |\n", encoding="utf-8")
    again = ensure_workspace_index(ws)
    assert again.read_text(encoding="utf-8").endswith("| edited | row |\n")


def test_parse_table_ignores_extra_columns(tmp_path: Path) -> None:
    """tier/when_to_use columns past 'description' are ignored by the parser."""
    ws = tmp_path / "ws"
    ws_index = ws / "skills" / "INDEX.md"
    ws_index.parent.mkdir(parents=True)
    ws_index.write_text(
        "| name | description | tier | when_to_use |\n"
        "|---|---|---|---|\n"
        "| foo | bar | B | code questions |\n",
        encoding="utf-8",
    )
    out = read_skills_index(workspace_root=ws)
    assert out == {"foo": "bar"}


def test_repo_starter_index_path_anchored_to_starter() -> None:
    """The constant must point at the packaged starter."""
    assert REPO_STARTER_INDEX.name == "INDEX.md"
    assert REPO_STARTER_INDEX.parent.name == "skills"
    assert REPO_STARTER_INDEX.is_file()
    assert REPO_STARTER_INDEX == _PACKAGED_STARTER_INDEX


def test_resolve_repo_starter_index_returns_packaged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starter resolution uses the packaged ``sevn/data/skills/INDEX.md`` path."""
    packaged = tmp_path / "packaged" / "skills" / "INDEX.md"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(
        "| name | description |\n|---|---|\n| packaged-only | yes |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sevn.data.skills_index._PACKAGED_STARTER_INDEX",
        packaged,
    )
    assert _resolve_repo_starter_index() == packaged


def test_parse_table_escaped_pipe(tmp_path: Path) -> None:
    """``\\|`` in a description survives the round-trip as ``|``."""
    ws = tmp_path / "ws"
    ws_index = ws / "skills" / "INDEX.md"
    ws_index.parent.mkdir(parents=True)
    ws_index.write_text(
        "| name | description |\n|---|---|\n| foo | a \\| b |\n",
        encoding="utf-8",
    )
    out = read_skills_index(workspace_root=ws)
    assert out == {"foo": "a | b"}


def test_ensure_workspace_index_raises_when_starter_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing packaged starter surfaces a typed error instead of silent skip."""
    missing_packaged = tmp_path / "packaged" / "skills" / "INDEX.md"
    monkeypatch.setattr(
        "sevn.data.skills_index._PACKAGED_STARTER_INDEX",
        missing_packaged,
    )
    ws = tmp_path / "ws"
    with pytest.raises(SkillsStarterMissingError) as exc_info:
        ensure_workspace_index(ws)
    assert exc_info.value.resolved_path == missing_packaged


@pytest.mark.parametrize(
    "row",
    [
        "",
        "no table here",
        "| not-enough |",
        "|---|---|",  # separator row alone
    ],
)
def test_parse_table_robust_to_garbage(tmp_path: Path, row: str) -> None:
    """Non-table content is silently ignored."""
    ws = tmp_path / "ws"
    ws_index = ws / "skills" / "INDEX.md"
    ws_index.parent.mkdir(parents=True)
    ws_index.write_text(row + "\n", encoding="utf-8")
    out = read_skills_index(workspace_root=ws)
    assert out == {}
