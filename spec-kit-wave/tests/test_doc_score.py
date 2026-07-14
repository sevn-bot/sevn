"""RED contract tests for ``skw.doc_score`` (D5). Green after W3."""

from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import (
    SCORE_COMPONENTS,
    SCORE_THRESHOLD,
    SPEC_REQUIRED_SECTIONS,
    require_module,
)


def _score_weights(kind: str) -> dict[str, int]:
    doc_score = require_module("skw.doc_score")
    return doc_score.load_score_weights(kind)


def _score_doc(path: Path, *, kind: str, repo_root: Path, siblings: list[Path] | None = None):
    doc_score = require_module("skw.doc_score")
    return doc_score.score_doc(path, kind, repo_root=repo_root, siblings=siblings)


def _write_doc(
    directory: Path,
    *,
    kind: str,
    status: str,
    body: str,
    sources: list[str],
    interfaces: list[dict[str, str]] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    if kind == "spec":
        doc_id = "spec-17-gateway"
        filename = "17-gateway.md"
        parent = "parent_prd: prd-01-conversational-experience"
        interface_block = ""
        if interfaces is None:
            interfaces = [
                {
                    "name": "run_turn",
                    "file": "src/sevn/gateway/agent_turn.py",
                    "symbol": "run_turn",
                }
            ]
        interface_block = "interfaces:\n" + "\n".join(
            f"  - name: {row['name']}\n    file: {row['file']}\n    symbol: {row['symbol']}"
            for row in interfaces
        )
    else:
        doc_id = "prd-01-conversational-experience"
        filename = "01-conversational-experience.md"
        parent = "parent_prd: null"
        interface_block = ""
    source_lines = "\n".join(f"  - {item}" for item in sources)
    text = f"""---
id: {doc_id}
kind: {kind}
title: Sample
status: {status}
owner: Alex
summary: Sample document for scoring.
last_updated: 2026-07-14
{parent}
sources:
{source_lines}
{interface_block}
fingerprint: sha256:abc
related: []
depends_on: []
---

{body}
"""
    path = directory / filename
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("kind", ["spec", "prd"])
def test_score_weights_sum_to_one_hundred(kind: str) -> None:
    """D5: component weights in ``*-rules.toml [score]`` sum to 100."""
    weights = _score_weights(kind)
    assert set(weights) == set(SCORE_COMPONENTS)
    assert sum(weights.values()) == 100


def test_scaffold_body_scores_below_threshold(repo_root: Path, tmp_path: Path) -> None:
    """D5: scaffold placeholder prose must score below the 80 threshold."""
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nOffline scaffold for gateway." for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="scaffold",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    result = _score_doc(
        path, kind="spec", repo_root=repo_root, siblings=list(docs_dir.glob("*.md"))
    )
    assert result.total < SCORE_THRESHOLD
    assert result.components["no_scaffold_phrase"] == 0


def test_authored_spec_scores_at_or_above_threshold(repo_root: Path, tmp_path: Path) -> None:
    """D5: fully authored, resolving spec scores >= 80."""
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nAuthored prose for {heading.lower()}."
        for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="done",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    result = _score_doc(
        path, kind="spec", repo_root=repo_root, siblings=list(docs_dir.glob("*.md"))
    )
    assert result.total >= SCORE_THRESHOLD


def test_status_honesty_component_penalizes_done_with_scaffold(
    repo_root: Path, tmp_path: Path
) -> None:
    """D5: ``status_honesty`` component fails when ``done`` overlays scaffold prose."""
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(
        f"## {heading}\n\nInitial draft for gateway." for heading in SPEC_REQUIRED_SECTIONS
    )
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="done",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    result = _score_doc(
        path, kind="spec", repo_root=repo_root, siblings=list(docs_dir.glob("*.md"))
    )
    assert result.components["status_honesty"] == 0
    assert result.total < SCORE_THRESHOLD


def test_score_result_exposes_breakdown_and_rollup(repo_root: Path, tmp_path: Path) -> None:
    """D5: scorer returns per-component breakdown and folder rollup helper."""
    doc_score = require_module("skw.doc_score")
    docs_dir = tmp_path / "specs"
    body = "\n\n".join(f"## {heading}\n\nAuthored prose." for heading in SPEC_REQUIRED_SECTIONS)
    path = _write_doc(
        docs_dir,
        kind="spec",
        status="done",
        body=body,
        sources=["src/sevn/gateway/**"],
    )
    siblings = list(docs_dir.glob("*.md"))
    one = _score_doc(path, kind="spec", repo_root=repo_root, siblings=siblings)
    assert set(one.components) == set(SCORE_COMPONENTS)
    assert isinstance(one.total, int)
    rollup = doc_score.rollup_scores([one])
    assert rollup["file_count"] == 1
    assert rollup["average_total"] == one.total
    assert rollup["below_threshold"] == []
