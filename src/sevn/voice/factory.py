"""Construct voice pipelines from workspace config (`specs/20-voice.md` §5).

Module: sevn.voice.factory
Depends: pathlib, sevn.config.defaults, sevn.config.workspace_config

Exports:
    VoiceRuntimeSettings — resolved voice knobs for gateway + pipelines.
    voice_runtime_settings — merge ``WorkspaceConfig.voice`` with shipped defaults.
    voice_enabled — global master switch helper.
    resolve_effective_tts_mode — session override ?? global default.
    probe_voice_backends — doctor/install hints for STT/TTS chains.
    build_stt_pipeline — ordered :class:`~sevn.voice.stt.SpeechToTextPipeline`.
    build_tts_pipeline — ordered :class:`~sevn.voice.tts.TextToSpeechPipeline`.
    prune_stale_tts_files — TTL cleanup under ``channel_files/.tts/``.
    maybe_preload_local_tts — optional gateway warm-up hook.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from sevn.agent.tracing.sink import TraceSink
from sevn.config.defaults import (
    DEFAULT_VOICE_ENABLED,
    DEFAULT_VOICE_LOCAL_TTS_ENGINE,
    DEFAULT_VOICE_MAX_MB,
    DEFAULT_VOICE_MAX_SECONDS,
    DEFAULT_VOICE_PRELOAD_LOCAL_TTS_ON_BOOT,
    DEFAULT_VOICE_STT_CONFIDENCE_REPROMPT_THRESHOLD,
    DEFAULT_VOICE_STT_PROVIDERS,
    DEFAULT_VOICE_TRIGGER_KEYWORDS,
    DEFAULT_VOICE_TTS_PROVIDERS,
    DEFAULT_VOICE_TTS_TEMP_TTL_DAYS,
)
from sevn.config.workspace_config import VoiceConfig, WorkspaceConfig
from sevn.voice.backends import TextToVoiceBackend, build_stt_backend, build_tts_backend
from sevn.voice.stt import SpeechToTextPipeline
from sevn.voice.tts import TextToSpeechPipeline


@dataclass(frozen=True)
class VoiceRuntimeSettings:
    """Effective voice configuration for one workspace."""

    stt_providers: tuple[str, ...]
    tts_providers: tuple[str, ...]
    voice_trigger_keywords: tuple[str, ...]
    max_voice_mb: float
    max_voice_seconds: float
    stt_confidence_reprompt_threshold: float
    tts_temp_ttl_days: int
    preload_local_tts_on_boot: bool
    tts_mode: str
    tts_voice_id: str | None
    local_tts_engine: str
    enabled: bool


def voice_enabled(ws: WorkspaceConfig) -> bool:
    """Return whether voice STT/TTS pipelines are allowed (`specs/20-voice.md` D9).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        bool: ``False`` only when ``voice.enabled`` is explicitly false.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig, VoiceConfig
        >>> voice_enabled(WorkspaceConfig.minimal(voice=VoiceConfig(enabled=False)))
        False
        >>> voice_enabled(WorkspaceConfig.minimal())
        True
    """
    v = ws.voice
    if v is not None and v.enabled is not None:
        return bool(v.enabled)
    return bool(DEFAULT_VOICE_ENABLED)


def resolve_effective_tts_mode(
    *,
    global_mode: str,
    session_override: str | None,
) -> str:
    """Resolve per-chat TTS mode: session wins, then global, then ``off`` (D4).

    Args:
        global_mode (str): Workspace ``voice.tts_mode``.
        session_override (str | None): Session ``tts_mode_override`` when set.

    Returns:
        str: ``off``, ``all``, or ``when_asked``.

    Examples:
        >>> resolve_effective_tts_mode(global_mode="off", session_override="all")
        'all'
        >>> resolve_effective_tts_mode(global_mode="all", session_override=None)
        'all'
    """
    if session_override in {"off", "all", "when_asked"}:
        return str(session_override)
    mode = (global_mode or "off").strip().casefold()
    if mode in {"off", "all", "when_asked"}:
        return mode
    return "off"


def voice_runtime_settings(ws: WorkspaceConfig) -> VoiceRuntimeSettings:
    """Merge explicit ``voice`` keys with ``defaults.py`` (`specs/20-voice.md` §5).

    ``gateway.voice_trigger_keywords`` remains a backward-compatible fallback when
    ``voice.voice_trigger_keywords`` is unset.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        VoiceRuntimeSettings: Concrete runtime values for routers and tests.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> vr = voice_runtime_settings(WorkspaceConfig.minimal())
        >>> isinstance(vr.stt_providers, tuple)
        True
    """

    v: VoiceConfig | None = ws.voice
    stt = (
        tuple(v.stt_providers) if v and v.stt_providers is not None else DEFAULT_VOICE_STT_PROVIDERS
    )
    tts = (
        tuple(v.tts_providers) if v and v.tts_providers is not None else DEFAULT_VOICE_TTS_PROVIDERS
    )
    trig: list[str] = []
    if v and v.voice_trigger_keywords is not None:
        trig = list(v.voice_trigger_keywords)
    elif ws.gateway and ws.gateway.voice_trigger_keywords is not None:
        trig = list(ws.gateway.voice_trigger_keywords)
    else:
        trig = list(DEFAULT_VOICE_TRIGGER_KEYWORDS)
    max_mb = (
        float(v.max_voice_mb) if v and v.max_voice_mb is not None else float(DEFAULT_VOICE_MAX_MB)
    )
    max_sec = (
        float(v.max_voice_seconds)
        if v and v.max_voice_seconds is not None
        else float(DEFAULT_VOICE_MAX_SECONDS)
    )
    thr = (
        float(v.stt_confidence_reprompt_threshold)
        if v and v.stt_confidence_reprompt_threshold is not None
        else float(DEFAULT_VOICE_STT_CONFIDENCE_REPROMPT_THRESHOLD)
    )
    ttl = (
        int(v.tts_temp_ttl_days)
        if v and v.tts_temp_ttl_days is not None
        else int(DEFAULT_VOICE_TTS_TEMP_TTL_DAYS)
    )
    preload = (
        bool(v.preload_local_tts_on_boot)
        if v and v.preload_local_tts_on_boot is not None
        else bool(DEFAULT_VOICE_PRELOAD_LOCAL_TTS_ON_BOOT)
    )
    mode = "off"
    if v and v.tts_mode:
        mode = str(v.tts_mode).strip() or "off"
    voice_id = str(v.tts_voice_id).strip() if v and v.tts_voice_id else None
    engine = DEFAULT_VOICE_LOCAL_TTS_ENGINE
    if v and v.local_tts_engine:
        engine = str(v.local_tts_engine).strip().casefold() or DEFAULT_VOICE_LOCAL_TTS_ENGINE
    enabled = voice_enabled(ws)
    return VoiceRuntimeSettings(
        stt_providers=stt,
        tts_providers=tts,
        voice_trigger_keywords=tuple(trig),
        max_voice_mb=max_mb,
        max_voice_seconds=max_sec,
        stt_confidence_reprompt_threshold=thr,
        tts_temp_ttl_days=ttl,
        preload_local_tts_on_boot=preload,
        tts_mode=mode,
        tts_voice_id=voice_id,
        local_tts_engine=engine,
        enabled=enabled,
    )


def build_stt_pipeline(
    ws: WorkspaceConfig,
    *,
    trace: TraceSink | None,
) -> SpeechToTextPipeline:
    """Instantiate the STT chain for ``ws``.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        trace (TraceSink | None): Trace sink for voice spans.

    Returns:
        SpeechToTextPipeline: Ordered backend chain.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> p = build_stt_pipeline(WorkspaceConfig.minimal(), trace=None)
        >>> hasattr(p, "transcribe_or_placeholder")
        True
    """

    settings = voice_runtime_settings(ws)
    from sevn.voice.host_deps import maybe_resolve_whisper_model_env

    maybe_resolve_whisper_model_env(allow_download=False)
    backends = [build_stt_backend(tag) for tag in settings.stt_providers]
    return SpeechToTextPipeline(
        backends,
        stt_confidence_reprompt_threshold=settings.stt_confidence_reprompt_threshold,
        trace=trace,
    )


def build_tts_pipeline(
    ws: WorkspaceConfig,
    *,
    content_root: Path,
    trace: TraceSink | None,
) -> TextToSpeechPipeline:
    """Instantiate the TTS chain for ``ws``.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.
        content_root (Path): Workspace narrative/content root.
        trace (TraceSink | None): Trace sink for voice spans.

    Returns:
        TextToSpeechPipeline: Ordered backend chain with temp dir wiring.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> td = Path(tempfile.mkdtemp())
        >>> p = build_tts_pipeline(WorkspaceConfig.minimal(), content_root=td, trace=None)
        >>> hasattr(p, "synthesize_or_skip")
        True
    """

    settings = voice_runtime_settings(ws)
    backends = [
        build_tts_backend(
            tag,
            workspace_root=content_root,
            local_tts_engine=settings.local_tts_engine,
        )
        for tag in settings.tts_providers
    ]
    from sevn.workspace.artifact_output import normalise_output_dir_rel

    out_dir = content_root / normalise_output_dir_rel(None) / "audio"
    return TextToSpeechPipeline(
        backends,
        voice_trigger_keywords=settings.voice_trigger_keywords,
        trace=trace,
        tts_output_dir=out_dir,
    )


def prune_stale_tts_files(*, content_root: Path, ttl_days: int) -> int:
    """Delete ``out/audio/*`` TTS files older than ``ttl_days`` (best effort).

    Args:
        content_root (Path): Workspace content root.
        ttl_days (int): Age threshold in whole days.

    Returns:
        int: Number of files deleted.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> d = td / "out" / "audio"
        >>> d.mkdir(parents=True)
        >>> p = d / "old.bin"
        >>> _ = p.write_bytes(b"x")
        >>> import os, time as time_mod
        >>> old = time_mod.time() - (10 * 86400)
        >>> os.utime(p, (old, old))
        >>> prune_stale_tts_files(content_root=td, ttl_days=7) >= 1
        True
    """

    from sevn.workspace.artifact_output import normalise_output_dir_rel

    tts_dir = content_root / normalise_output_dir_rel(None) / "audio"
    if not tts_dir.is_dir():
        return 0
    cutoff = time.time() - float(max(1, ttl_days) * 86400)
    removed = 0
    for child in tts_dir.iterdir():
        if not child.is_file():
            continue
        try:
            if child.stat().st_mtime < cutoff:
                child.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


def _log_tts_warmup_task_result(task: asyncio.Task[None]) -> None:
    """Log a completed background TTS warmup task without raising into the loop.

    Args:
        task (asyncio.Task[None]): The completed (or cancelled) warmup task.

    Returns:
        None: Always.

    Examples:
        >>> import asyncio
        >>> async def _noop() -> None:
        ...     return None
        >>> async def _run() -> None:
        ...     t = asyncio.ensure_future(_noop())
        ...     await t
        ...     _log_tts_warmup_task_result(t)
        >>> asyncio.run(_run()) is None
        True
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.debug("tts_warmup_task_failed error={}", exc)


async def maybe_preload_local_tts(ws: WorkspaceConfig) -> None:
    """Optional warm-up hook (`specs/20-voice.md` §4.1).

    Preloads the first configured local TTS backend (``text_to_voice`` / ``kokoro`` /
    ``kitten_tts``) when ``voice.tts_mode == all`` (v1 default) or
    ``voice.preload_local_tts_on_boot`` is true. Checks ``is_available`` first (cheap, no
    model weights loaded in CI); when available and the backend exposes an async
    ``warmup()`` (e.g. :class:`TextToVoiceBackend`), that warmup runs as a
    **fire-and-forget background task** — not awaited here — so a slow cold start
    (first ``uv run --with-requirements`` + model download) cannot block gateway boot.

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        None: Always (errors are swallowed).

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> asyncio.run(maybe_preload_local_tts(WorkspaceConfig.minimal())) is None
        True
    """

    settings = voice_runtime_settings(ws)
    mode = settings.tts_mode.strip().casefold()
    if mode == "off":
        return
    should_preload = mode == "all" or settings.preload_local_tts_on_boot
    if not should_preload:
        return
    local_tags = frozenset({"text_to_voice", "kokoro", "kitten_tts"})
    for tag in settings.tts_providers:
        if tag not in local_tags:
            continue
        backend = build_tts_backend(
            tag,
            local_tts_engine=settings.local_tts_engine,
        )
        try:
            available = await backend.is_available()
        except Exception:
            return
        if not available:
            return
        if isinstance(backend, TextToVoiceBackend):
            task = asyncio.ensure_future(backend.warmup())
            task.add_done_callback(_log_tts_warmup_task_result)
        return


async def probe_voice_backends(ws: WorkspaceConfig) -> dict[str, Any]:
    """Probe STT/TTS chains for ``sevn doctor`` (`specs/20-voice.md` W5).

    Args:
        ws (WorkspaceConfig): Parsed workspace document.

    Returns:
        dict[str, Any]: Structured probe rows with first-working backend hints.

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> out = asyncio.run(probe_voice_backends(WorkspaceConfig.minimal()))
        >>> "stt" in out and "tts" in out
        True
    """
    settings = voice_runtime_settings(ws)
    stt_rows: list[dict[str, Any]] = []
    tts_rows: list[dict[str, Any]] = []
    first_stt: str | None = None
    first_tts: str | None = None
    for tag in settings.stt_providers:
        backend = build_stt_backend(tag)
        ok = False
        try:
            ok = await backend.is_available()
        except Exception:
            ok = False
        if ok and first_stt is None:
            first_stt = tag
        stt_rows.append({"tag": tag, "available": ok})
    for tag in settings.tts_providers:
        tts_backend = build_tts_backend(
            tag,
            workspace_root=None,
            local_tts_engine=settings.local_tts_engine,
        )
        ok = False
        try:
            ok = await tts_backend.is_available()
        except Exception:
            ok = False
        if ok and first_tts is None:
            first_tts = tag
        row: dict[str, Any] = {"tag": tag, "available": ok}
        if isinstance(tts_backend, TextToVoiceBackend):
            row["engine"] = tts_backend.engine
        tts_rows.append(row)
    hints: list[str] = []
    if first_stt is None:
        from sevn.voice.backends import whisper_cpp_missing_prereqs

        whisper_missing = whisper_cpp_missing_prereqs()
        if whisper_missing:
            hints.extend(f"STT (whisper_cpp): {item}" for item in whisper_missing)
        else:
            hints.append("STT: no configured backend is available")
    if first_tts is None:
        hints.append(
            "TTS: install text-to-voice under workspace skills/core/text-to-voice "
            f"(engine={settings.local_tts_engine}) or edge-tts on PATH",
        )
    return {
        "enabled": settings.enabled,
        "stt": stt_rows,
        "tts": tts_rows,
        "first_stt": first_stt,
        "first_tts": first_tts,
        "hints": hints,
    }
