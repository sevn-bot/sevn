"""Offline wake-word scoring (openWakeWord, Apache-2.0 — D23).

Module: sevn.voice.wake_engine
Depends: optional ``openwakeword`` (``voice-wake`` extra)

Exports:
    NullWakeWordEngine — never triggers (missing extra / unsupported engine id).
    WakeWordEngine — protocol for frame scoring.
    build_wake_word_engine — factory keyed on ``voice.activation.engine``.
"""

from __future__ import annotations

from typing import Protocol

from sevn.config.defaults import DEFAULT_VOICE_ACTIVATION_ENGINE


class WakeWordEngine(Protocol):
    """Score PCM frames for wake-word activation without network I/O."""

    def reset(self) -> None:
        """Clear internal audio state between activations.

        Examples:
            >>> NullWakeWordEngine().reset() is None
            True
        """
        ...

    def score_frame(self, frame: bytes, *, sample_rate: int = 16000) -> float:
        """Return a wake-word confidence in ``[0, 1]`` for one PCM chunk.

        Args:
            frame (bytes): Mono 16-bit PCM chunk.
            sample_rate (int): Sample rate in Hz.

        Returns:
            float: Confidence score.

        Examples:
            >>> NullWakeWordEngine().score_frame(b"\\x00\\x00")
            0.0
        """
        ...

    def is_triggered(self, score: float) -> bool:
        """Return whether ``score`` crosses the engine threshold.

        Args:
            score (float): Confidence from :meth:`score_frame`.

        Returns:
            bool: ``True`` when activation should start.

        Examples:
            >>> NullWakeWordEngine().is_triggered(0.99)
            False
        """
        ...


class NullWakeWordEngine:
    """Fallback when the optional extra or engine id is unavailable."""

    def reset(self) -> None:
        """No-op reset for the null engine.

        Examples:
            >>> NullWakeWordEngine().reset() is None
            True
        """
        return

    def score_frame(self, frame: bytes, *, sample_rate: int = 16000) -> float:
        """Always return zero — engine unavailable.

        Args:
            frame (bytes): Mono PCM chunk (ignored).
            sample_rate (int): Sample rate in Hz (ignored).

        Returns:
            float: Always ``0.0``.

        Examples:
            >>> NullWakeWordEngine().score_frame(b"\\x00")
            0.0
        """
        _ = frame, sample_rate
        return 0.0

    def is_triggered(self, score: float) -> bool:
        """Never trigger activation.

        Args:
            score (float): Confidence score (ignored).

        Returns:
            bool: Always ``False``.

        Examples:
            >>> NullWakeWordEngine().is_triggered(0.99)
            False
        """
        _ = score
        return False


def build_wake_word_engine(*, wake_word: str, engine_id: str | None = None) -> WakeWordEngine:
    """Instantiate the configured offline detector (D23: default openWakeWord).

    Args:
        wake_word (str): Operator-configured phrase (model selection may refine in W38).
        engine_id (str | None): ``voice.activation.engine`` value.

    Returns:
        WakeWordEngine: Scoring engine, or :class:`NullWakeWordEngine` when unavailable.

    Examples:
        >>> eng = build_wake_word_engine(wake_word="hey sevn")
        >>> eng.is_triggered(0.0)
        False
    """
    chosen = (engine_id or DEFAULT_VOICE_ACTIVATION_ENGINE).strip().casefold()
    if chosen != "openwakeword":
        return NullWakeWordEngine()
    try:
        from sevn.voice._openwakeword_engine import OpenWakeWordEngine, WakeModelLoadError

        return OpenWakeWordEngine(wake_word=wake_word)
    except (ImportError, WakeModelLoadError):
        return NullWakeWordEngine()


__all__ = [
    "NullWakeWordEngine",
    "WakeWordEngine",
    "build_wake_word_engine",
]
