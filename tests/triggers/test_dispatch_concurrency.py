"""Concurrency gate for ``POST /api/v1/run`` (`specs/30-non-interactive-triggers.md` §4.3)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from sevn.triggers.dispatcher import TriggerDispatchGate


@pytest.mark.asyncio
async def test_api_slot_second_acquire_raises_429() -> None:
    gate = TriggerDispatchGate(1)
    await gate.acquire_api_slot()
    with pytest.raises(HTTPException) as excinfo:
        await gate.acquire_api_slot()
    assert excinfo.value.status_code == 429
    gate.release_api_slot()
