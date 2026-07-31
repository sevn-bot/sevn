"""W35.6 — no ambient leakage (#102 → W37, D24).

Non-activated audio must produce no attachment files, no transcripts, and no trace
attrs containing raw audio or non-activated text.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from tests.open_issues_sweep.batch_g.conftest import (
    FakeAudioScenario,
    _RecordingTraceSink,
    _StaticFrameSource,
    baseline_voice_workspace,
    import_voice_activation_module,
)

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent


def _trace_attrs_contain_audio_or_transcript(events: list[TraceEvent]) -> list[str]:
    violations: list[str] = []
    for event in events:
        attrs = event.attrs or {}
        for key, value in attrs.items():
            blob = repr(value).lower()
            if any(token in blob for token in ("audio_bytes", "pcm", "wav", "transcript")):
                violations.append(f"{event.kind}.{key}={value!r}")
    return violations


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            FakeAudioScenario("ambient_only", (b"\x00\x01" * 128,) * 3, activation_at_frame=None),
            id="ambient_only",
        ),
    ],
)
@pytest.mark.xfail(reason="green after W37: ambient frames never persisted", strict=False)
async def test_non_activated_audio_writes_no_attachment_files(
    tmp_path: Path,
    scenario: FakeAudioScenario,
) -> None:
    activation = import_voice_activation_module()
    content_root = tmp_path / "content"
    content_root.mkdir()
    attachments = content_root / "channel_files"
    attachments.mkdir()
    source = _StaticFrameSource(scenario.frames)
    listener = activation.WakeWordListener(
        workspace=baseline_voice_workspace(),
        frame_source=source,
        stt_pipeline=AsyncMock(),
        trace=None,
        attachments_dir=attachments,
    )
    await listener.run_until_idle(max_frames=len(scenario.frames))
    audio_files = list(attachments.rglob("*"))
    assert audio_files == [], f"ambient audio leaked files: {audio_files}"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W37: ambient audio never transcribed", strict=False)
async def test_non_activated_audio_produces_no_transcript(
    tmp_path: Path,
    mock_stt_pipeline: AsyncMock,
) -> None:
    activation = import_voice_activation_module()
    source = _StaticFrameSource((b"\x00" * 256,) * 4)
    listener = activation.WakeWordListener(
        workspace=baseline_voice_workspace(),
        frame_source=source,
        stt_pipeline=mock_stt_pipeline,
        trace=None,
        attachments_dir=tmp_path / "attachments",
    )
    await listener.run_until_idle(max_frames=4)
    mock_stt_pipeline.transcribe_or_placeholder.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W37: ambient audio never traced", strict=False)
async def test_non_activated_audio_emits_no_audio_bearing_trace_attrs(
    tmp_path: Path,
    recording_trace_sink: _RecordingTraceSink,
) -> None:
    activation = import_voice_activation_module()
    source = _StaticFrameSource((b"\xab\xcd" * 64,) * 2)
    listener = activation.WakeWordListener(
        workspace=baseline_voice_workspace(),
        frame_source=source,
        stt_pipeline=AsyncMock(),
        trace=recording_trace_sink,
        attachments_dir=tmp_path / "attachments",
    )
    await listener.run_until_idle(max_frames=2)
    violations = _trace_attrs_contain_audio_or_transcript(recording_trace_sink.events)
    assert violations == []
