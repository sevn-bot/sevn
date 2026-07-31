"""Injectable and live microphone frame sources for wake-word capture.

Module: sevn.voice.frame_sources
Depends: optional ``sounddevice`` (``voice-wake`` extra)

Exports:
    LiveMicFrameSource — lifespan-managed input stream (D24: only when enabled).
    build_live_frame_source — construct a mic source when hardware is present.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from collections.abc import AsyncIterator

from sevn.config.defaults import VOICE_WAKE_ENGINE_MODULE

_DEFAULT_SAMPLE_RATE = 16000
_DEFAULT_BLOCK_SAMPLES = 1280


def _voice_wake_extra_installed() -> bool:
    """Return whether the wake-word engine module is importable.

    Returns:
        bool: ``True`` when ``openwakeword`` is importable.

    Examples:
        >>> isinstance(_voice_wake_extra_installed(), bool)
        True
    """
    return importlib.util.find_spec(VOICE_WAKE_ENGINE_MODULE) is not None


def _activation_supported_platform() -> bool:
    """Return whether this host may run wake-word capture.

    Returns:
        bool: ``False`` for unsupported OS, Docker, or headless env.

    Examples:
        >>> isinstance(_activation_supported_platform(), bool)
        True
    """
    if sys.platform not in ("darwin", "linux"):
        return False
    if os.path.exists("/.dockerenv"):
        return False
    return os.environ.get("SEVN_HEADLESS", "").strip() not in {"1", "true", "yes"}


def _has_input_device() -> bool:
    """Probe input devices via ``sounddevice`` without opening a stream.

    Returns:
        bool: ``True`` when at least one input channel exists.

    Examples:
        >>> _has_input_device() in (True, False)
        True
    """
    if not _activation_supported_platform() or not _voice_wake_extra_installed():
        return False
    try:
        import sounddevice as sd
    except ImportError:
        return False
    try:
        devices = sd.query_devices()
        if isinstance(devices, dict):
            return int(devices.get("max_input_channels") or 0) > 0
        return any(int(d.get("max_input_channels") or 0) > 0 for d in devices)
    except Exception:
        return False


class LiveMicFrameSource:
    """sounddevice-backed mic reader — never constructed unless activation is available."""

    def __init__(
        self,
        *,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        block_samples: int = _DEFAULT_BLOCK_SAMPLES,
    ) -> None:
        """Configure sample rate and block size for the input stream.

        Args:
            sample_rate (int): PCM sample rate in Hz.
            block_samples (int): Frames per callback block.

        Examples:
            >>> LiveMicFrameSource(sample_rate=16000)._sample_rate
            16000
        """
        self._sample_rate = sample_rate
        self._block_samples = block_samples
        self._stop = asyncio.Event()
        self.opened = False

    def request_stop(self) -> None:
        """Signal ``read_frames`` to exit.

        Examples:
            >>> src = LiveMicFrameSource()
            >>> src.request_stop() is None
            True
        """
        self._stop.set()

    async def read_frames(self) -> AsyncIterator[bytes]:
        """Yield PCM int16 frames until :meth:`request_stop` is called.

        Yields:
            bytes: One PCM frame per iteration.

        Returns:
            AsyncIterator[bytes]: Async generator of PCM frames.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LiveMicFrameSource.read_frames)
            False
        """
        import sounddevice as sd

        self.opened = True
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=8)

        def _callback(indata: object, _frames: int, _time: object, status: object) -> None:
            _ = status
            if self._stop.is_set():
                return
            import numpy as np

            arr = np.asarray(indata, dtype=np.int16)
            pcm = arr.tobytes()
            loop.call_soon_threadsafe(queue.put_nowait, pcm)

        stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._block_samples,
            callback=_callback,
        )
        with stream:
            while not self._stop.is_set():
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=0.5)
                except TimeoutError:
                    continue
                if frame is None:
                    break
                yield frame


def build_live_frame_source() -> LiveMicFrameSource | None:
    """Return a live mic source when the extra is installed and input exists (D25).

    Returns:
        LiveMicFrameSource | None: ``None`` when capture must not start.

    Examples:
        >>> build_live_frame_source() is None or isinstance(build_live_frame_source(), LiveMicFrameSource)
        True
    """
    if not _has_input_device():
        return None
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        return None
    return LiveMicFrameSource()


__all__ = ["LiveMicFrameSource", "build_live_frame_source"]
