"""Wake-word activation config, availability verdict, and lifespan listener (W36-W37).

Module: sevn.voice.activation
Depends: sevn.config, sevn.voice.factory, sevn.voice.frame_sources, sevn.voice.wake_engine

Exports:
    AudioFrameSource — injectable mic protocol for tests.
    VoiceActivationSettings — resolved activation state for doctor/CLI/gateway.
    WakeWordListener — capture + detection loop with STT hand-off.
    activation_config_key_paths — dotted config paths under ``voice.activation.*``.
    activation_supported_platform — host/container gate for capture (D25).
    build_wake_word_listener — factory when enabled and available.
    format_activation_status — plain-text activation status (W38).
    has_input_device — best-effort mic probe without opening a stream.
    maybe_start_wake_word_listener — gateway lifespan startup hook.
    maybe_stop_wake_word_listener — gateway lifespan shutdown hook.
    activation_status_payload — CLI/Telegram listening-state snapshot (W38).
    available_wake_word_models — engine-derived wake phrase choices (W38).
    probe_voice_activation — structured availability verdict (D25).
    resolve_listening_state — D24 three-way listening verdict (W38).
    resolve_voice_activation_settings — merge config with defaults.
    voice_activation_config_enabled — ``voice.activation.enabled`` alone.
    voice_activation_enabled — conjunctive ``voice.enabled`` + activation.
    voice_wake_extra_installed — optional extra import probe.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from sevn.config.defaults import (
    DEFAULT_VOICE_ACTIVATION_ENABLED,
    DEFAULT_VOICE_ACTIVATION_ENGINE,
    DEFAULT_VOICE_ACTIVATION_WAKE_WORD,
    VOICE_WAKE_ENGINE_MODULE,
    VOICE_WAKE_OPTIONAL_EXTRA,
)
from sevn.config.sections.channels import VoiceActivationConfig, VoiceConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.voice.factory import build_stt_pipeline, voice_enabled, voice_runtime_settings
from sevn.voice.frame_sources import build_live_frame_source
from sevn.voice.trace_events import emit_voice_event
from sevn.voice.wake_engine import WakeWordEngine, build_wake_word_engine

ListeningState = Literal["disabled", "enabled_listening", "enabled_unavailable"]

_ACTIVATION_CONFIG_PREFIX = "voice.activation"
_WAKE_SESSION_ID = "_wake_word"
_SAMPLE_RATE = 16000


class AudioFrameSource(Protocol):
    """Injectable mic stand-in for tests — production uses :class:`~sevn.voice.frame_sources.LiveMicFrameSource`."""

    def read_frames(self) -> AsyncIterator[bytes]:
        """Yield PCM frames until exhausted.

        Yields:
            bytes: One audio frame per iteration.

        Returns:
            AsyncIterator[bytes]: Async generator of PCM frames.

        Examples:
            >>> class _OneShot:
            ...     async def read_frames(self):
            ...         yield b"\\x00"
            >>> import asyncio
            >>> async def _first(source):
            ...     async for frame in source.read_frames():
            ...         return frame
            ...     return b""
            >>> asyncio.run(_first(_OneShot()))
            b'\\x00'
        """
        ...


@dataclass(frozen=True)
class VoiceActivationSettings:
    """Resolved activation state for CLI, doctor, and gateway lifespan."""

    enabled: bool
    listening: bool
    wake_word: str
    engine: str


def activation_config_key_paths() -> frozenset[str]:
    """Return dotted config paths owned by the activation subtree (D23 namespace).

    Returns:
        frozenset[str]: Keys under ``voice.activation.*`` (never ``*_trigger_keywords``).

    Examples:
        >>> "voice.activation.enabled" in activation_config_key_paths()
        True
    """
    return frozenset(
        {
            f"{_ACTIVATION_CONFIG_PREFIX}.enabled",
            f"{_ACTIVATION_CONFIG_PREFIX}.engine",
            f"{_ACTIVATION_CONFIG_PREFIX}.wake_word",
        },
    )


def _activation_cfg(voice: VoiceConfig | None) -> VoiceActivationConfig | None:
    """Return the typed ``voice.activation`` subtree when present.

    Args:
        voice (VoiceConfig | None): Parsed ``voice`` section.

    Returns:
        VoiceActivationConfig | None: Activation subtree or ``None``.

    Examples:
        >>> _activation_cfg(None) is None
        True
    """
    if voice is None:
        return None
    return voice.activation


def voice_activation_config_enabled(ws: WorkspaceConfig) -> bool:
    """Return whether ``voice.activation.enabled`` resolves true (ignores master voice gate).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        bool: ``True`` only when activation is explicitly enabled in config.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> voice_activation_config_enabled(WorkspaceConfig.minimal())
        False
    """
    act = _activation_cfg(ws.voice)
    if act is not None and act.enabled is not None:
        return bool(act.enabled)
    return bool(DEFAULT_VOICE_ACTIVATION_ENABLED)


def voice_activation_enabled(ws: WorkspaceConfig) -> bool:
    """Conjunctive gate: master ``voice.enabled`` **and** activation enabled (W36.4).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        bool: ``True`` only when both voice and activation are enabled.

    Examples:
        >>> from sevn.config.sections.channels import VoiceConfig
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> voice_activation_enabled(
        ...     WorkspaceConfig.minimal(
        ...         voice=VoiceConfig(enabled=True, activation={"enabled": True}),
        ...     ),
        ... )
        True
    """
    return voice_enabled(ws) and voice_activation_config_enabled(ws)


def resolve_voice_activation_settings(
    ws: WorkspaceConfig,
    *,
    listening: bool | None = None,
) -> VoiceActivationSettings:
    """Merge activation keys with defaults; ``listening`` reflects runtime when provided.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        listening (bool | None): Runtime listening flag from lifespan state.

    Returns:
        VoiceActivationSettings: Resolved runtime view for status surfaces.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> s = resolve_voice_activation_settings(WorkspaceConfig.minimal())
        >>> s.enabled
        False
    """
    act = _activation_cfg(ws.voice)
    enabled = voice_activation_enabled(ws)
    engine = (
        str(act.engine).strip()
        if act is not None and act.engine is not None
        else DEFAULT_VOICE_ACTIVATION_ENGINE
    )
    wake_word = (
        str(act.wake_word).strip()
        if act is not None and act.wake_word is not None
        else DEFAULT_VOICE_ACTIVATION_WAKE_WORD
    )
    return VoiceActivationSettings(
        enabled=enabled,
        listening=bool(listening) if listening is not None else False,
        wake_word=wake_word,
        engine=engine,
    )


def voice_wake_extra_installed() -> bool:
    """Return whether the optional wake-word engine module is importable.

    Returns:
        bool: ``True`` when ``openwakeword`` (W37 extra) is on ``sys.path``.

    Examples:
        >>> isinstance(voice_wake_extra_installed(), bool)
        True
    """
    return importlib.util.find_spec(VOICE_WAKE_ENGINE_MODULE) is not None


def activation_supported_platform() -> bool:
    """Return whether this host may run wake-word capture (D25 platform matrix).

    Returns:
        bool: ``False`` for unsupported OS, Docker, or explicit headless env.

    Examples:
        >>> isinstance(activation_supported_platform(), bool)
        True
    """
    if sys.platform not in ("darwin", "linux"):
        return False
    if os.path.exists("/.dockerenv"):
        return False
    return os.environ.get("SEVN_HEADLESS", "").strip() not in {"1", "true", "yes"}


def has_input_device() -> bool:
    """Best-effort input-device probe without opening a stream (D24).

    Returns:
        bool: ``True`` when ``sounddevice`` reports at least one input channel.

    Examples:
        >>> has_input_device() in (True, False)
        True
    """
    if not activation_supported_platform() or not voice_wake_extra_installed():
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


def available_wake_word_models(*, engine_id: str | None = None) -> tuple[str, ...]:
    """Return wake phrases the configured offline engine can load (W38.4).

    Args:
        engine_id (str | None): ``voice.activation.engine`` value.

    Returns:
        tuple[str, ...]: Human-readable phrases; empty when the engine is unsupported.

    Examples:
        >>> models = available_wake_word_models(engine_id="openwakeword")
        >>> isinstance(models, tuple)
        True
    """
    chosen = (engine_id or DEFAULT_VOICE_ACTIVATION_ENGINE).strip().casefold()
    if chosen != "openwakeword":
        return ()
    if voice_wake_extra_installed():
        try:
            from openwakeword.model import Model

            model = Model()
            ids = tuple(sorted(str(k) for k in model.models))
            if ids:
                return tuple(_wake_model_id_to_phrase(mid) for mid in ids)
        except Exception:
            return _fallback_wake_phrases()
    return _fallback_wake_phrases()


def _fallback_wake_phrases() -> tuple[str, ...]:
    """Bundled openWakeWord model ids mapped to operator-facing phrases.

    Returns:
        tuple[str, ...]: Default wake phrases when the engine extra is absent.

    Examples:
        >>> "hey jarvis" in _fallback_wake_phrases()
        True
    """
    return ("hey jarvis", "alexa", "hey mycroft", "hey sevn")


def _wake_model_id_to_phrase(model_id: str) -> str:
    """Map an openWakeWord model slug to a display phrase.

    Args:
        model_id (str): Engine model identifier such as ``hey_jarvis``.

    Returns:
        str: Human-readable wake phrase.

    Examples:
        >>> _wake_model_id_to_phrase("hey_jarvis")
        'hey jarvis'
    """
    slug = model_id.strip().casefold()
    mapping = {
        "hey_jarvis": "hey jarvis",
        "alexa": "alexa",
        "hey_mycroft": "hey mycroft",
    }
    return mapping.get(slug, slug.replace("_", " "))


def resolve_listening_state(
    ws: WorkspaceConfig,
    *,
    runtime_listening: bool | None = None,
) -> ListeningState:
    """Return the D24 three-way listening verdict for operator surfaces (W38).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        runtime_listening (bool | None): Gateway lifespan ``listening`` flag when known.

    Returns:
        ListeningState: ``disabled``, ``enabled_listening``, or ``enabled_unavailable``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_listening_state(WorkspaceConfig.minimal())
        'disabled'
    """
    if not voice_activation_config_enabled(ws):
        return "disabled"
    if runtime_listening is True:
        return "enabled_listening"
    return "enabled_unavailable"


def activation_status_payload(
    ws: WorkspaceConfig,
    *,
    runtime_listening: bool | None = None,
) -> dict[str, Any]:
    """Build JSON-safe activation status for CLI and Telegram (W38).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        runtime_listening (bool | None): Live gateway listening flag when wired.

    Returns:
        dict[str, Any]: ``listening_state``, settings, verdict, and privacy hints.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> activation_status_payload(WorkspaceConfig.minimal())["listening_state"]
        'disabled'
    """
    settings = resolve_voice_activation_settings(ws, listening=runtime_listening is True)
    verdict = probe_voice_activation(ws)
    state = resolve_listening_state(ws, runtime_listening=runtime_listening)
    models = available_wake_word_models(engine_id=settings.engine)
    return {
        "listening_state": state,
        "activation_enabled": voice_activation_config_enabled(ws),
        "voice_enabled": voice_enabled(ws),
        "wake_word": settings.wake_word,
        "engine": settings.engine,
        "available_wake_words": list(models),
        "wake_word_selectable": bool(models),
        "verdict": verdict,
        "privacy": (
            "Opt-in (default-off). Ambient audio stays in memory until the wake word; "
            "only post-activation utterances may be written under channel_files/ and "
            "transcribed. Raw audio and non-activated transcripts are never logged or traced. "
            "Disable activation or stop the gateway to close the mic."
        ),
    }


def format_activation_status(data: dict[str, Any]) -> str:
    """Render :func:`activation_status_payload` as plain text.

    Args:
        data (dict[str, Any]): Payload from :func:`activation_status_payload`.

    Returns:
        str: Human-readable status lines.

    Examples:
        >>> "listening_state" in format_activation_status({"listening_state": "disabled"})
        True
    """
    state = str(data.get("listening_state") or "disabled")
    labels = {
        "disabled": "disabled (mic closed)",
        "enabled_listening": "listening (mic open for wake word)",
        "enabled_unavailable": "enabled but unavailable (mic not open)",
    }
    lines = [
        f"listening_state: {labels.get(state, state)}",
        f"activation_enabled: {data.get('activation_enabled')}",
        f"wake_word: {data.get('wake_word')}",
        f"engine: {data.get('engine')}",
    ]
    verdict = data.get("verdict")
    if isinstance(verdict, dict):
        reason = str(verdict.get("reason") or "").strip()
        if reason:
            lines.append(f"reason: {reason}")
    if data.get("wake_word_selectable"):
        words = data.get("available_wake_words") or []
        if words:
            lines.append(f"available_wake_words: {', '.join(str(w) for w in words)}")
    privacy = data.get("privacy")
    if isinstance(privacy, str) and privacy.strip():
        lines.append("")
        lines.append(privacy.strip())
    return "\n".join(lines)


def probe_voice_activation(ws: WorkspaceConfig) -> dict[str, Any]:
    """Return a structured availability verdict — never raises (D25).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        dict[str, Any]: ``available``, ``status``, and ``reason`` keys.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> v = probe_voice_activation(WorkspaceConfig.minimal())
        >>> v["status"]
        'disabled'
    """
    settings = resolve_voice_activation_settings(ws)
    if not voice_activation_config_enabled(ws):
        return {
            "available": False,
            "status": "disabled",
            "reason": "voice.activation.enabled is false (default-off; D24)",
        }
    if not voice_enabled(ws):
        return {
            "available": False,
            "status": "unavailable",
            "reason": "voice.enabled is false — activation requires the voice subsystem",
        }
    if not voice_wake_extra_installed():
        return {
            "available": False,
            "status": "unavailable",
            "reason": (
                f"wake-word engine not installed — run: "
                f"uv sync --extra {VOICE_WAKE_OPTIONAL_EXTRA} && uv pip install openwakeword"
            ),
        }
    if not activation_supported_platform():
        return {
            "available": False,
            "status": "unavailable",
            "reason": "wake-word activation is unsupported on this platform or container",
        }
    if not has_input_device():
        return {
            "available": False,
            "status": "unavailable",
            "reason": "no audio input device detected",
        }
    return {
        "available": True,
        "status": "available",
        "reason": f"engine={settings.engine}; wake_word={settings.wake_word!r}",
    }


class WakeWordListener:
    """Lifecycle-managed capture loop — ambient frames discarded in memory (D24)."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        frame_source: AudioFrameSource,
        stt_pipeline: Any,
        trace: Any,
        attachments_dir: Path,
        wake_word: str = DEFAULT_VOICE_ACTIVATION_WAKE_WORD,
        engine_id: str | None = None,
        simulate_activation_at_frame: int | None = None,
        content_root: Path | None = None,
    ) -> None:
        """Store capture dependencies; never opens ``frame_source`` until :meth:`run_until_idle`.

        Args:
            workspace (WorkspaceConfig): Parsed workspace document.
            frame_source (AudioFrameSource): Injectable or live frame source.
            stt_pipeline (Any): Post-activation STT pipeline.
            trace (Any): Gateway trace sink.
            attachments_dir (Path): Attachment output directory.
            wake_word (str): Configured wake phrase.
            engine_id (str | None): ``voice.activation.engine`` value.
            simulate_activation_at_frame (int | None): Test-only activation index.
            content_root (Path | None): Workspace content root.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> class _Empty:
            ...     async def read_frames(self):
            ...         if False:
            ...             yield b""
            >>> listener = WakeWordListener(
            ...     workspace=WorkspaceConfig.minimal(),
            ...     frame_source=_Empty(),
            ...     stt_pipeline=None,
            ...     trace=None,
            ...     attachments_dir=Path("/tmp"),
            ...     wake_word="hey sevn",
            ... )
            >>> isinstance(listener, WakeWordListener)
            True
        """
        self._workspace = workspace
        self._frame_source = frame_source
        self._stt_pipeline = stt_pipeline
        self._trace = trace
        self._attachments_dir = attachments_dir
        self._wake_word = wake_word
        self._engine_id = engine_id
        self._simulate_activation_at_frame = simulate_activation_at_frame
        self._content_root = content_root
        self._stop_requested = False
        self._wake_engine: WakeWordEngine = build_wake_word_engine(
            wake_word=wake_word,
            engine_id=engine_id,
        )

    def request_stop(self) -> None:
        """Signal the background loop and live frame source to exit.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> class _Empty:
            ...     async def read_frames(self):
            ...         if False:
            ...             yield b""
            >>> listener = WakeWordListener(
            ...     workspace=WorkspaceConfig.minimal(),
            ...     frame_source=_Empty(),
            ...     stt_pipeline=None,
            ...     trace=None,
            ...     attachments_dir=Path("/tmp"),
            ... )
            >>> listener.request_stop() is None
            True
        """
        self._stop_requested = True
        stop = getattr(self._frame_source, "request_stop", None)
        if callable(stop):
            stop()

    async def run_until_idle(self, *, max_frames: int | None = None) -> None:
        """Process frames — discard ambient audio; hand off one utterance post-activation.

        Args:
            max_frames (int | None): Optional frame budget for tests.

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> class _Empty:
            ...     async def read_frames(self):
            ...         if False:
            ...             yield b""
            >>> listener = WakeWordListener(
            ...     workspace=WorkspaceConfig.minimal(),
            ...     frame_source=_Empty(),
            ...     stt_pipeline=None,
            ...     trace=None,
            ...     attachments_dir=Path("/tmp"),
            ...     wake_word="hey sevn",
            ... )
            >>> asyncio.run(listener.run_until_idle(max_frames=0)) is None
            True
        """
        frame_idx = 0
        activated = False
        utterance_frames: list[bytes] = []
        turn_id = uuid.uuid4().hex

        await emit_voice_event(
            self._trace,
            kind="voice.activation.listening",
            session_id=_WAKE_SESSION_ID,
            turn_id=turn_id,
            status="started",
            attrs={"wake_word": self._wake_word, "engine": self._engine_id or "openwakeword"},
        )

        async for frame in self._frame_source.read_frames():
            if self._stop_requested:
                break
            if max_frames is not None and frame_idx >= max_frames:
                break

            if not activated:
                if self._should_activate(frame_idx, frame):
                    activated = True
                    self._wake_engine.reset()
                    await emit_voice_event(
                        self._trace,
                        kind="voice.activation.detected",
                        session_id=_WAKE_SESSION_ID,
                        turn_id=turn_id,
                        status="ok",
                        attrs={"frame_index": frame_idx},
                    )
                    utterance_frames.append(frame)
            else:
                utterance_frames.append(frame)

            frame_idx += 1

        if activated and utterance_frames and self._stt_pipeline is not None:
            await self._handoff_utterance(utterance_frames, turn_id=turn_id)

        await emit_voice_event(
            self._trace,
            kind="voice.activation.idle",
            session_id=_WAKE_SESSION_ID,
            turn_id=turn_id,
            status="ok",
            attrs={"frames_processed": frame_idx, "activated": activated},
        )

    def _should_activate(self, frame_idx: int, frame: bytes) -> bool:
        """Return whether the current frame index/audio should trigger capture.

        Args:
            frame_idx (int): Zero-based frame index in the current pass.
            frame (bytes): Mono PCM chunk under test.

        Returns:
            bool: ``True`` when activation should begin.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> class _Empty:
            ...     async def read_frames(self):
            ...         if False:
            ...             yield b""
            >>> listener = WakeWordListener(
            ...     workspace=WorkspaceConfig.minimal(),
            ...     frame_source=_Empty(),
            ...     stt_pipeline=None,
            ...     trace=None,
            ...     attachments_dir=Path("/tmp"),
            ...     simulate_activation_at_frame=1,
            ... )
            >>> listener._should_activate(1, b"\\x00")
            True
        """
        if self._simulate_activation_at_frame is not None:
            return frame_idx >= self._simulate_activation_at_frame
        score = self._wake_engine.score_frame(frame, sample_rate=_SAMPLE_RATE)
        return self._wake_engine.is_triggered(score)

    async def _handoff_utterance(self, frames: list[bytes], *, turn_id: str) -> None:
        """Persist one capped utterance and invoke the existing STT chain (W35.7).

        Args:
            frames (list[bytes]): Post-activation PCM chunks.
            turn_id (str): Correlation id for traces and filenames.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(WakeWordListener._handoff_utterance)
            True
        """
        pcm = b"".join(frames)
        vr = voice_runtime_settings(self._workspace)
        max_bytes = int(float(vr.max_voice_mb) * 1024 * 1024)
        if len(pcm) > max_bytes:
            pcm = pcm[:max_bytes]
        self._attachments_dir.mkdir(parents=True, exist_ok=True)
        audio_path = self._attachments_dir / f"wake-{turn_id}.wav"
        await asyncio.to_thread(_write_pcm_wav, audio_path, pcm)

        duration_s = len(pcm) / (2 * _SAMPLE_RATE) if pcm else None
        if duration_s is not None and duration_s > float(vr.max_voice_seconds):
            return

        await self._stt_pipeline.transcribe_or_placeholder(
            audio_path=audio_path,
            mime_type="audio/wav",
            duration_s=duration_s,
            session_id=_WAKE_SESSION_ID,
            turn_id=turn_id,
        )


