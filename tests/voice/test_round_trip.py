"""STT/TTS round-trip integration (`specs/20-voice.md` §9, Wave 7B gate)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.voice.backends import TranscriptionResult
from sevn.voice.stt import SpeechToTextPipeline
from sevn.voice.tts import TextToSpeechPipeline


class _RoundTripSTT:
    id = "round_stt"

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
        raw = audio_path.read_bytes()
        text = raw.decode("utf-8", errors="replace").strip()
        return TranscriptionResult(text=text, provider=self.id, confidence=0.95)


class _RoundTripTTS:
    id = "round_tts"

    async def is_available(self) -> bool:
        return True

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        _ = voice_id
        out_path.write_bytes(text.encode("utf-8"))


@pytest.mark.asyncio
async def test_stt_tts_round_trip_preserves_message(tmp_path: Path) -> None:
    """Inbound bytes → transcript → outbound audio encodes assistant reply."""
    audio_in = tmp_path / "in.bin"
    audio_in.write_bytes(b"user said hello")

    stt = SpeechToTextPipeline(
        [_RoundTripSTT()],
        stt_confidence_reprompt_threshold=0.7,
        trace=NullTraceSink(),
    )
    transcript, stt_meta = await stt.transcribe_or_placeholder(
        audio_path=audio_in,
        mime_type="audio/ogg",
        duration_s=1.0,
        session_id="sess",
        turn_id="turn",
    )
    assert transcript == "user said hello"
    assert stt_meta["stt_provider"] == "round_stt"

    assistant_reply = f"heard: {transcript}"
    tts_dir = tmp_path / "channel_files" / ".tts"
    tts = TextToSpeechPipeline(
        [_RoundTripTTS()],
        voice_trigger_keywords=(),
        trace=NullTraceSink(),
        tts_output_dir=tts_dir,
    )
    assert tts.should_synthesize(session_tts_mode="all", user_text_last_turn=transcript)

    outcome = await tts.synthesize_or_skip(
        cleaned_assistant_text=assistant_reply,
        voice_id=None,
        session_id="sess",
        turn_id="turn",
    )
    assert outcome.result is not None
    assert outcome.result.provider == "round_tts"
    assert outcome.result.path.is_file()
    assert outcome.result.path.read_bytes() == assistant_reply.encode("utf-8")
