"""Test frontmatter loading, splitting, and round-tripping."""

import pytest

from sevn.docs.about.loader import dump_doc, load_doc, split_frontmatter
from sevn.docs.about.model import AboutDoc


def minimal_spec_doc():
    """Return a minimal valid AboutDoc for testing."""
    return AboutDoc(
        id="spec-17-gateway",
        kind="spec",
        title="Gateway",
        status="done",
        owner="Alex",
        summary="Per-session turn spine.",
        last_updated="2026-06-19",
        parent_prd="prd-01-conversational-experience",
        sources=["src/sevn/gateway/**"],
    )


def test_split_frontmatter_parses():
    text = "---\nid: spec-17-gateway\nkind: spec\n---\n\n## Body\n\nHere is content."
    fm, body = split_frontmatter(text)
    assert isinstance(fm, dict)
    assert "id" in fm
    assert body.strip().startswith("## Body")


def test_split_frontmatter_missing_raises():
    text = "No frontmatter here\n## Just body"
    with pytest.raises(ValueError, match="frontmatter"):
        split_frontmatter(text)


def test_roundtrip(tmp_path):
    doc = minimal_spec_doc()
    body_text = "## Purpose\n\nThis is the gateway.\n"

    # Dump to string
    text = dump_doc(doc, body_text)

    # Write to tmp file
    tmp_file = tmp_path / "test_doc.md"
    tmp_file.write_text(text)

    # Load back
    loaded_doc, loaded_body = load_doc(tmp_file)

    # Verify equality
    assert loaded_doc == doc
    assert loaded_body.strip() == body_text.strip()
