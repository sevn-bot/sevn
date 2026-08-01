"""Injectable and live microphone frame sources for wake-word capture.

Module: sevn.voice.frame_sources
Depends: optional ``sounddevice`` (``voice-wake`` extra)

Exports:
    LiveMicFrameSource — lifespan-managed input stream (D24: only when enabled).
    build_live_frame_source — construct a mic source when hardware is present.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

from sevn.voice.capture_prerequisites import has_input_device

_DEFAULT_SAMPLE_RATE = 16000
_DEFAULT_BLOCK_SAMPLES = 1280


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

        def _enqueue(pcm: bytes) -> None:
            if queue.full():
                with suppress(asyncio.QueueFull):
                    queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(pcm)

        def _callback(indata: object, _frames: int, _time: object, status: object) -> None:
            _ = status
            if self._stop.is_set():
                return
            import numpy as np

            arr = np.asarray(indata, dtype=np.int16)
            loop.call_soon_threadsafe(_enqueue, arr.tobytes())

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
    if not has_input_device():
        return None
    try:
        import sounddevice  # noqa: F401
    except ImportError:
        return None
    return LiveMicFrameSource()


__all__ = ["LiveMicFrameSource", "build_live_frame_source"]
