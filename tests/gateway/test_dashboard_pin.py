"""Dashboard pin publisher tests (`plan/control-surface-wave-plan.md` Wave 3)."""

from __future__ import annotations

import asyncio

import pytest

from sevn.gateway.dashboard_pin import DashboardPinPublisher, default_pin_keyboard


@pytest.mark.asyncio
async def test_debounce_coalesces_rapid_updates() -> None:
    calls: list[int] = []

    async def edit_fn(**kwargs: object) -> bool:
        _ = kwargs
        calls.append(1)
        return True

    pub = DashboardPinPublisher(
        debounce_s=0.05, global_capacity=10.0, global_refill_per_second=10.0
    )
    for _ in range(3):
        await pub.schedule_render(
            chat_id=1,
            topic_id=None,
            message_id=9,
            text="a",
            reply_markup=default_pin_keyboard(),
            edit_fn=edit_fn,
        )
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.12)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_global_rate_limit_blocks_burst() -> None:
    calls: list[int] = []

    async def edit_fn(**kwargs: object) -> bool:
        _ = kwargs
        calls.append(1)
        return True

    pub = DashboardPinPublisher(
        debounce_s=0.0,
        global_capacity=1.0,
        global_refill_per_second=0.0,
    )
    await pub.schedule_render(
        chat_id=1,
        topic_id=None,
        message_id=9,
        text="a",
        reply_markup=default_pin_keyboard(),
        edit_fn=edit_fn,
    )
    await pub.schedule_render(
        chat_id=2,
        topic_id=None,
        message_id=10,
        text="b",
        reply_markup=default_pin_keyboard(),
        edit_fn=edit_fn,
    )
    await asyncio.sleep(0.02)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_edit_failure_logged_and_subsequent_schedule_works() -> None:
    from loguru import logger as loguru_logger

    calls: list[int] = []
    captured: list[str] = []

    async def edit_fn(**kwargs: object) -> bool:
        _ = kwargs
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("edit exploded")
        return True

    pub = DashboardPinPublisher(
        debounce_s=0.05, global_capacity=10.0, global_refill_per_second=10.0
    )
    sink_id = loguru_logger.add(lambda rec: captured.append(str(rec)), level="ERROR")
    try:
        await pub.schedule_render(
            chat_id=42,
            topic_id=None,
            message_id=9,
            text="first",
            reply_markup=default_pin_keyboard(),
            edit_fn=edit_fn,
        )
        await asyncio.sleep(0.12)
        assert any("dashboard_pin_edit_failed chat_id=42" in line for line in captured)

        await pub.schedule_render(
            chat_id=42,
            topic_id=None,
            message_id=9,
            text="second",
            reply_markup=default_pin_keyboard(),
            edit_fn=edit_fn,
        )
        await asyncio.sleep(0.12)
        assert len(calls) == 2
    finally:
        loguru_logger.remove(sink_id)
