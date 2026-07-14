"""Onboarding web validator contracts for queue mode (D17; green after W9)."""

from __future__ import annotations

import pytest

from sevn.onboarding.web_app import _validate_field


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W9: gateway.queue_mode=multi accepted", strict=False)
async def test_web_validator_accepts_queue_mode_multi() -> None:
    """D17: onboarding web validator accepts ``gateway.queue_mode=multi``."""
    ok, message = await _validate_field("gateway.queue_mode", "multi", context={})
    assert ok is True
    assert message == "ok"


@pytest.mark.asyncio
async def test_web_validator_still_accepts_cancel_and_steer() -> None:
    """Baseline: existing queue modes remain valid until W9 extends the set."""
    for mode in ("cancel", "steer"):
        ok, message = await _validate_field("gateway.queue_mode", mode, context={})
        assert ok is True, message
