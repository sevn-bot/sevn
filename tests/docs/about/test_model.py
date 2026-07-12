"""Test AboutDoc and Interface models for frontmatter validation."""

import pytest
from pydantic import ValidationError

from sevn.docs.about.model import AboutDoc


def minimal_spec_dict():
    """Return a minimal valid spec doc dict."""
    return {
        "id": "spec-17-gateway",
        "kind": "spec",
        "title": "Gateway",
        "status": "done",
        "owner": "Alex",
        "summary": "Per-session turn spine that routes inbound messages.",
        "last_updated": "2026-06-19",
        "parent_prd": "prd-01-conversational-experience",
        "sources": ["src/sevn/gateway/**"],
    }


def minimal_prd_dict():
    """Return a minimal valid prd doc dict."""
    return {
        "id": "prd-01-conversational-experience",
        "kind": "prd",
        "title": "Conversational Experience",
        "status": "done",
        "owner": "Alex",
        "summary": "End-to-end conversational agent flow.",
        "last_updated": "2026-06-19",
        "parent_prd": None,
    }


def test_valid_spec_doc_validates():
    doc = minimal_spec_dict()
    result = AboutDoc.model_validate(doc)
    assert result.id == "spec-17-gateway"
    assert result.kind == "spec"


def test_valid_prd_doc_validates():
    doc = minimal_prd_dict()
    result = AboutDoc.model_validate(doc)
    assert result.id == "prd-01-conversational-experience"
    assert result.kind == "prd"


def test_missing_id_rejected():
    doc = minimal_spec_dict()
    del doc["id"]
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_bad_id_pattern_rejected():
    doc = minimal_spec_dict()
    doc["id"] = "spec-gateway"  # missing NN
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_summary_over_200_rejected():
    doc = minimal_spec_dict()
    doc["summary"] = "x" * 201  # 201 chars exceeds maxLength
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_bad_status_rejected():
    doc = minimal_spec_dict()
    doc["status"] = "bogus"
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_spec_requires_parent_prd():
    doc = minimal_spec_dict()
    doc["parent_prd"] = None
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_spec_requires_sources():
    doc = minimal_spec_dict()
    doc["sources"] = []
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_spec_rejects_prd_only_fields():
    doc = minimal_spec_dict()
    doc["specs"] = ["spec-18-channel-telegram"]  # prd-only field
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_prd_rejects_spec_only_fields():
    doc = minimal_prd_dict()
    doc["interfaces"] = [{"name": "foo", "file": "bar.py"}]  # spec-only field
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)


def test_unknown_field_rejected():
    doc = minimal_spec_dict()
    doc["bogus"] = 1
    with pytest.raises(ValidationError):
        AboutDoc.model_validate(doc)
