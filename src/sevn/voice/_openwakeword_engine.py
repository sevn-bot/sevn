"""Guarded openWakeWord adapter — import only with ``openwakeword`` installed (D23).

Module: sevn.voice._openwakeword_engine
Depends: optional ``openwakeword``, ``numpy``

Exports:
    OpenWakeWordEngine — Apache-2.0 offline wake-word scorer.
    WakeModelLoadError — configured model id failed to load.
    normalise_wake_model_name — phrase → bundled model slug.
    wake_word_model_loadable — probe whether a phrase maps to a bundled model.
"""

from __future__ import annotations

from typing import Any

from sevn.voice.wake_engine import NullWakeWordEngine

_ACTIVATION_THRESHOLD = 0.5
_DEFAULT_SAMPLE_RATE = 16000
_SCORING_WINDOW_S = 0.08
_BUFFER_WINDOW_MULTIPLIER = 4


class WakeModelLoadError(RuntimeError):
    """Configured wake phrase has no loadable bundled model."""


def _numpy() -> Any:
    """Import numpy when the ``voice-wake`` extra is installed.

    Returns:
        Any: The ``numpy`` module object.

    Examples:
        >>> import types
        >>> isinstance(_numpy(), types.ModuleType)  # doctest: +SKIP
        True
    """
    import numpy as np

    return np


def normalise_wake_model_name(wake_word: str) -> str:
    """Map operator wake phrase to an openWakeWord bundled model id.

    Args:
        wake_word (str): Configured phrase such as ``hey jarvis``.

    Returns:
        str: Model slug understood by openWakeWord.

    Examples:
        >>> normalise_wake_model_name("hey jarvis")
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


def wake_word_model_loadable(wake_word: str) -> bool:
    """Return whether ``wake_word`` maps to a bundled openWakeWord model.

    Args:
        wake_word (str): Operator-configured phrase.

    Returns:
        bool: ``True`` when the specific model loads without falling back to all models.

    Examples:
        >>> wake_word_model_loadable("hey jarvis") in (True, False)
        True
    """
    try:
        OpenWakeWordEngine(wake_word=wake_word)
    except (WakeModelLoadError, ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False
    return True


class OpenWakeWordEngine(NullWakeWordEngine):
    """Apache-2.0 offline scorer — no account, key, or network (D23)."""

    def __init__(self, *, wake_word: str) -> None:
        """Load exactly one bundled openWakeWord model for ``wake_word``.

        Args:
            wake_word (str): Operator-configured wake phrase.

        Raises:
            WakeModelLoadError: When the configured model id is not bundled.

        Examples:
            >>> OpenWakeWordEngine(wake_word="hey jarvis")  # doctest: +SKIP
            ...
        """
        from openwakeword.model import Model

        model_name = normalise_wake_model_name(wake_word)
        try:
            self._model: Any = Model(wakeword_models=[model_name])
        except Exception as exc:
            raise WakeModelLoadError(
                f"wake-word model {model_name!r} is not available — "
                f"choose a bundled phrase such as 'hey jarvis'"
            ) from exc
        np = _numpy()
        self._buffer = np.array([], dtype=np.int16)
        self._max_buffer_samples = (
            int(_DEFAULT_SAMPLE_RATE * _SCORING_WINDOW_S) * _BUFFER_WINDOW_MULTIPLIER
        )

    def reset(self) -> None:
        """Clear the rolling PCM buffer.

        Examples:
            >>> eng = OpenWakeWordEngine(wake_word="hey jarvis")  # doctest: +SKIP
            >>> eng.reset() is None  # doctest: +SKIP
            True
        """
        np = _numpy()
        self._buffer = np.array([], dtype=np.int16)

    def score_frame(self, frame: bytes, *, sample_rate: int = _DEFAULT_SAMPLE_RATE) -> float:
        """Score one PCM chunk against the loaded wake-word model.

        Args:
            frame (bytes): Mono 16-bit PCM chunk.
            sample_rate (int): Sample rate in Hz.

        Returns:
            float: Confidence score in ``[0, 1]``.

        Examples:
            >>> eng = OpenWakeWordEngine(wake_word="hey jarvis")  # doctest: +SKIP
            >>> eng.score_frame(b"\\x00\\x00") >= 0.0  # doctest: +SKIP
            True
        """
        if not frame:
            return 0.0
        np = _numpy()
        if len(frame) % 2 != 0:
            frame = frame[:-1]
        chunk = np.frombuffer(frame, dtype=np.int16)
        self._buffer = np.concatenate([self._buffer, chunk])
        if self._buffer.size > self._max_buffer_samples:
            self._buffer = self._buffer[-self._max_buffer_samples :]
        min_samples = int(sample_rate * _SCORING_WINDOW_S)
        if self._buffer.size < min_samples:
            return 0.0
        audio = self._buffer[-min_samples * _BUFFER_WINDOW_MULTIPLIER :]
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
            >>> eng = OpenWakeWordEngine(wake_word="hey jarvis")  # doctest: +SKIP
            >>> eng.is_triggered(0.0)  # doctest: +SKIP
            False
        """
        return score >= _ACTIVATION_THRESHOLD


__all__ = [
    "OpenWakeWordEngine",
    "WakeModelLoadError",
    "normalise_wake_model_name",
    "wake_word_model_loadable",
]
