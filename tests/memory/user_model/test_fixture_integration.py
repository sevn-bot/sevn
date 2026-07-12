"""Golden fixture integration for user model (`specs/32-memory-honcho.md` §10.4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sevn.memory.user_model.merger import UserModelMerger
from sevn.memory.user_model.models import InferredFact, UserProfile
from sevn.memory.user_model.renderer import render_profile_block

REPO = Path(__file__).resolve().parents[3]


def test_profile_golden_fixture_renders() -> None:
    path = REPO / "tests" / "fixtures" / "memory" / "user_model" / "profile_golden.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    prof = UserProfile.model_validate(raw)
    merger = UserModelMerger()
    bump = InferredFact(
        id="n1",
        topic="language_preference",
        value="Prefers Python for services.",
        confidence="high",
        last_observed_at=datetime(2026, 5, 13, 13, 0, 0, tzinfo=UTC),
        source_session_ids=["sess-b"],
    )
    merged = merger.merge(prof, [bump], deny_topic_patterns=[], max_facts=64)
    block = render_profile_block(merged, max_tokens=400, now=datetime.now(tz=UTC))
    assert "language_preference" in block


def test_disabled_config_does_not_write_on_load(tmp_path: Path) -> None:
    """When no save occurs, ``load`` must not create ``.sevn`` dirs."""

    from sevn.memory.user_model.store import UserModelStore

    root = tmp_path / "ws"
    root.mkdir()
    prof = UserModelStore().load(str(root))
    assert prof.facts == []
    assert not (root / ".sevn").exists()
