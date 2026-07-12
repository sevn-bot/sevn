"""Unit tests for :mod:`sevn.voice.stt` (`specs/20-voice.md` §9)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.voice.backends import TranscriptionResult
from sevn.voice.stt import PLACEHOLDER_LLM_LINE, SpeechToTextPipeline


class _FailSTT:
    id = "fail"

    async def is_available(self) -> bool:
        return True

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        _ = audio_path, mime_type, duration_s, locale
        msg = "boom"
        raise RuntimeError(msg)


class _OkSTT:
    id = "ok"

    async def is_available(self) -> bool:
        return True

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        _ = mime_type, duration_s, locale
        assert audio_path.is_file()
        return TranscriptionResult(text="  hi there  ", provider=self.id, confidence=0.99)


class _EmptySTT:
    id = "empty"

    async def is_available(self) -> bool:
        return True

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        _ = audio_path, mime_type, duration_s, locale
        return TranscriptionResult(text="   ", provider=self.id, confidence=None)


@pytest.mark.asyncio
async def test_stt_chain_order_second_wins(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"x")
    pipe = SpeechToTextPipeline(
        [_FailSTT(), _OkSTT()],
        stt_confidence_reprompt_threshold=0.7,
        trace=NullTraceSink(),
    )
    text, meta = await pipe.transcribe_or_placeholder(
        audio_path=p,
        mime_type="audio/ogg",
        duration_s=1.0,
        session_id="s",
        turn_id="t",
    )
    assert text == "hi there"
    assert meta["stt_provider"] == "ok"
    assert meta["transcript"] == "hi there"


@pytest.mark.asyncio
async def test_stt_exhausted_placeholder(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"x")
    pipe = SpeechToTextPipeline(
        [_FailSTT(), _EmptySTT()],
        stt_confidence_reprompt_threshold=0.7,
        trace=NullTraceSink(),
    )
    text, meta = await pipe.transcribe_or_placeholder(
        audio_path=p,
        mime_type=None,
        duration_s=None,
        session_id="s",
        turn_id="t",
    )
    assert text == PLACEHOLDER_LLM_LINE
    assert meta["stt_provider"] == "placeholder"
    assert meta["transcript"] == ""


def test_placeholder_line_matches_prd() -> None:
    assert "Do NOT try to transcribe or read the audio file" in PLACEHOLDER_LLM_LINE


def test_transcribe_placeholder_returns_empty() -> None:
    from sevn.voice.stt import transcribe_placeholder

    out = asyncio.run(transcribe_placeholder(channel="telegram", attachment_meta={}))
    assert out == ""
