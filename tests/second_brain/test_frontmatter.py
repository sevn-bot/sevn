"""Tests for Second Brain frontmatter helpers."""

from __future__ import annotations

from sevn.second_brain.frontmatter import (
    compose_page,
    missing_okf_type,
    normalise_agent_keys,
    okf_type_required,
    split_frontmatter,
)


def test_unknown_frontmatter_keys_round_trip() -> None:
    text = "---\nfoo: 1\nsevn_source: x\n---\nbody\n"
    fm, body, _raw = split_frontmatter(text)
    assert fm.get("foo") == 1
    assert body.strip() == "body"
    out = compose_page(fm, body)
    fm2, body2, _ = split_frontmatter(out)
    assert fm2.get("foo") == 1
    assert body2.strip() == "body"


def test_normalise_aliases() -> None:
    fm = normalise_agent_keys({"source": "s", "evidence": ["a"]})
    assert fm.get("sevn_source") == "s"
    assert fm.get("sevn_evidence") == ["a"]


def test_okf_type_required_and_missing() -> None:
    assert okf_type_required("ingests/note.md") is True
    assert okf_type_required("nested/index.md") is False
    assert missing_okf_type({}) is True
    assert missing_okf_type({"type": "Note"}) is False
    assert missing_okf_type({"type": "  "}) is True
