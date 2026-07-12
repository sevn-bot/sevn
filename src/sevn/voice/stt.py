"""Speech-to-text pipeline (`specs/20-voice.md` §2, §4, §6).
Module: sevn.voice.stt
Depends: sevn.voice.backends, sevn.voice.trace_events
Exports:
    SpeechToTextBackend — protocol implemented by registry entries.
    SpeechToTextPipeline — ordered chain with placeholder fallback.
    transcribe_placeholder — legacy no-op hook for scaffold tests.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from loguru import logger

from sevn.agent.tracing.sink import TraceSink
from sevn.voice.backends import TranscriptionResult
from sevn.voice.trace_events import emit_voice_event

# PRD 05 §5.8 — must match verbatim (`specs/20-voice.md` §6).
PLACEHOLDER_LLM_LINE = (
    "[Voice message received but transcription unavailable. "
    "Respond naturally based on conversation context. "
    "Do NOT try to transcribe or read the audio file.]"
)


@runtime_checkable
class SpeechToTextBackend(Protocol):
    """One STT implementation (`specs/20-voice.md` §2.2)."""

    id: str

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        """Return a non-empty transcript on success.
        Args:
            audio_path (Path): Input audio path.
            mime_type (str | None): MIME hint.
            duration_s (float | None): Duration seconds, if known.
            locale (str | None): Optional locale hint.
        Returns:
            TranscriptionResult: Parsed transcript payload.
        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> from sevn.voice.backends import TranscriptionResult
            >>> class B:
            ...     id = "x"
            ...     async def transcribe(self, *, audio_path, mime_type, duration_s, locale=None):
            ...         return TranscriptionResult(text="z", provider=self.id)
            ...     async def is_available(self):
            ...         return True
            >>> asyncio.run(B().transcribe(
            ...     audio_path=Path("/a"), mime_type=None, duration_s=None)).text
            'z'
        """
        ...

    async def is_available(self) -> bool:
        """Cheap availability probe.
        Returns:
            bool: Whether this backend should run.
        Examples:
            >>> import asyncio
            >>> from sevn.voice.backends import TranscriptionResult
            >>> class B:
            ...     id = "x"
            ...     async def transcribe(self, *, audio_path, mime_type, duration_s, locale=None):
            ...         return TranscriptionResult(text="z", provider=self.id)
            ...     async def is_available(self):
            ...         return True
            >>> asyncio.run(B().is_available())
            True
        """
        ...


class SpeechToTextPipeline:
    """Ordered STT chain with caps-aware callers and tracing hooks."""

    PLACEHOLDER_LLM_LINE = PLACEHOLDER_LLM_LINE

    def __init__(
        self,
        backends: Sequence[SpeechToTextBackend],
        *,
        stt_confidence_reprompt_threshold: float,
        trace: TraceSink | None,
    ) -> None:
        """Store ordered backends and trace handle for the STT chain.
        Args:
            backends (Sequence[SpeechToTextBackend]): Candidate backends.
            stt_confidence_reprompt_threshold (float): Low-confidence warn threshold.
            trace (TraceSink | None): Trace sink.
        Returns:
            None: Always.
        Examples:
            >>> from sevn.voice.stt import SpeechToTextPipeline
            >>> SpeechToTextPipeline(
            ...     (), stt_confidence_reprompt_threshold=0.4, trace=None
            ... )._threshold
            0.4
        """
        self._backends = tuple(backends)
        self._threshold = stt_confidence_reprompt_threshold
        self._trace = trace

    async def transcribe_or_placeholder(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        session_id: str,
        turn_id: str,
        locale: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Return LLM-visible text plus attachment metadata updates.
        Args:
            audio_path (Path): On-disk audio from :class:`~sevn.gateway.media_store.MediaStore`.
            mime_type (str | None): MIME hint from the adapter.
            duration_s (float | None): Known duration in seconds, if any.
            session_id (str): Gateway session id for traces.
            turn_id (str): Correlation id for traces.
            locale (str | None): Optional BCP-47 locale hint.
        Returns:
            tuple[str, dict[str, Any]]: ``(text_for_llm, attachment_metadata_updates)``.
        Examples:
            >>> import asyncio
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.voice.stt import SpeechToTextPipeline
            >>> af = Path(tempfile.mkdtemp()) / "a.bin"
            >>> _ = af.write_bytes(b"x")
            >>> async def _run():
            ...     p = SpeechToTextPipeline(
            ...         (), stt_confidence_reprompt_threshold=0.5, trace=None)
            ...     return await p.transcribe_or_placeholder(
            ...         audio_path=af,
            ...         mime_type=None,
            ...         duration_s=None,
            ...         session_id="s",
            ...         turn_id="t",
            ...     )
            >>> text, meta = asyncio.run(_run())
            >>> meta["stt_provider"]
            'placeholder'
        """
        started = time.perf_counter()
        audio_bytes = 0
        try:
            audio_bytes = audio_path.stat().st_size
        except OSError:
            audio_bytes = 0
        await emit_voice_event(
            self._trace,
            kind="voice.stt.start",
            session_id=session_id,
            turn_id=turn_id,
            status="started",
            attrs={
                "backend_id": ",".join(b.id for b in self._backends) or "none",
                "audio_bytes": audio_bytes,
            },
        )
        prev_attempted: str | None = None
        last_error_class: str | None = None
        for backend in self._backends:
            if not await backend.is_available():
                continue
            if last_error_class is not None and prev_attempted is not None:
                await emit_voice_event(
                    self._trace,
                    kind="voice.stt.fallback",
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
            try:
                res = await backend.transcribe(
                    audio_path=audio_path,
                    mime_type=mime_type,
                    duration_s=duration_s,
                    locale=locale,
                )
            except Exception as exc:
                prev_attempted = backend.id
                last_error_class = type(exc).__name__
                continue
            text = (res.text or "").strip()
            if not text:
                prev_attempted = backend.id
                last_error_class = "EmptyTranscript"
                continue
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            await emit_voice_event(
                self._trace,
                kind="voice.stt.success",
                session_id=session_id,
                turn_id=turn_id,
                status="ok",
                attrs={
                    "backend_id": backend.id,
                    "duration_ms": elapsed_ms,
                    "audio_bytes": audio_bytes,
                    "confidence": res.confidence,
                },
            )
            low = res.confidence is not None and float(res.confidence) < float(self._threshold)
            if low:
                await emit_voice_event(
                    self._trace,
                    kind="voice.stt.low_confidence",
                    session_id=session_id,
                    turn_id=turn_id,
                    status="warn",
                    attrs={
                        "backend_id": backend.id,
                        "confidence": res.confidence,
                        "threshold": self._threshold,
                    },
                )
            meta: dict[str, Any] = {
                "transcript": text,
                "stt_provider": backend.id,
                "stt_confidence": res.confidence,
            }
            return text, meta
        await emit_voice_event(
            self._trace,
            kind="voice.stt.exhausted",
            session_id=session_id,
            turn_id=turn_id,
            status="failed",
            attrs={"audio_bytes": audio_bytes},
        )
        logger.warning("voice STT chain exhausted for session_id={}", session_id)
        return self.PLACEHOLDER_LLM_LINE, {
            "transcript": "",
            "stt_provider": "placeholder",
            "stt_confidence": None,
        }


async def transcribe_placeholder(
    *,
    channel: str,
    attachment_meta: dict[str, Any],
) -> str:
    """No-op STT hook retained for early gateway tests (`specs/20-voice.md`).
    Args:
        channel (str): Adapter key (ignored).
        attachment_meta (dict[str, Any]): Attachment row (ignored).
    Returns:
        str: Always empty — prefer :class:`SpeechToTextPipeline` in production.
    Examples:
        >>> import asyncio
        >>> asyncio.run(transcribe_placeholder(channel="x", attachment_meta={}))
        ''
    """
    _ = channel, attachment_meta
    return ""