def _write_pcm_wav(path: Path, pcm: bytes, *, sample_rate: int = _SAMPLE_RATE) -> None:
    """Write mono 16-bit PCM bytes to a minimal WAV container.

    Args:
        path (Path): Destination ``.wav`` path.
        pcm (bytes): Raw PCM samples.
        sample_rate (int): Sample rate in Hz.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> target = Path(tempfile.mkdtemp()) / "a.wav"
        >>> _write_pcm_wav(target, b"\\x00\\x01")
        >>> target.stat().st_size > 44
        True
    """
    import struct

    path.write_bytes(
        struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + len(pcm),
            b"WAVE",
            b"fmt ",
            16,
            1,
            1,
            sample_rate,
            sample_rate * 2,
            2,
            16,
            b"data",
            len(pcm),
        )
        + pcm
    )


def build_wake_word_listener(
    ws: WorkspaceConfig,
    *,
    stt_pipeline: Any,
    trace: Any,
    content_root: Path | None,
    frame_source: AudioFrameSource | None = None,
) -> WakeWordListener | None:
    """Return a listener when activation is enabled and available.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        stt_pipeline (Any): Existing STT pipeline for post-activation hand-off.
        trace (Any): Gateway trace sink.
        content_root (Path | None): Workspace content root.
        frame_source (AudioFrameSource | None): Injectable mic stand-in for tests.

    Returns:
        WakeWordListener | None: ``None`` when disabled or unavailable.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> build_wake_word_listener(
        ...     WorkspaceConfig.minimal(),
        ...     stt_pipeline=None,
        ...     trace=None,
        ...     content_root=None,
        ... ) is None
        True
    """
    settings = resolve_voice_activation_settings(ws)
    if not settings.enabled:
        return None
    verdict = probe_voice_activation(ws)
    if not verdict.get("available"):
        return None
    src = frame_source or build_live_frame_source()
    if src is None:
        return None
    attachments_dir = (
        (content_root / "channel_files" / _WAKE_SESSION_ID).resolve()
        if content_root is not None
        else Path.cwd() / "channel_files" / _WAKE_SESSION_ID
    )
    act = _activation_cfg(ws.voice)
    engine_id = (
        str(act.engine).strip()
        if act is not None and act.engine is not None
        else DEFAULT_VOICE_ACTIVATION_ENGINE
    )
    return WakeWordListener(
        workspace=ws,
        frame_source=src,
        stt_pipeline=stt_pipeline,
        trace=trace,
        attachments_dir=attachments_dir,
        wake_word=settings.wake_word,
        engine_id=engine_id,
        content_root=content_root,
    )


