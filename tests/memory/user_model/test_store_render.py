"""Store + renderer smoke tests (`specs/32-memory-honcho.md`)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sevn.memory.user_model.models import InferredFact, UserProfile
from sevn.memory.user_model.renderer import render_profile_block
from sevn.memory.user_model.store import UserModelStore


def test_store_roundtrip(tmp_path: Path) -> None:
    store = UserModelStore()
    prof = UserProfile(
        workspace_id="abc",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        facts=[
            InferredFact(
                id="1",
                topic="lang",
                value="Python",
                confidence="high",
                last_observed_at=datetime(2026, 1, 2, tzinfo=UTC),
            ),
        ],
    )
    sevn = tmp_path / ".sevn"
    sevn.mkdir(parents=True)
    store.save(str(tmp_path), prof)
    path = tmp_path / ".sevn" / "user_model.json"
    assert path.is_file()
    got = store.load(str(tmp_path))
    assert got.facts[0].topic == "lang"


def test_renderer_respects_token_ceiling() -> None:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    facts = [
        InferredFact(
            id=str(i),
            topic=f"t{i}",
            value="word " * 40,
            confidence="high",
            last_observed_at=now,
        )
        for i in range(5)
    ]
    prof = UserProfile(workspace_id="w", updated_at=now, facts=facts)
    block = render_profile_block(prof, max_tokens=12, now=now)
    assert block
    assert block.count("\n") < 5
