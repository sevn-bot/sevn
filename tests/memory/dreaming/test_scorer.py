"""Scorer + promoter integration tests (`specs/31-memory-dreaming.md` §9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.config.workspace_config import (
    DreamingLlmRankerWorkspaceConfig,
    DreamingScoringWorkspaceConfig,
    DreamingWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.memory.dreaming.models import DreamingCandidate
from sevn.memory.dreaming.promoter import promote_auto_batch
from sevn.memory.dreaming.rollback import rollback_manifest
from sevn.memory.dreaming.scorer import build_candidates, maybe_llm_rerank
from sevn.memory.dreaming.sources import RawMemorySignal


def _signal_dm(topic: str, content: str, score_boost: str = "dm:owner") -> RawMemorySignal:
    return RawMemorySignal(
        source_kind="memory",
        source_key=f"memory:{score_boost}:{topic}",
        session_label=score_boost,
        topic=topic,
        content=content,
        created_at="2099-01-01",
        metadata=None,
    )


def test_build_candidates_dm_only_and_threshold() -> None:
    cfg = DreamingWorkspaceConfig(enabled=True, threshold=0.01, max_promotions_per_run=2)
    raws = [
        _signal_dm("a", "longer text " * 20),
        _signal_dm("b", "also decent " * 15),
        _signal_dm("g", "nope", score_boost="grp:1"),
    ]
    kept, _eligible, _skipped = build_candidates(raws, cfg)
    assert len(kept) >= 2


def test_group_memory_row_filtered() -> None:
    cfg = DreamingWorkspaceConfig(enabled=True, threshold=0.0)
    raws = [_signal_dm("g", "x", score_boost="grp:1")]
    _kept, _eligible, _skipped = build_candidates(raws, cfg)
    assert _kept == []


def test_promote_then_rollback_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    mem = root / "MEMORY.md"
    mem.write_text("# Mem\norig\n", encoding="utf-8")
    cands = [
        DreamingCandidate(
            candidate_id="c1",
            topic="t1",
            value="v1",
            score=0.9,
            source_keys=["k1"],
        ),
    ]
    _append, man_path, _m = promote_auto_batch(root, run_id="r1", mode="auto", candidates=cands)
    after = mem.read_text(encoding="utf-8")
    assert "v1" in after
    rollback_manifest(root, man_path)
    assert mem.read_text(encoding="utf-8") == "# Mem\norig\n"


def test_dreaming_workspace_config_in_root_model() -> None:
    raw = WorkspaceConfig(
        schema_version=1,
        memory={"dreaming": {"enabled": True, "threshold": 0.4}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    assert raw.memory is not None
    assert raw.memory.dreaming is not None
    assert raw.memory.dreaming.enabled is True
    assert raw.memory.dreaming.threshold == 0.4


@pytest.mark.asyncio
async def test_llm_ranker_fallback_on_error() -> None:
    class Boom:
        name = "mock"

        async def complete(self, _req: dict) -> dict:  # type: ignore[no-untyped-def]
            raise RuntimeError("no network")

    cfg = DreamingWorkspaceConfig(
        enabled=True,
        scoring=DreamingScoringWorkspaceConfig(
            llm_ranker=DreamingLlmRankerWorkspaceConfig(enabled=True, model="test"),
        ),
    )
    cands = [
        DreamingCandidate(candidate_id="a", topic="t", value="v", score=0.5),
        DreamingCandidate(candidate_id="b", topic="t2", value="v2", score=0.4),
    ]
    out, err = await maybe_llm_rerank(
        list(cands),
        dreaming=cfg,
        transport=Boom(),  # type: ignore[arg-type]
        lcm_summary_model="fallback",
    )
    assert err is True
    assert [x.candidate_id for x in out] == ["a", "b"]