async def _listener_background_loop(listener: WakeWordListener) -> None:
    """Run the listener until :meth:`WakeWordListener.request_stop` is set.

    Args:
        listener (WakeWordListener): Active capture loop instance.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_listener_background_loop)
        True
    """
    try:
        while not listener._stop_requested:
            await listener.run_until_idle(max_frames=None)
    except asyncio.CancelledError:
        listener.request_stop()
        raise


async def maybe_start_wake_word_listener(
    *,
    app_state: dict[str, Any],
    workspace: WorkspaceConfig,
    trace: Any = None,
    content_root: Path | None = None,
) -> None:
    """Gateway lifespan hook — no stream unless enabled **and** available (D24/D25).

    Args:
        app_state (dict[str, Any]): Mutable lifespan bag on ``app.state.voice_activation``.
        workspace (WorkspaceConfig): Parsed workspace document.
        trace (Any): Gateway trace sink.
        content_root (Path | None): Workspace content root for attachment paths.

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> asyncio.run(
        ...     maybe_start_wake_word_listener(
        ...         app_state={},
        ...         workspace=WorkspaceConfig.minimal(),
        ...     ),
        ... ) is None
        True
    """
    settings = resolve_voice_activation_settings(workspace)
    if not settings.enabled:
        app_state["listening"] = False
        return
    verdict = probe_voice_activation(workspace)
    if not verdict.get("available"):
        app_state["listening"] = False
        app_state["verdict"] = verdict
        await emit_voice_event(
            trace,
            kind="voice.activation.unavailable",
            session_id=_WAKE_SESSION_ID,
            turn_id="boot",
            status=str(verdict.get("status") or "unavailable"),
            attrs={"reason": str(verdict.get("reason") or "")},
        )
        return

    stt = build_stt_pipeline(workspace, trace=trace)
    listener = build_wake_word_listener(
        workspace,
        stt_pipeline=stt,
        trace=trace,
        content_root=content_root,
    )
    if listener is None:
        app_state["listening"] = False
        return

    app_state["listener"] = listener
    app_state["trace"] = trace
    app_state["task"] = asyncio.create_task(
        _listener_background_loop(listener),
        name="wake_word_listener",
    )
    app_state["listening"] = True
    await emit_voice_event(
        trace,
        kind="voice.activation.started",
        session_id=_WAKE_SESSION_ID,
        turn_id="boot",
        status="ok",
        attrs={"wake_word": settings.wake_word, "engine": settings.engine},
    )


