"""Wave W1 tests: voice duplex fixes (`build-plan-from-review/waves/
voice-duplex-tts-menu-log-fixes-wave-plan.md` W1.1-W1.3).

Tests-first: whisper.cpp STT is not yet provisioned (W2) and Kokoro warmup /
dispatch-timeout margin does not yet exist (W3), so several assertions here
are expected to be RED until those waves land.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from sevn.tools.context import ToolContext
from sevn.tools.decorator import tool_from_decorated
from sevn.tools.outbound import tts_tool
from sevn.voice.backends import (
    TranscriptionResult,
    WhisperCppBackend,
    _HttpClosedTTSBackend,
)
from sevn.voice.stt import PLACEHOLDER_LLM_LINE, SpeechToTextPipeline
from sevn.voice.tts import TextToSpeechPipeline

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent


class _RecordingTraceSink:
    """Collects every emitted :class:`TraceEvent` for assertion (no I/O).

    Structurally satisfies :class:`sevn.agent.tracing.sink.TraceSink` (duck-typed
    Protocol) without subclassing it, matching :class:`~sevn.agent.tracing.sink.NullTraceSink`.
    """

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


# --- W1.1: whisper.cpp backend --------------------------------------------------


@pytest.mark.asyncio
async def test_whisper_cpp_is_available_true_when_binary_and_model_resolve(
    tmp_path: Path,
) -> None:
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"weights")
    with (
        patch("sevn.voice.backends.shutil.which", return_value="/usr/local/bin/whisper-cpp"),
        patch.dict(os.environ, {"SEVN_WHISPER_CPP_MODEL": str(model)}, clear=False),
    ):
        assert await WhisperCppBackend().is_available() is True


@pytest.mark.asyncio
async def test_whisper_cpp_is_available_false_when_binary_missing(tmp_path: Path) -> None:
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"weights")
    with (
        patch("sevn.voice.backends.shutil.which", return_value=None),
        patch.dict(os.environ, {"SEVN_WHISPER_CPP_MODEL": str(model)}, clear=False),
    ):
        assert await WhisperCppBackend().is_available() is False


@pytest.mark.asyncio
async def test_whisper_cpp_transcribe_returns_nonempty_result(tmp_path: Path) -> None:
    """``transcribe`` mocks the whisper.cpp subprocess — no real binary/model required."""
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"weights")
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF....WAVEfmt ")
    out_txt = tmp_path / "clip.wav.txt"
    out_txt.write_text("hello from whisper", encoding="utf-8")

    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))

    with (
        patch("sevn.voice.backends.shutil.which", return_value="/usr/local/bin/whisper-cpp"),
        patch.dict(os.environ, {"SEVN_WHISPER_CPP_MODEL": str(model)}, clear=False),
        patch("sevn.voice.backends.asyncio.create_subprocess_exec", return_value=proc),
    ):
        result = await WhisperCppBackend().transcribe(
            audio_path=audio,
            mime_type="audio/wav",
            duration_s=1.5,
        )
    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello from whisper"
    assert result.provider == "whisper_cpp"


@pytest.mark.asyncio
async def test_whisper_cpp_transcribe_reads_wav_txt_sidecar(tmp_path: Path) -> None:
    """After ffmpeg conversion, whisper.cpp writes ``{input}.txt`` (e.g. ``clip.wav.txt``)."""
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"weights")
    audio = tmp_path / "clip.ogg"
    audio.write_bytes(b"OggS")
    converted = tmp_path / "clip.wav"
    converted.write_bytes(b"RIFF....WAVEfmt ")
    sidecar = Path(str(converted) + ".txt")
    sidecar.write_text("converted transcript", encoding="utf-8")

    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))

    async def _fake_convert(path: Path) -> tuple[Path, Path | None]:
        return converted, converted

    with (
        patch("sevn.voice.backends.shutil.which", return_value="/usr/local/bin/whisper-cpp"),
        patch.dict(os.environ, {"SEVN_WHISPER_CPP_MODEL": str(model)}, clear=False),
        patch("sevn.voice.backends.asyncio.create_subprocess_exec", return_value=proc),
        patch("sevn.voice.backends._maybe_convert_audio_for_whisper", side_effect=_fake_convert),
    ):
        result = await WhisperCppBackend().transcribe(
            audio_path=audio,
            mime_type="audio/ogg",
            duration_s=1.5,
        )
    assert result.text == "converted transcript"


@pytest.mark.asyncio
async def test_whisper_cpp_transcribe_fails_gracefully_when_model_absent(tmp_path: Path) -> None:
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x")
    with (
        patch("sevn.voice.backends.shutil.which", return_value="/usr/local/bin/whisper-cpp"),
        patch.dict(os.environ, {"SEVN_WHISPER_CPP_MODEL": ""}, clear=False),
        pytest.raises(RuntimeError, match="SEVN_WHISPER_CPP_MODEL"),
    ):
        await WhisperCppBackend().transcribe(audio_path=audio, mime_type=None, duration_s=None)


def test_whisper_model_provisioner_idempotent(tmp_path: Path) -> None:
    """W2 provisioner (mirrors pyclaww ``download_model.py``) must be idempotent.

    The provisioner module does not exist until Wave W2 lands, so this is
    guarded with ``importorskip`` rather than a static import — collection
    must stay green even though the behavior is not implemented yet.
    """
    provisioner = pytest.importorskip("sevn.voice.whisper_model_provisioner")
    cache_dir = tmp_path / "voice-models"
    first = provisioner.ensure_whisper_model(model="base", cache_dir=cache_dir)
    second = provisioner.ensure_whisper_model(model="base", cache_dir=cache_dir)
    assert first == second


# --- W1.2: STT pipeline with whisper_cpp available ------------------------------


class _FakeWhisperCppOk:
    id = "whisper_cpp"

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
        return TranscriptionResult(text="turn the lights on", provider=self.id, confidence=0.92)


@pytest.mark.asyncio
async def test_stt_pipeline_returns_real_text_with_whisper_cpp_available(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "note.ogg"
    audio.write_bytes(b"x")
    sink = _RecordingTraceSink()
    pipe = SpeechToTextPipeline(
        [_FakeWhisperCppOk()],
        stt_confidence_reprompt_threshold=0.5,
        trace=sink,
    )
    text, meta = await pipe.transcribe_or_placeholder(
        audio_path=audio,
        mime_type="audio/ogg",
        duration_s=2.0,
        session_id="s",
        turn_id="t",
    )
    assert text != PLACEHOLDER_LLM_LINE
    assert text == "turn the lights on"
    assert meta["stt_provider"] == "whisper_cpp"
    kinds = [e.kind for e in sink.events]
    assert "voice.stt.exhausted" not in kinds
    assert "voice.stt.success" in kinds


# --- W1.3: Kokoro warmup + TTS dispatch-timeout margin; clear D3 errors --------


def test_tts_tool_has_dispatch_timeout_margin_for_kokoro_cold_start() -> None:
    """The ``tts`` tool must declare a dispatch timeout >= Kokoro's cold-start budget.

    Today ``tts`` has no override (``dispatch_timeout_seconds == "inherit"``, i.e. the
    generic 30s default), which is exactly the ``TOOL_TIMEOUT`` bug from the session log.
    """
    definition = tool_from_decorated(tts_tool).definition()
    timeout = definition.dispatch_timeout_seconds
    assert timeout is None or (isinstance(timeout, int | float) and timeout >= 60.0), (
        f"tts dispatch_timeout_seconds={timeout!r} does not cover a Kokoro cold start"
    )


@pytest.mark.asyncio
async def test_http_closed_tts_backend_surfaces_clear_error_when_unavailable() -> None:
    """D3: an unavailable cloud/edge backend must fail with a clear, specific message."""
    backend = _HttpClosedTTSBackend("openai_tts")
    with pytest.raises(RuntimeError, match="openai_tts is not available"):
        await backend.synthesize(text="hi", voice_id=None, out_path=Path("/tmp/w1_tts.bin"))


@pytest.mark.asyncio
async def test_tts_tool_exhausted_chain_names_the_reason_not_generic(tmp_path: Path) -> None:
    """D3: chain exhaustion must surface *why*, not a generic internal error."""
    pipeline = TextToSpeechPipeline(
        (_HttpClosedTTSBackend("openai_tts"),),
        voice_trigger_keywords=(),
        trace=None,
        tts_output_dir=tmp_path / "tts",
    )
    ctx = ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        tts_pipeline=pipeline,
    )
    raw = await tts_tool(ctx, text="hello there")
    import json

    blob = json.loads(raw)
    assert blob["ok"] is False
    message = str(blob.get("error") or "")
    assert "openai_tts" in message or "unavailable" in message.lower(), (
        f"expected a specific unavailable-backend reason, got: {message!r}"
    )
