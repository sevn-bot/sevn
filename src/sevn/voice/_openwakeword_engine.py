"""Guarded openWakeWord adapter — import only with ``openwakeword`` installed (D23).

Module: sevn.voice._openwakeword_engine
Depends: optional ``openwakeword``, ``numpy``

Exports:
    OpenWakeWordEngine — Apache-2.0 offline wake-word scorer.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sevn.voice.wake_engine import NullWakeWordEngine

_ACTIVATION_THRESHOLD = 0.5
_DEFAULT_SAMPLE_RATE = 16000


def _normalise_wake_model_name(wake_word: str) -> str:
    """Map operator wake phrase to an openWakeWord bundled model id.

    Args:
        wake_word (str): Configured phrase such as ``hey sevn``.

    Returns:
        str: Model slug understood by openWakeWord.

    Examples:
        >>> _normalise_wake_model_name("hey jarvis")
        'hey_jarvis'
    """
    slug = "_".join(wake_word.strip().casefold().split())
    if not slug:
        return "hey_jarvis"
    known = {
        "hey jarvis": "hey_jarvis",
        "hey_jarvis": "hey_jarvis",
        "alexa": "alexa",
        "hey mycroft": "hey_mycroft",
        "hey_mycroft": "hey_mycroft",
    }
    return known.get(wake_word.strip().casefold(), slug.replace(" ", "_"))


class OpenWakeWordEngine(NullWakeWordEngine):
    """Apache-2.0 offline scorer — no account, key, or network (D23)."""

    def __init__(self, *, wake_word: str) -> None:
        """Load the bundled openWakeWord model closest to ``wake_word``.

        Args:
            wake_word (str): Operator-configured wake phrase.

        Examples:
            >>> isinstance(OpenWakeWordEngine(wake_word="hey jarvis"), OpenWakeWordEngine)
            True
        """
        from openwakeword.model import Model

        model_name = _normalise_wake_model_name(wake_word)
        try:
            self._model: Any = Model(wakeword_models=[model_name])
        except Exception:
            self._model = Model()
        self._buffer = np.array([], dtype=np.int16)

    def reset(self) -> None:
        """Clear the rolling PCM buffer.

        Examples:
            >>> eng = OpenWakeWordEngine(wake_word="hey jarvis")
            >>> eng.reset() is None
            True
        """
        self._buffer = np.array([], dtype=np.int16)

    def score_frame(self, frame: bytes, *, sample_rate: int = _DEFAULT_SAMPLE_RATE) -> float:
        """Score one PCM chunk against the loaded wake-word model.

        Args:
            frame (bytes): Mono 16-bit PCM chunk.
            sample_rate (int): Sample rate in Hz.

        Returns:
            float: Confidence score in ``[0, 1]``.

        Examples:
            >>> eng = OpenWakeWordEngine(wake_word="hey jarvis")
            >>> eng.score_frame(b"\\x00\\x00") >= 0.0
            True
        """
        if not frame:
            return 0.0
        if len(frame) % 2 != 0:
            frame = frame[:-1]
        chunk = np.frombuffer(frame, dtype=np.int16)
        self._buffer = np.concatenate([self._buffer, chunk])
        min_samples = int(sample_rate * 0.08)
        if self._buffer.size < min_samples:
            return 0.0
        audio = self._buffer[-min_samples * 4 :]
        try:
            scores = self._model.predict(audio)
        except Exception:
            return 0.0
        if not scores:
            return 0.0
        return float(max(scores.values()))

    def is_triggered(self, score: float) -> bool:
        """Return whether ``score`` crosses the activation threshold.

        Args:
            score (float): Confidence from :meth:`score_frame`.

        Returns:
            bool: ``True`` when activation should start.

        Examples:
            >>> eng = OpenWakeWordEngine(wake_word="hey jarvis")
            >>> eng.is_triggered(0.0)
            False
        """
        return score >= _ACTIVATION_THRESHOLD


__all__ = ["OpenWakeWordEngine"]