async def maybe_stop_wake_word_listener(
    *,
    app_state: dict[str, Any],
    shutdown_timeout_s: float = 30.0,
) -> None:
    """Gateway shutdown hook — drain listener with timeout (W37).

    Args:
        app_state (dict[str, Any]): Lifespan bag from startup.
        shutdown_timeout_s (float): Max seconds to wait for background task exit.

    Examples:
        >>> import asyncio
        >>> asyncio.run(maybe_stop_wake_word_listener(app_state={})) is None
        True
    """
    listener = app_state.get("listener")
    task = app_state.get("task")
    trace = app_state.get("trace")
    if isinstance(listener, WakeWordListener):
        listener.request_stop()
    if isinstance(task, asyncio.Task):
        with suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=shutdown_timeout_s)
    app_state["listening"] = False
    await emit_voice_event(
        trace,
        kind="voice.activation.stopped",
        session_id=_WAKE_SESSION_ID,
        turn_id="shutdown",
        status="ok",
        attrs={},
    )


__all__ = [
    "AudioFrameSource",
    "ListeningState",
    "VoiceActivationSettings",
    "WakeWordListener",
    "activation_config_key_paths",
    "activation_status_payload",
    "activation_supported_platform",
    "available_wake_word_models",
    "build_wake_word_listener",
    "format_activation_status",
    "has_input_device",
    "maybe_start_wake_word_listener",
    "maybe_stop_wake_word_listener",
    "probe_voice_activation",
    "resolve_listening_state",
    "resolve_voice_activation_settings",
    "voice_activation_config_enabled",
    "voice_activation_enabled",
    "voice_wake_extra_installed",
]
