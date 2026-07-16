"""RED suite for queue classifier timeout (D15; green after W8)."""

from __future__ import annotations

import asyncio

import pytest

from sevn.agent.triager import relatedness as rel
from sevn.agent.triager.relatedness import RelatednessInput, RelatednessResult, classify_relatedness
from sevn.config.workspace_config import WorkspaceConfig

_XFAIL_W8 = pytest.mark.xfail(
    reason="green after W8: classifier timeout must not silently merge (D15)",
    strict=False,
)


@_XFAIL_W8
@pytest.mark.asyncio
async def test_d15_classifier_timeout_enqueues_own_turn_not_related_steer() -> None:
    """D15: on classifier timeout, enqueue as ``new_task`` — never silent ``related_steer``."""

    async def _slow_transport(*_a: object, **_k: object) -> str:
        await asyncio.sleep(60)
        return "related_steer"

    orig = rel._classify_via_triager_transport
    rel._classify_via_triager_transport = _slow_transport  # type: ignore[assignment]
    try:
        result = await classify_relatedness(
            workspace=WorkspaceConfig.minimal(),
            inp=RelatednessInput(
                in_flight_task_summary="debugging CDP browser NO_CDP",
                queued_task_summaries=(),
                new_message="list all your tools",
            ),
            session_id="triager-d15",
            turn_id="turn-d15",
            timeout_s=0.05,
        )
    finally:
        rel._classify_via_triager_transport = orig  # type: ignore[assignment]

    assert isinstance(result, RelatednessResult)
    assert result.label != "related_steer"
    assert result.label == "new_task"
    assert result.fallback is True


@_XFAIL_W8
@pytest.mark.asyncio
async def test_d15_unrelated_ask_not_absorbed_into_in_flight_summary() -> None:
    """D15: timed-out unrelated asks must not be absorbed into the in-flight task."""

    async def _slow_transport(*_a: object, **_k: object) -> str:
        await asyncio.sleep(60)
        return "related_steer"

    orig = rel._classify_via_triager_transport
    rel._classify_via_triager_transport = _slow_transport  # type: ignore[assignment]
    try:
        result = await classify_relatedness(
            workspace=WorkspaceConfig.minimal(),
            inp=RelatednessInput("in-flight A", (), "Why playwright? Do not use it."),
            session_id="triager-d15b",
            turn_id="turn-d15b",
            timeout_s=0.05,
        )
    finally:
        rel._classify_via_triager_transport = orig  # type: ignore[assignment]

    assert result.fallback is True
    assert result.label == "new_task"
