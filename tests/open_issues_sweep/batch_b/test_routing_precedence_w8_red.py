"""W8.1 — model override precedence matrix (#86 → W9).

Contract: default → workspace slot → channel → session; exactly one winner per case;
omitting a level falls through to the next lower level.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from tests.open_issues_sweep.batch_b.conftest import (
    baseline_minimal_workspace,
    baseline_split_workspace,
)

from sevn.config.model_resolution import ModelSlot


@dataclass(frozen=True)
class _PrecedenceCase:
    """One row of the W9 precedence table."""

    workspace_tier_b: str | None
    channel_model: str | None
    session_once_model: str | None
    expected_model: str
    expected_source: str
    unified: bool = True


def _resolve_turn_model(
    cfg: object,
    *,
    channel: str,
    scope_key: str | None,
    session_once_model: str | None,
) -> tuple[str, str]:
    """Call the W9 turn overlay resolver (lazy import keeps collection clean)."""
    from sevn.config.model_resolution import (
        ModelResolutionSource,
        resolve_model_slot_for_turn,
    )

    result = resolve_model_slot_for_turn(
        cfg,
        ModelSlot.tier_b,
        channel=channel,
        scope_key=scope_key,
        session_once_model=session_once_model,
    )
    assert isinstance(result.source, ModelResolutionSource)
    return result.model_id, result.source.value


def _workspace_for_case(case: _PrecedenceCase) -> object:
    if case.unified:
        base = baseline_minimal_workspace(
            tier_b=case.workspace_tier_b or "minimax/MiniMax-M2.7",
        )
    else:
        base = baseline_split_workspace()
    channels: dict[str, object] = {}
    if case.channel_model is not None:
        channels["telegram"] = {"model": case.channel_model}
    doc = base.model_dump()
    if channels:
        doc["channels"] = channels
    from sevn.config.workspace_config import WorkspaceConfig

    return WorkspaceConfig.model_validate(doc)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b=None,
                channel_model=None,
                session_once_model=None,
                expected_model="minimax/MiniMax-M2.7",
                expected_source="default",
            ),
            id="all_absent_falls_to_default",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b="anthropic/claude-sonnet-4-20250514",
                channel_model=None,
                session_once_model=None,
                expected_model="anthropic/claude-sonnet-4-20250514",
                expected_source="workspace",
                unified=False,
            ),
            id="workspace_slot_only",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b=None,
                channel_model="openai/gpt-4.1",
                session_once_model=None,
                expected_model="openai/gpt-4.1",
                expected_source="channel",
            ),
            id="channel_only",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b=None,
                channel_model=None,
                session_once_model="openai/gpt-4o",
                expected_model="openai/gpt-4o",
                expected_source="session",
            ),
            id="session_once_only",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b="anthropic/claude-sonnet-4-20250514",
                channel_model="openai/gpt-4.1",
                session_once_model=None,
                expected_model="openai/gpt-4.1",
                expected_source="channel",
                unified=False,
            ),
            id="channel_beats_workspace",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b="anthropic/claude-sonnet-4-20250514",
                channel_model="openai/gpt-4.1",
                session_once_model="minimax/MiniMax-M3",
                expected_model="minimax/MiniMax-M3",
                expected_source="session",
                unified=False,
            ),
            id="session_beats_channel_and_workspace",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b="anthropic/claude-sonnet-4-20250514",
                channel_model=None,
                session_once_model=None,
                expected_model="anthropic/claude-sonnet-4-20250514",
                expected_source="workspace",
                unified=False,
            ),
            id="omit_channel_falls_to_workspace",
        ),
        pytest.param(
            _PrecedenceCase(
                workspace_tier_b=None,
                channel_model="openai/gpt-4.1",
                session_once_model=None,
                expected_model="openai/gpt-4.1",
                expected_source="channel",
            ),
            id="omit_session_keeps_channel",
        ),
    ],
)
def test_model_precedence_matrix_exactly_one_winner(case: _PrecedenceCase) -> None:
    cfg = _workspace_for_case(case)
    model_id, source = _resolve_turn_model(
        cfg,
        channel="telegram",
        scope_key=None,
        session_once_model=case.session_once_model,
    )
    assert model_id == case.expected_model
    assert source == case.expected_source


def test_precedence_scope_key_does_not_leak_across_topics() -> None:
    cfg = _workspace_for_case(
        _PrecedenceCase(
            workspace_tier_b=None,
            channel_model="openai/gpt-4.1",
            session_once_model=None,
            expected_model="minimax/MiniMax-M2.7",
            expected_source="default",
        ),
    )
    # Topic-specific override should not apply to a different scope_key.
    from sevn.config.model_resolution import (
        resolve_model_slot_for_turn,
    )

    topic_cfg = cfg.model_copy(deep=True)
    topic_doc = topic_cfg.model_dump()
    topic_doc.setdefault("channels", {})["telegram"] = {
        "model": "openai/gpt-4.1",
        "topics": {"42": {"topic_id": 42, "model": "anthropic/claude-haiku-4-5"}},
    }
    from sevn.config.workspace_config import WorkspaceConfig

    topic_cfg = WorkspaceConfig.model_validate(topic_doc)
    other = resolve_model_slot_for_turn(
        topic_cfg,
        ModelSlot.tier_b,
        channel="telegram",
        scope_key="forum:1:99",
        session_once_model=None,
    )
    scoped = resolve_model_slot_for_turn(
        topic_cfg,
        ModelSlot.tier_b,
        channel="telegram",
        scope_key="forum:1:42",
        session_once_model=None,
    )
    assert other.model_id == "openai/gpt-4.1"
    assert scoped.model_id == "anthropic/claude-haiku-4-5"
