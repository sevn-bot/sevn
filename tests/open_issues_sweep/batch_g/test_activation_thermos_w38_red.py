"""G-Thermos — owner-only menu rows and ``scan_voice`` on post-activation hand-off."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    _StaticFrameSource,
    baseline_voice_workspace,
    import_voice_activation_module,
)

from sevn.gateway.menu.menu_registry import match_menu_button_spec
from sevn.security.llm_guard_scanner import BlockReason, ScanResult, ScanVerdict


def test_activation_menu_rows_are_owner_only() -> None:
    """Mic activation toggle and wake-phrase cycle require the Telegram owner."""
    toggle = match_menu_button_spec("cfg:toggle:voice.activation.enabled:true")
    assert toggle is not None
    assert toggle.owner_only is True
    cycle = match_menu_button_spec("cfg:voice:activation:wake:next")
    assert cycle is not None
    assert cycle.owner_only is True


@pytest.mark.asyncio
async def test_scan_voice_blocks_post_activation_transcript(
    tmp_path: Path,
    mock_stt_pipeline: AsyncMock,
) -> None:
    activation = import_voice_activation_module()
    mock_stt_pipeline.transcribe_or_placeholder.return_value = ("blocked phrase", {})
    scanner = MagicMock()
    scanner.scan_inbound = AsyncMock(
        return_value=ScanResult(
            verdict=ScanVerdict.block,
            reasons=(BlockReason.toxicity,),
            scores={},
            provider_used="heuristic",
            details={},
        ),
    )
    source = _StaticFrameSource((b"\x00" * 64, b"\xff" * 128))
    listener = activation.WakeWordListener(
        workspace=baseline_voice_workspace(),
        frame_source=source,
        stt_pipeline=mock_stt_pipeline,
        trace=None,
        attachments_dir=tmp_path / "attachments",
        wake_word="hey sevn",
        simulate_activation_at_frame=1,
        scanner=scanner,
        content_root=tmp_path,
    )
    await listener.run_until_idle(max_frames=2)
    scanner.scan_inbound.assert_awaited_once()
    assert scanner.scan_inbound.await_args.kwargs["source"] == "voice.activation.handoff"
