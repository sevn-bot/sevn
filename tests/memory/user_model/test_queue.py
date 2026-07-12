"""Per-workspace extraction queue (`specs/32-memory-honcho.md` §4.1)."""

from __future__ import annotations

import asyncio

import pytest

from sevn.memory.user_model.queue import (
    USER_MODEL_PROMPT_REV,
    UserModelExtractionQueue,
    schedule_user_model_extraction,
)


def test_prompt_rev_pinned() -> None:
    assert USER_MODEL_PROMPT_REV == 1


@pytest.mark.asyncio
async def test_queue_serializes_jobs() -> None:
    order: list[int] = []

    async def work(n: int) -> int:
        await asyncio.sleep(0.01)
        order.append(n)
        return n

    q = UserModelExtractionQueue("/tmp/ws-queue-test")
    await asyncio.gather(
        q.run_serialized(lambda: work(1)),
        q.run_serialized(lambda: work(2)),
    )
    assert order == [1, 2]


@pytest.mark.asyncio
async def test_schedule_user_model_extraction_drains() -> None:
    seen: list[int] = []

    async def job() -> None:
        seen.append(1)

    await schedule_user_model_extraction("/tmp/ws-schedule-test", job)
    await asyncio.sleep(0.05)
    assert seen == [1]
