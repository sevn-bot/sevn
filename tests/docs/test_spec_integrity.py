"""Spec corpus integrity contracts (D17; green after W9)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "about-sevn.bot/specs"
SPECS_INDEX = REPO_ROOT / "about-sevn.bot/specs-index.md"
GLOSSARY = REPO_ROOT / "about-sevn.bot/GLOSSARY.md"

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_STATUS = re.compile(r"^status:\s*(\S+)", re.MULTILINE)
_SOURCES = re.compile(r"^sources:\s*\n((?:- .+\n)+)", re.MULTILINE)
_SPEC_NUMERIC_ID = re.compile(r"^(\d+)-", re.MULTILINE)


def _split_frontmatter(text: str) -> tuple[str, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def _sources_list(frontmatter: str) -> list[str]:
    match = _SOURCES.search(frontmatter)
    if not match:
        return []
    return [
        line.split("-", maxsplit=1)[1].strip()
        for line in match.group(1).splitlines()
        if line.strip().startswith("-")
    ]


@pytest.mark.xfail(reason="green after W9: D17 specs-index exists", strict=False)
def test_specs_index_exists() -> None:
    """D17: ``about-sevn.bot/specs-index.md`` exists for architecture links."""
    assert SPECS_INDEX.is_file()


@pytest.mark.xfail(reason="green after W9: D17 hollow done scaffolds relabeled", strict=False)
def test_no_done_status_with_offline_scaffold_body() -> None:
    """D17: no spec combines ``status: done`` with an Offline scaffold body."""
    offenders: list[str] = []
    for path in sorted(SPECS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(text)
        status_match = _STATUS.search(frontmatter)
        status = status_match.group(1) if status_match else ""
        if status == "done" and "Offline scaffold" in body:
            offenders.append(path.name)
    assert offenders == []


@pytest.mark.xfail(reason="green after W9: D17 glossary terms seeded", strict=False)
def test_glossary_has_at_least_one_term_row() -> None:
    """D17: ``GLOSSARY.md`` ``## Terms`` contains at least one table/data row."""
    text = GLOSSARY.read_text(encoding="utf-8")
    terms_section = text.split("## Terms", maxsplit=1)[-1]
    rows = [
        line
        for line in terms_section.splitlines()
        if line.strip().startswith("|") and "---" not in line and "Term" not in line
    ]
    assert len(rows) >= 1


@pytest.mark.xfail(reason="green after W9: D17 duplicate numeric spec id resolved", strict=False)
def test_no_duplicate_numeric_spec_id_prefix() -> None:
    """D17: spec filenames do not reuse the same numeric id prefix."""
    ids: dict[str, list[str]] = {}
    for path in SPECS_DIR.glob("*.md"):
        match = _SPEC_NUMERIC_ID.match(path.name)
        if not match:
            continue
        numeric = match.group(1)
        ids.setdefault(numeric, []).append(path.name)
    duplicates = {key: names for key, names in ids.items() if len(names) > 1}
    assert duplicates == {}


@pytest.mark.parametrize(
    ("filename", "expected_source"),
    [
        ("16-harness-discipline.md", "agent/harness"),
        ("06-secrets.md", "security/secrets"),
        ("04-tracing.md", "agent/tracing"),
    ],
)
@pytest.mark.xfail(reason="green after W9: D17 spec sources frontmatter", strict=False)
def test_spec_sources_frontmatter_points_at_real_trees(
    filename: str,
    expected_source: str,
) -> None:
    """D17: corrected ``sources`` frontmatter cites the implementing tree."""
    path = SPECS_DIR / filename
    frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    sources = _sources_list(frontmatter)
    assert sources
    assert any(expected_source in item for item in sources)
