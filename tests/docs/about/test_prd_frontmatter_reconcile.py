"""RED contract tests for about-docs PRD frontmatter reconciliation (D7). Green after W4.

Exports:
    test_extract_fields_omits_spec_only_keys_for_prd — PRD extract omits spec-only keys.
    test_extract_fields_still_emits_interfaces_for_spec — spec extract keeps interfaces.
    test_dump_prd_frontmatter_omits_forbidden_keys — PRD dump omits forbidden keys.
    test_dump_spec_frontmatter_retains_interfaces — spec dump retains interfaces.
    test_extract_merge_dump_prd_pipeline_omits_forbidden_keys — PRD pipeline omits forbidden keys.
    test_about_docs_check_passes_clean_prd_without_forbidden_keys — check passes clean PRD.

Examples:
    >>> len(FORBIDDEN_PRD_KEYS)
    3
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sevn.docs.about.check import check_about_docs
from sevn.docs.about.extract import extract_fields
from sevn.docs.about.index import index_path, render_index
from sevn.docs.about.loader import dump_doc
from sevn.docs.about.model import AboutDoc, Interface

FORBIDDEN_PRD_KEYS = ("interfaces", "depends_on", "build_phase")


def _minimal_prd() -> AboutDoc:
    """Return a minimal valid PRD :class:`AboutDoc` for tests.

    Returns:
        AboutDoc: PRD model with required fields populated.

    Examples:
        >>> doc = _minimal_prd()
        >>> doc.kind
        'prd'
    """
    return AboutDoc(
        id="prd-01-conversational-experience",
        kind="prd",
        title="Conversational Experience",
        status="ready",
        owner="Alex",
        summary="End-to-end conversational flow.",
        last_updated=date(2026, 7, 14),
        parent_prd=None,
        sources=["Makefile"],
    )


def _minimal_spec() -> AboutDoc:
    """Return a minimal valid spec :class:`AboutDoc` for tests.

    Returns:
        AboutDoc: Spec model with required fields populated.

    Examples:
        >>> doc = _minimal_spec()
        >>> doc.kind
        'spec'
    """
    return AboutDoc(
        id="spec-17-gateway",
        kind="spec",
        title="Gateway",
        status="done",
        owner="Alex",
        summary="Gateway turn spine.",
        last_updated=date(2026, 7, 14),
        parent_prd="prd-01-conversational-experience",
        sources=["src/sevn/gateway/**"],
    )


def test_extract_fields_omits_spec_only_keys_for_prd(tmp_path: Path) -> None:
    """D7: ``extract_fields`` must not emit spec-only keys for ``kind: prd``.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Examples:
        >>> "interfaces" in FORBIDDEN_PRD_KEYS
        True
    """
    (tmp_path / "Makefile").write_text("ci:\n\ttrue\n", encoding="utf-8")
    fields = extract_fields(tmp_path, {"kind": "prd", "sources": ["Makefile"]})
    for key in FORBIDDEN_PRD_KEYS:
        assert key not in fields
    assert "interfaces" not in fields


def test_extract_fields_still_emits_interfaces_for_spec(tmp_path: Path) -> None:
    """D7: spec extraction keeps ``interfaces`` for ``kind: spec``.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Examples:
        >>> "interfaces" not in FORBIDDEN_PRD_KEYS
        True
    """
    module_dir = tmp_path / "src" / "sevn" / "gateway"
    module_dir.mkdir(parents=True)
    (module_dir / "agent_turn.py").write_text(
        "def run_turn() -> None:\n    pass\n", encoding="utf-8"
    )
    fields = extract_fields(
        tmp_path,
        {"kind": "spec", "sources": ["src/sevn/gateway/**"]},
    )
    assert "interfaces" in fields
    assert fields["interfaces"]


def test_dump_prd_frontmatter_omits_forbidden_keys() -> None:
    """D7: serialised PRD frontmatter must not contain forbidden keys at all.

    Examples:
        >>> FORBIDDEN_PRD_KEYS[0]
        'interfaces'
    """
    text = dump_doc(_minimal_prd(), "## Problem & Motivation\n\nBody.\n")
    frontmatter = text.split("---", maxsplit=2)[1]
    for key in FORBIDDEN_PRD_KEYS:
        assert f"{key}:" not in frontmatter


def test_dump_spec_frontmatter_retains_interfaces() -> None:
    """D7: spec serialisation keeps ``interfaces`` / ``depends_on`` where applicable.

    Examples:
        >>> "depends_on" in FORBIDDEN_PRD_KEYS
        True
    """
    doc = _minimal_spec().model_copy(
        update={
            "interfaces": [
                Interface(
                    name="run_turn",
                    file="src/sevn/gateway/agent_turn.py",
                    symbol="run_turn",
                )
            ],
            "depends_on": ["spec-02-config-and-workspace"],
        }
    )
    text = dump_doc(doc, "## Purpose\n\nBody.\n")
    frontmatter = text.split("---", maxsplit=2)[1]
    assert "interfaces:" in frontmatter
    assert "depends_on:" in frontmatter


def test_extract_merge_dump_prd_pipeline_omits_forbidden_keys(tmp_path: Path) -> None:
    """Integration: extract → merge → dump for PRD never reintroduces forbidden keys.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Examples:
        >>> len(FORBIDDEN_PRD_KEYS)
        3
    """
    (tmp_path / "Makefile").write_text("ci:\n\ttrue\n", encoding="utf-8")
    merged = _minimal_prd().model_copy(
        update=extract_fields(tmp_path, _minimal_prd().model_dump(mode="json"))
    )
    text = dump_doc(merged, "## Problem & Motivation\n\nBody.\n")
    frontmatter = text.split("---", maxsplit=2)[1]
    for key in FORBIDDEN_PRD_KEYS:
        assert f"{key}:" not in frontmatter


def test_about_docs_check_passes_clean_prd_without_forbidden_keys(
    tmp_path: Path,
) -> None:
    """D7: ``check_about_docs`` stays green once PRD files omit forbidden keys.

    Args:
        tmp_path (Path): pytest temporary directory fixture.

    Examples:
        >>> "build_phase" in FORBIDDEN_PRD_KEYS
        True
    """
    docs_dir = tmp_path / "about-sevn.bot" / "prd"
    docs_dir.mkdir(parents=True)
    allowlist_dir = tmp_path / "about-sevn.bot" / "_docsys"
    allowlist_dir.mkdir(parents=True)
    allowlist_dir.joinpath("allowed-refs.txt").write_text("Makefile\nsrc/**\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text("ci:\n\ttrue\n", encoding="utf-8")
    merged = _minimal_prd().model_copy(
        update=extract_fields(tmp_path, _minimal_prd().model_dump(mode="json"))
    )
    doc_path = docs_dir / "01-conversational-experience.md"
    doc_path.write_text(
        dump_doc(merged, "## Problem & Motivation\n\nBody.\n"),
        encoding="utf-8",
    )
    index_file = index_path(tmp_path, "prd")
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(render_index([merged], "prd"), encoding="utf-8")
    frontmatter = doc_path.read_text(encoding="utf-8").split("---", maxsplit=2)[1]
    for key in FORBIDDEN_PRD_KEYS:
        assert f"{key}:" not in frontmatter
    issues = check_about_docs(tmp_path)
    assert issues == []
