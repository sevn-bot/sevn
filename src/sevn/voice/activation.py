"""Wake-word activation config, availability verdict, and lifecycle stubs (W36).

Module: sevn.voice.activation
Depends: sevn.config, sevn.voice.factory

Exports:
    AudioFrameSource — injectable mic protocol for tests.
    VoiceActivationSettings — resolved activation state for doctor/CLI/gateway.
    WakeWordListener — injectable listener stub (W37 implements capture).
    activation_config_key_paths — dotted config paths under ``voice.activation.*``.
    activation_supported_platform — host/container gate for capture (D25).
    build_wake_word_listener — factory returning ``None`` until W37.
    has_input_device — best-effort mic probe without opening a stream.
    maybe_start_wake_word_listener — gateway lifespan startup hook.
    maybe_stop_wake_word_listener — gateway lifespan shutdown hook.
    probe_voice_activation — structured availability verdict (D25).
    resolve_voice_activation_settings — merge config with defaults.
    voice_activation_config_enabled — ``voice.activation.enabled`` alone.
    voice_activation_enabled — conjunctive ``voice.enabled`` + activation.
    voice_wake_extra_installed — optional extra import probe.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sevn.config.defaults import (
    DEFAULT_VOICE_ACTIVATION_ENABLED,
    DEFAULT_VOICE_ACTIVATION_ENGINE,
    DEFAULT_VOICE_ACTIVATION_WAKE_WORD,
    VOICE_WAKE_ENGINE_MODULE,
    VOICE_WAKE_OPTIONAL_EXTRA,
)
from sevn.config.sections.channels import VoiceActivationConfig, VoiceConfig
from sevn.config.workspace_config import WorkspaceConfig
from sevn.voice.factory import voice_enabled

_ACTIVATION_CONFIG_PREFIX = "voice.activation"


class AudioFrameSource(Protocol):
    """Injectable mic stand-in for tests — W37 opens real hardware."""

    async def read_frames(self) -> AsyncIterator[bytes]:
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


def resolve_voice_activation_settings(ws: WorkspaceConfig) -> VoiceActivationSettings:
    """Merge activation keys with defaults; ``listening`` is false until W37 capture.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

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
        listening=False,
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
    """Best-effort input-device probe without opening a stream (W37 may deepen this).

    Returns:
        bool: ``False`` in W36 until capture dependencies and probing land in W37.

    Examples:
        >>> has_input_device() in (True, False)
        True
    """
    if not activation_supported_platform():
        return False
    if not voice_wake_extra_installed():
        return False
    return False


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
                f"wake-word optional extra not installed — run: "
                f"uv sync --extra {VOICE_WAKE_OPTIONAL_EXTRA}"
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
    """Lifecycle-managed listener stub — W37 implements capture and detection."""

    def __init__(
        self,
        *,
        workspace: WorkspaceConfig,
        frame_source: AudioFrameSource,
        stt_pipeline: Any,
        trace: Any,
        attachments_dir: Path,
        wake_word: str,
        simulate_activation_at_frame: int | None = None,
        content_root: Path | None = None,
    ) -> None:
        """Store dependencies for W37 capture; W36 never opens ``frame_source``.

        Args:
            workspace (WorkspaceConfig): Parsed workspace document.
            frame_source (AudioFrameSource): Injectable or live frame source.
            stt_pipeline (Any): Post-activation STT pipeline (W37).
            trace (Any): Gateway trace sink.
            attachments_dir (Path): Attachment output directory.
            wake_word (str): Configured wake phrase.
            simulate_activation_at_frame (int | None): Test-only activation index.
            content_root (Path | None): Workspace content root.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> class _Empty:
            ...     async def read_frames(self):
            ...         if False:
            ...             yield b""
            >>> WakeWordListener(
            ...     workspace=WorkspaceConfig.minimal(),
            ...     frame_source=_Empty(),
            ...     stt_pipeline=None,
            ...     trace=None,
            ...     attachments_dir=Path("/tmp"),
            ...     wake_word="hey sevn",
            ... )
            WakeWordListener(...)
        """
        self._workspace = workspace
        self._frame_source = frame_source
        self._stt_pipeline = stt_pipeline
        self._trace = trace
        self._attachments_dir = attachments_dir
        self._wake_word = wake_word
        self._simulate_activation_at_frame = simulate_activation_at_frame
        self._content_root = content_root

    async def run_until_idle(self, *, max_frames: int | None = None) -> None:
        """Process up to ``max_frames`` — no-op until W37 wires detection.

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
        _ = max_frames
        return


def build_wake_word_listener(
    ws: WorkspaceConfig,
    *,
    stt_pipeline: Any,
    trace: Any,
    content_root: Path | None,
    frame_source: AudioFrameSource | None = None,
) -> WakeWordListener | None:
    """Return a listener only when activation is enabled and available (W36: always None).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        stt_pipeline (Any): Existing STT pipeline for post-activation hand-off (W37).
        trace (Any): Gateway trace sink.
        content_root (Path | None): Workspace content root.
        frame_source (AudioFrameSource | None): Injectable mic stand-in for tests.

    Returns:
        WakeWordListener | None: ``None`` until W37 capture is implemented.

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
    _ = (stt_pipeline, trace, content_root, frame_source)
    settings = resolve_voice_activation_settings(ws)
    if not settings.enabled:
        return None
    verdict = probe_voice_activation(ws)
    if not verdict.get("available"):
        return None
    return None


async def maybe_start_wake_word_listener(
    *,
    app_state: dict[str, Any],
    workspace: WorkspaceConfig,
) -> None:
    """Gateway lifespan hook — no stream until enabled **and** available (D24).

    Args:
        app_state (dict[str, Any]): Mutable lifespan bag on ``app.state.voice_activation``.
        workspace (WorkspaceConfig): Parsed workspace document.

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
    _ = app_state
    settings = resolve_voice_activation_settings(workspace)
    if not settings.enabled:
        return
    verdict = probe_voice_activation(workspace)
    if not verdict.get("available"):
        return


async def maybe_stop_wake_word_listener(*, app_state: dict[str, Any]) -> None:
    """Gateway shutdown hook — drain listener when present (W37).

    Args:
        app_state (dict[str, Any]): Lifespan bag from startup.

    Examples:
        >>> import asyncio
        >>> asyncio.run(maybe_stop_wake_word_listener(app_state={})) is None
        True
    """
    _ = app_state
    return


__all__ = [
    "AudioFrameSource",
    "VoiceActivationSettings",
    "WakeWordListener",
    "activation_config_key_paths",
    "activation_supported_platform",
    "build_wake_word_listener",
    "has_input_device",
    "maybe_start_wake_word_listener",
    "maybe_stop_wake_word_listener",
    "probe_voice_activation",
    "resolve_voice_activation_settings",
    "voice_activation_config_enabled",
    "voice_activation_enabled",
    "voice_wake_extra_installed",
]
