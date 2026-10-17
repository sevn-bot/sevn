"""Self-test for the K-CANARY kit. This test is green in W1."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes.fake_claude import FakeClaudeClient
from support.canary import canary
from support.chat import arm_home


async def test_canary_detects_planted_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.log import logger

    arm_home(monkeypatch, tmp_path)
    with canary() as probe:
        logger.warning("seen " + probe.value)
        probe.assert_absent(probe.value)
        assert any(f"«redacted:{probe.name}»" in line for line in probe._logs)

        for name in probe.capture_names:
            probe.plant(name, probe.value)
            with pytest.raises(AssertionError, match=f"canary leaked in {name}"):
                probe.assert_absent(probe.value)
            probe.unplant(name)
            probe.assert_absent(probe.value)

        await FakeClaudeClient().query(probe.value)
        with pytest.raises(AssertionError, match="canary leaked in fake_claude"):
            probe.assert_absent(probe.value)
