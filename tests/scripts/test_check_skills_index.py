"""Tests for ``scripts/check_skills_index.py`` drift detection."""

from __future__ import annotations

from pathlib import Path

import scripts.check_skills_index as checker


def test_main_fails_when_shipped_skill_missing_from_index(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """A bundled core skill without an INDEX row must exit non-zero."""
    core = tmp_path / "core" / "newskill"
    core.mkdir(parents=True)
    (core / "SKILL.md").write_text(
        "---\nname: newskill\n---\n# newskill\n",
        encoding="utf-8",
    )
    index = tmp_path / "src" / "sevn" / "data" / "skills" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text(
        "| name | description |\n|---|---|\n| existing | ok |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "CORE_ROOT", core.parent)
    monkeypatch.setattr(checker, "INDEX_PATH", index)

    assert checker.main() == 1


def test_main_passes_when_index_matches_shipped(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """INDEX rows covering every bundled skill must exit zero."""
    core = tmp_path / "core" / "alpha"
    core.mkdir(parents=True)
    (core / "SKILL.md").write_text(
        "---\nname: alpha\n---\n# alpha\n",
        encoding="utf-8",
    )
    index = tmp_path / "src" / "sevn" / "data" / "skills" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text(
        "| name | description |\n|---|---|\n| alpha | does alpha |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "CORE_ROOT", core.parent)
    monkeypatch.setattr(checker, "INDEX_PATH", index)

    assert checker.main() == 0
