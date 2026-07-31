"""W35.7 — post-activation STT hand-off (#102 → W37).

An activation must produce exactly one utterance routed through the existing
``SpeechToTextPipeline.transcribe_or_placeholder`` chain — never a parallel path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    FakeAudioScenario,
    _StaticFrameSource,
    baseline_voice_workspace,
    import_voice_activation_module,
)


@pytest.mark.asyncio
async def test_activation_invokes_transcribe_or_placeholder_once(
    tmp_path: Path,
    mock_stt_pipeline: AsyncMock,
) -> None:
    activation = import_voice_activation_module()
    scenario = FakeAudioScenario(
        "activation_once",
        (b"\x00" * 128, b"\x00" * 128, b"\xff" * 256, b"\xff" * 256),
        activation_at_frame=2,
    )
    source = _StaticFrameSource(scenario.frames)
    listener = activation.WakeWordListener(
        workspace=baseline_voice_workspace(),
        frame_source=source,
        stt_pipeline=mock_stt_pipeline,
        trace=None,
        attachments_dir=tmp_path / "attachments",
        wake_word="hey sevn",
        simulate_activation_at_frame=scenario.activation_at_frame,
    )
    await listener.run_until_idle(max_frames=len(scenario.frames))
    mock_stt_pipeline.transcribe_or_placeholder.assert_awaited_once()


@pytest.mark.asyncio
async def test_activation_does_not_call_alternate_transcription_helper(
    tmp_path: Path,
    mock_stt_pipeline: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activation = import_voice_activation_module()
    alt = AsyncMock(return_value=("parallel path", {}))
    monkeypatch.setattr(activation, "transcribe_activation_utterance", alt, raising=False)
    source = _StaticFrameSource((b"\x00" * 64, b"\xff" * 128))
    listener = activation.WakeWordListener(
        workspace=baseline_voice_workspace(),
        frame_source=source,
        stt_pipeline=mock_stt_pipeline,
        trace=None,
        attachments_dir=tmp_path / "attachments",
        wake_word="hey sevn",
        simulate_activation_at_frame=1,
    )
    await listener.run_until_idle(max_frames=2)
    alt.assert_not_called()
    mock_stt_pipeline.transcribe_or_placeholder.assert_awaited_once()
