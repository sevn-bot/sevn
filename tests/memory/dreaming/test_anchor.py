"""Promotion manifest anchors (`specs/31-memory-dreaming.md` §3.2)."""

from __future__ import annotations

from pathlib import Path

from sevn.memory.dreaming.models import DreamingCandidate, PromotedBatchManifest
from sevn.memory.dreaming.promoter import promote_auto_batch
from sevn.memory.dreaming.rollback import rollback_manifest


def test_memory_md_anchor_line_range_and_hash(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    mem = root / "MEMORY.md"
    mem.write_text("# Mem\norig\n", encoding="utf-8")
    cands = [
        DreamingCandidate(candidate_id="c1", topic="t", value="v1", score=0.9),
        DreamingCandidate(candidate_id="c2", topic="t2", value="v2", score=0.8),
    ]
    _txt, man_path, manifest = promote_auto_batch(root, run_id="r1", mode="auto", candidates=cands)
    assert len(manifest.rows) == 2
    row0 = manifest.rows[0]
    assert row0.memory_md_anchor.line_start == 3
    assert row0.memory_md_anchor.line_end == 3
    assert len(row0.memory_md_anchor.content_sha256) == 64
    assert row0.memory_md_anchor.byte_start is not None
    rollback_manifest(root, man_path)
    assert mem.read_text(encoding="utf-8") == "# Mem\norig\n"


def test_promoted_manifest_round_trip_json(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    c = DreamingCandidate(candidate_id="x", topic="t", value="v", score=0.5)
    _t, path, m = promote_auto_batch(root, run_id="rid", mode="auto", candidates=[c])
    loaded = PromotedBatchManifest.model_validate_json(path.read_text(encoding="utf-8"))
    assert (
        loaded.rows[0].memory_md_anchor.content_sha256 == m.rows[0].memory_md_anchor.content_sha256
    )
