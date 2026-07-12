"""Text-to-speech pipeline (`specs/20-voice.md` §2, §4, §6).
Module: sevn.voice.tts
Depends: sevn.voice.backends, sevn.voice.trace_events
Exports:
    TextToSpeechBackend — protocol implemented by registry entries.
    TextToSpeechPipeline — ordered chain with gating and skip tracing.
    TtsSynthOutcome — per-call synthesize result with optional exhaustion detail.
    speak_placeholder — legacy no-op hook for scaffold tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from loguru import logger

from sevn.agent.tracing.sink import TraceSink
from sevn.voice.backends import SynthesisResult
from sevn.voice.keywords import user_text_matches_voice_trigger
from sevn.voice.trace_events import emit_voice_event

_OPUS_TRANSCODE_TIMEOUT_S = 60.0


async def _ensure_telegram_opus(path: Path) -> None:
    """Re-encode a synthesized audio file in place to OGG/Opus for cross-client playback.

    Telegram voice notes (``sendVoice``) require an OGG container with the **Opus** codec.
    Local TTS backends emit other encodings — Kokoro writes OGG/**Vorbis** via ``soundfile``,
    edge/openai emit MP3 — which the Telegram *desktop* client tolerantly probes and plays but
    the *mobile* client silently refuses (the note shows but produces no sound). Transcode to
    mono 48 kHz Opus with ffmpeg so the note plays on every client.

    Best-effort: a no-op when ffmpeg is absent and a silent leave-as-is on any failure, so a
    voice reply is never lost to this step (the original file still uploads).

    Args:
        path (Path): Synthesized audio file, rewritten in place on success.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> asyncio.run(_ensure_telegram_opus(Path("/nonexistent/x.ogg"))) is None
        True
    """
    if shutil.which("ffmpeg") is None or not path.is_file():
        return
    tmp = path.with_name(f"{path.stem}.opus{path.suffix}")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-ar",
        "48000",
        "-ac",
        "1",
        "-f",
        "ogg",
        str(tmp),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=_OPUS_TRANSCODE_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        with contextlib.suppress(OSError):
            tmp.unlink()
        logger.warning("voice_tts_opus_transcode_timeout path={}", path)
        return
    if proc.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
        with contextlib.suppress(OSError):
            tmp.replace(path)
        return
    with contextlib.suppress(OSError):
        tmp.unlink()
    logger.warning("voice_tts_opus_transcode_failed rc={} path={}", proc.returncode, path)


@runtime_checkable
class TextToSpeechBackend(Protocol):
    """One TTS implementation (`specs/20-voice.md` §2.2)."""

    id: str

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        """Write audio bytes to ``out_path``.
        Args:
            text (str): Assistant reply to encode.
            voice_id (str | None): Provider voice id.
            out_path (Path): Destination media path.
        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> class B:
            ...     id = "x"
            ...     async def synthesize(self, *, text, voice_id, out_path):
            ...         out_path.write_bytes(b"")
            ...     async def is_available(self):
            ...         return True
            >>> p = Path("/tmp/tts_doc.bin")
            >>> asyncio.run(B().synthesize(text="a", voice_id=None, out_path=p)) is None
            True
        """
        ...

    async def is_available(self) -> bool:
        """Cheap availability probe.
        Returns:
            bool: Whether this backend should run.
        Examples:
            >>> import asyncio
            >>> class B:
            ...     id = "x"
            ...     async def synthesize(self, *, text, voice_id, out_path):
            ...         pass
            ...     async def is_available(self):
            ...         return False
            >>> asyncio.run(B().is_available())
            False
        """
        ...


@dataclass(frozen=True)
class TtsSynthOutcome:
    """Result of :meth:`TextToSpeechPipeline.synthesize_or_skip`."""

    result: SynthesisResult | None
    exhaustion_detail: str | None = None


class TextToSpeechPipeline:
    """Ordered TTS chain with ``tts_mode`` + keyword gating."""

    def __init__(
        self,
        backends: Sequence[TextToSpeechBackend],
        *,
        voice_trigger_keywords: tuple[str, ...],
        trace: TraceSink | None,
        tts_output_dir: Path,
        default_mime: str = "audio/ogg",
    ) -> None:
        """Store backends, gating keywords, trace handle, and output directory.
        Args:
            backends (Sequence[TextToSpeechBackend]): Candidate backends.
            voice_trigger_keywords (tuple[str, ...]): Words for ``when_asked`` mode.
            trace (TraceSink | None): Trace sink.
            tts_output_dir (Path): Temp/output directory for encoded media.
            default_mime (str): MIME type recorded on success.
        Examples:
            >>> from pathlib import Path
            >>> from sevn.voice.tts import TextToSpeechPipeline
            >>> TextToSpeechPipeline(
            ...     (), voice_trigger_keywords=(), trace=None, tts_output_dir=Path("/tmp")
            ... )._default_mime
            'audio/ogg'
        """
        self._backends = tuple(backends)
        self._keywords = tuple(k.casefold() for k in voice_trigger_keywords if k.strip())
        self._trace = trace
        self._out_dir = tts_output_dir
        self._default_mime = default_mime

    def should_synthesize(
        self,
        *,
        session_tts_mode: str,
        user_text_last_turn: str,
        inbound_voice_attachment: bool = False,
    ) -> bool:
        """Return whether TTS should run for this reply (`specs/20-voice.md` §4.1).
        ``when_asked`` matches configured keywords at **Unicode word boundaries**
        (``sevn.voice.keywords``; not ASCII ``\\b``) over case-folded user text, or
        when the inbound turn included a voice note (D5).
        Args:
            session_tts_mode (str): ``off``, ``all``, or ``when_asked``.
            user_text_last_turn (str): Latest user-visible text for the session.
            inbound_voice_attachment (bool): Whether this turn included voice/audio.
        Returns:
            bool: ``True`` when the outbound chain should run.
        Examples:
            >>> p = TextToSpeechPipeline((), voice_trigger_keywords=("speak",), trace=None,
            ...     tts_output_dir=Path("."))
            >>> p.should_synthesize(session_tts_mode="off", user_text_last_turn="speak hi")
            False
            >>> p.should_synthesize(session_tts_mode="when_asked", user_text_last_turn="SPEAK hi")
            True
        """
        mode = (session_tts_mode or "off").strip().casefold()
        if mode == "off":
            return False
        if mode == "all":
            return True
        if mode != "when_asked":
            return False
        if inbound_voice_attachment:
            return True
        return user_text_matches_voice_trigger(
            user_text=user_text_last_turn or "",
            keywords=self._keywords,
        )

    async def synthesize_or_skip(
        self,
        *,
        cleaned_assistant_text: str,
        voice_id: str | None,
        session_id: str,
        turn_id: str,
    ) -> TtsSynthOutcome:
        """Run the TTS chain or return a skip/exhaustion outcome.
        Args:
            cleaned_assistant_text (str): Assistant reply text.
            voice_id (str | None): Voice override from config.
            session_id (str): Gateway session id.
            turn_id (str): Correlation id for traces.
        Returns:
            TtsSynthOutcome: Artefact metadata or skip/exhaustion details.
        Examples:
            >>> import asyncio
            >>> from sevn.voice.tts import TextToSpeechPipeline
            >>> from pathlib import Path
            >>> async def _run():
            ...     p = TextToSpeechPipeline(
            ...         (), voice_trigger_keywords=(), trace=None, tts_output_dir=Path("/tmp"))
            ...     return await p.synthesize_or_skip(
            ...         cleaned_assistant_text="",
            ...         voice_id=None,
            ...         session_id="s",
            ...         turn_id="t",
            ...     )
            >>> asyncio.run(_run()).result is None
            True
        """
        text = (cleaned_assistant_text or "").strip()
        if not text:
            await emit_voice_event(
                self._trace,
                kind="voice.tts.skipped",
                session_id=session_id,
                turn_id=turn_id,
                status="empty_text",
                attrs={},
            )
            return TtsSynthOutcome(None)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        await emit_voice_event(
            self._trace,
            kind="voice.tts.start",
            session_id=session_id,
            turn_id=turn_id,
            status="started",
            attrs={"backend_id": ",".join(b.id for b in self._backends) or "none"},
        )
        prev_attempted: str | None = None
        last_error_class: str | None = None
        unavailable_ids: list[str] = []
        for backend in self._backends:
            if not await backend.is_available():
                unavailable_ids.append(backend.id)
                continue
            if last_error_class is not None and prev_attempted is not None:
                await emit_voice_event(
                    self._trace,
                    kind="voice.tts.fallback",
                    session_id=session_id,
                    turn_id=turn_id,
                    status="retry",
                    attrs={
                        "from_id": prev_attempted,
                        "to_id": backend.id,
                        "error_class": last_error_class,
                    },
                )
                last_error_class = None
            session_dir = self._out_dir / session_id if session_id.strip() else self._out_dir
            session_dir.mkdir(parents=True, exist_ok=True)
            out_path = session_dir / f"{uuid.uuid4().hex}.ogg"
            try:
                await backend.synthesize(text=text, voice_id=voice_id, out_path=out_path)
            except Exception as exc:
                prev_attempted = backend.id
                last_error_class = type(exc).__name__
                if out_path.exists():
                    with contextlib.suppress(OSError):
                        out_path.unlink()
                continue
            if not out_path.is_file() or out_path.stat().st_size == 0:
                prev_attempted = backend.id
                last_error_class = "EmptyAudio"
                with contextlib.suppress(OSError):
                    out_path.unlink()
                continue
            await _ensure_telegram_opus(out_path)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await emit_voice_event(
                self._trace,
                kind="voice.tts.success",
                session_id=session_id,
                turn_id=turn_id,
                status="ok",
                attrs={
                    "backend_id": backend.id,
                    "duration_ms": elapsed_ms,
                    "audio_bytes": out_path.stat().st_size,
                },
            )
            return TtsSynthOutcome(
                SynthesisResult(
                    path=out_path,
                    mime_type=self._default_mime,
                    provider=backend.id,
                )
            )
        detail_parts: list[str] = []
        if prev_attempted is not None and last_error_class is not None:
            detail_parts.append(f"{prev_attempted} failed ({last_error_class})")
        if unavailable_ids:
            detail_parts.append(f"unavailable: {', '.join(unavailable_ids)}")
        exhaustion_detail = "; ".join(detail_parts) or None
        await emit_voice_event(
            self._trace,
            kind="voice.tts.exhausted",
            session_id=session_id,
            turn_id=turn_id,
            status="failed",
            attrs={"detail": exhaustion_detail or ""},
        )
        logger.warning(
            "voice TTS chain exhausted for session_id={} detail={}",
            session_id,
            exhaustion_detail,
        )
        return TtsSynthOutcome(None, exhaustion_detail)


async def speak_placeholder(*, text: str, session_channel: str) -> None:
    """No-op TTS hook retained for early gateway tests (`specs/20-voice.md`).
    Args:
        text (str): Assistant text (ignored).
        session_channel (str): Adapter key (ignored).
    Returns:
        None: Always.
    Examples:
        >>> import asyncio
        >>> asyncio.run(speak_placeholder(text="hi", session_channel="telegram")) is None
        True
    """
    _ = text, session_channel
    return
