"""STT/TTS backend registry (`specs/20-voice.md` §2.4).

Module: sevn.voice.backends
Depends: asyncio, httpx (optional cloud paths), pathlib

Exports:
    EdgeTtsBackend — edge-tts subprocess backend.
    SpeechToTextBackend — STT protocol.
    SynthesisResult — synthesis artefact metadata.
    TextToSpeechBackend — TTS protocol.
    TranscriptionResult — STT transcript payload.
    WhisperCppBackend — whisper.cpp subprocess backend.
    TextToVoiceBackend — unified local TTS (kokoro / supertonic) via text-to-voice skill.
    KokoroBackend — deprecated alias for TextToVoiceBackend (engine=kokoro).
    validate_voice_backend_tags — validate configured tags.
    whisper_cpp_missing_prereqs — actionable list of missing whisper.cpp prerequisites.
    build_stt_backend — factory for STT.
    build_tts_backend — factory for TTS.

Cloud HTTP backends must resolve egress base URLs via ``sevn.voice.egress.voice_http_base_url``
(process ``SEVN_PROXY_URL`` first, then workspace proxy) per ``specs/20-voice.md`` §10.3.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from loguru import logger

KNOWN_STT_TAGS: frozenset[str] = frozenset(
    {
        "whisper_cpp",
        "openai_whisper",
        "deepgram",
        "google_stt",
        "xai_grok_stt",
    },
)
KNOWN_TTS_TAGS: frozenset[str] = frozenset(
    {
        "text_to_voice",
        "kokoro",  # deprecated alias → text_to_voice (engine=kokoro)
        "kitten_tts",
        "edge_tts",
        "openai_tts",
        "elevenlabs",
        "mistral_voxtral",
        "google_gemini_tts",
    },
)
KNOWN_LOCAL_TTS_ENGINES: frozenset[str] = frozenset({"kokoro", "supertonic"})


def validate_voice_backend_tags(stt: list[str], tts: list[str]) -> None:
    """Reject unknown provider tags with an actionable error.

    Args:
        stt (list[str]): Configured STT chain.
        tts (list[str]): Configured TTS chain.

    Raises:
        ValueError: When any tag is unknown.

    Examples:
        >>> validate_voice_backend_tags(["whisper_cpp"], ["text_to_voice"])
        >>> import pytest
        >>> with pytest.raises(ValueError):
        ...     validate_voice_backend_tags(["bogus"], [])
    """

    bad_stt = [t for t in stt if t not in KNOWN_STT_TAGS]
    bad_tts = [t for t in tts if t not in KNOWN_TTS_TAGS]
    if bad_stt or bad_tts:
        parts: list[str] = []
        if bad_stt:
            parts.append(
                f"unknown voice.stt_providers tags {bad_stt!r}; "
                f"known tags: {sorted(KNOWN_STT_TAGS)!r}",
            )
        if bad_tts:
            parts.append(
                f"unknown voice.tts_providers tags {bad_tts!r}; "
                f"known tags: {sorted(KNOWN_TTS_TAGS)!r}",
            )
        raise ValueError("; ".join(parts))


@dataclass(frozen=True)
class TranscriptionResult:
    """Result of a successful STT call from one backend."""

    text: str
    provider: str
    confidence: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SpeechToTextBackend(Protocol):
    """One STT implementation (local binary, subprocess, or HTTP)."""

    id: str

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        """Return non-empty transcript text on success.

        Args:
            audio_path (Path): Input audio file path.
            mime_type (str | None): MIME hint from the adapter.
            duration_s (float | None): Known duration in seconds, if any.
            locale (str | None): Optional BCP-47 locale hint.

        Returns:
            TranscriptionResult: Parsed transcript metadata.

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> from sevn.voice.backends import SpeechToTextBackend, TranscriptionResult
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
        """Cheap probe before attempting ``transcribe``.

        Returns:
            bool: Whether this backend can run on this host.

        Examples:
            >>> import asyncio
            >>> from sevn.voice.backends import SpeechToTextBackend, TranscriptionResult
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


@dataclass(frozen=True)
class SynthesisResult:
    """Written audio artefact for adapters."""

    path: Path
    mime_type: str
    provider: str


@runtime_checkable
class TextToSpeechBackend(Protocol):
    """One TTS implementation."""

    id: str

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        """Write encoded audio bytes to ``out_path``.

        Args:
            text (str): Assistant reply to speak.
            voice_id (str | None): Provider-specific voice id.
            out_path (Path): Destination media path.

        Returns:
            None: Always (writes side-effect).

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> from sevn.voice.backends import TextToSpeechBackend
            >>> class B:
            ...     id = "x"
            ...     async def synthesize(self, *, text, voice_id, out_path):
            ...         out_path.write_bytes(b"")
            ...     async def is_available(self):
            ...         return True
            >>> p = Path("/tmp/tvb_doc.wav")
            >>> asyncio.run(B().synthesize(text="a", voice_id=None, out_path=p)) is None
            True
        """
        ...

    async def is_available(self) -> bool:
        """Cheap probe before attempting ``synthesize``.

        Returns:
            bool: Whether this backend can run on this host.

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> from sevn.voice.backends import TextToSpeechBackend
            >>> class B:
            ...     id = "x"
            ...     async def synthesize(self, *, text, voice_id, out_path):
            ...         out_path.write_bytes(b"")
            ...     async def is_available(self):
            ...         return True
            >>> asyncio.run(B().is_available())
            True
        """
        ...


_WHISPER_TIMEOUT_S = 120.0


def _find_whisper_cpp_binary() -> str | None:
    """Locate a whisper.cpp-compatible executable on ``PATH``.

    ``whisper-cli`` is Homebrew's ``whisper-cpp`` formula's current binary name (renamed from
    the upstream project's older ``main``); both plus a few historical aliases are checked so a
    provisioned or hand-built binary resolves regardless of build vintage.

    Returns:
        str | None: Absolute path when found.

    Examples:
        >>> isinstance(_find_whisper_cpp_binary(), (str, type(None)))
        True
    """
    for name in ("whisper-cli", "whisper-cpp", "main", "whisper"):
        p = shutil.which(name)
        if p:
            return p
    return None


def whisper_cpp_missing_prereqs() -> list[str]:
    """List human-readable, actionable whisper.cpp prerequisites that are missing.

    Used by ``sevn doctor`` (via :func:`sevn.voice.factory.probe_voice_backends`) to turn a
    silent STT-chain exhaustion into a specific warning naming exactly what to install, instead
    of the generic "no working STT backend" (`build-plan-from-review/waves/
    voice-duplex-tts-menu-log-fixes-wave-plan.md` W2.5).

    Returns:
        list[str]: Empty when the binary, model, and ffmpeg are all present; otherwise one
        entry per missing prerequisite with an install hint.

    Examples:
        >>> isinstance(whisper_cpp_missing_prereqs(), list)
        True
    """
    missing: list[str] = []
    if _find_whisper_cpp_binary() is None:
        missing.append(
            "whisper.cpp binary not on PATH (opt in via provisioning.auto_install: "
            '["whisper_cpp"] in sevn.json, or `brew install whisper-cpp`)',
        )
    if _whisper_model_path() is None:
        missing.append(
            "GGML whisper.cpp model not cached (runs automatically when the binary is on PATH; "
            'or opt in via provisioning.auto_install: ["whisper_cpp"])',
        )
    if shutil.which("ffmpeg") is None:
        missing.append(
            "ffmpeg not on PATH — opus/ogg voice notes cannot be converted before "
            'transcription (opt in via provisioning.auto_install: ["ffmpeg"], or '
            "`brew install ffmpeg`)",
        )
    return missing


_CONVERTIBLE_AUDIO_SUFFIXES: frozenset[str] = frozenset(
    {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".webm", ".mp4", ".aac", ".flac"},
)
_FFMPEG_TIMEOUT_S = 60.0


async def _maybe_convert_audio_for_whisper(audio_path: Path) -> tuple[Path, Path | None]:
    """Convert a non-WAV voice note to 16 kHz mono PCM WAV via ``ffmpeg`` for whisper.cpp.

    whisper.cpp's CLI expects WAV/PCM input; Telegram/Discord voice notes typically arrive as
    Opus-in-OGG. When ``audio_path``'s suffix is a known compressed format and ``ffmpeg`` is on
    ``PATH``, converts to a temp WAV alongside it — mirrors pyclaww's
    ``skills/voice-transcription/scripts/transcribe.py`` (``-ar 16000 -ac 1 -c:a pcm_s16le``).
    Falls back to the original path (best effort, never raises) when the suffix is already
    direct or ``ffmpeg`` is unavailable/fails — whisper.cpp may still accept it directly.

    Args:
        audio_path (Path): Source audio file (whatever format the adapter downloaded).

    Returns:
        tuple[Path, Path | None]: ``(path_to_feed_whisper, temp_path_for_caller_to_clean_up)``;
        the second element is ``None`` when no conversion happened (nothing to clean up).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_maybe_convert_audio_for_whisper)
        True
    """
    if audio_path.suffix.lower() not in _CONVERTIBLE_AUDIO_SUFFIXES:
        return audio_path, None
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return audio_path, None
    tmp_wav = audio_path.with_name(f"{audio_path.stem}_{uuid4().hex[:8]}.wav")
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(audio_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(tmp_wav),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return audio_path, None
    if proc.returncode != 0 or not tmp_wav.is_file() or tmp_wav.stat().st_size == 0:
        tmp_wav.unlink(missing_ok=True)
        return audio_path, None
    return tmp_wav, tmp_wav


def _whisper_model_path() -> Path | None:
    """Resolve ``SEVN_WHISPER_CPP_MODEL`` when it points at a file.

    Falls back to the default cached GGML path under the operator home when the env var is
    unset but :func:`~sevn.voice.whisper_model_provisioner.ensure_whisper_model` has already
    populated the cache.

    Returns:
        Path | None: Model weights path, or ``None`` when unset/missing.

    Examples:
        >>> _whisper_model_path() is None or _whisper_model_path().is_file()
        True
    """
    raw = os.environ.get("SEVN_WHISPER_CPP_MODEL", "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file():
            return p
    from sevn.voice.whisper_model_provisioner import DEFAULT_MODEL, model_path_for

    cached = model_path_for(DEFAULT_MODEL)
    return cached if cached.is_file() else None


class WhisperCppBackend:
    """Local whisper.cpp subprocess (`specs/20-voice.md` §2.4).

    Requires ``SEVN_WHISPER_CPP_MODEL`` pointing at a GGML/GGUF weights file.
    CLI flags follow upstream ``main`` / ``whisper-cpp`` examples (``-m``, ``-f``,
    ``-nt``, ``-otxt``); adjust env or PATH when your build uses a different argv.
    """

    id = "whisper_cpp"

    async def is_available(self) -> bool:
        """Return whether binary and model weights are present.

        Returns:
            bool: ``True`` when both ``PATH`` and ``SEVN_WHISPER_CPP_MODEL`` resolve.

        Examples:
            >>> import asyncio
            >>> isinstance(asyncio.run(WhisperCppBackend().is_available()), bool)
            True
        """
        if _find_whisper_cpp_binary() is None:
            return False
        return _whisper_model_path() is not None

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe ``audio_path`` via local whisper.cpp subprocess.

        Non-WAV formats (opus/ogg/mp3/...) are converted to 16 kHz mono PCM WAV via ``ffmpeg``
        first when it is on ``PATH`` (see :func:`_maybe_convert_audio_for_whisper`); the temp
        WAV and its whisper.cpp ``.txt`` sidecar are cleaned up before returning.

        Args:
            audio_path (Path): On-disk input audio.
            mime_type (str | None): MIME type hint.
            duration_s (float | None): Duration seconds, if known.
            locale (str | None): Optional locale hint (ignored in v1).

        Returns:
            TranscriptionResult: Non-empty transcript row.

        Examples:
            >>> WhisperCppBackend.id
            'whisper_cpp'
        """
        binary = _find_whisper_cpp_binary()
        if binary is None:
            msg = "whisper_cpp binary not found on PATH"
            raise RuntimeError(msg)
        model = _whisper_model_path()
        if model is None:
            msg = "whisper_cpp requires SEVN_WHISPER_CPP_MODEL pointing at a model file"
            raise RuntimeError(msg)
        _ = mime_type, duration_s, locale
        feed_path, cleanup_path = await _maybe_convert_audio_for_whisper(audio_path)
        out_txt = Path(str(feed_path) + ".txt")
        unlink_sidecar = False
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "-m",
                str(model),
                "-f",
                str(feed_path),
                "-nt",
                "-otxt",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=_WHISPER_TIMEOUT_S)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                msg = "whisper_cpp subprocess timed out"
                raise RuntimeError(msg) from None
            if proc.returncode != 0:
                msg = f"whisper_cpp exited {proc.returncode}"
                raise RuntimeError(msg)
            text = ""
            if out_txt.is_file():
                text = out_txt.read_text(encoding="utf-8", errors="replace").strip()
            if not text:
                msg = "whisper_cpp produced empty transcript"
                raise RuntimeError(msg)
            unlink_sidecar = True
            return TranscriptionResult(text=text, provider=self.id, confidence=None, raw={})
        finally:
            if unlink_sidecar:
                out_txt.unlink(missing_ok=True)
            if cleanup_path is not None:
                cleanup_path.unlink(missing_ok=True)
                Path(str(cleanup_path) + ".txt").unlink(missing_ok=True)


class _HttpClosedSTTBackend:
    """Cloud STT placeholder — fails closed until secrets + proxy wiring land."""

    def __init__(self, tag: str) -> None:
        """Store the registry tag for error messages.

        Args:
            tag (str): STT tag from config.

        Returns:
            None: Always.

        Examples:
            >>> b = _HttpClosedSTTBackend("openai_whisper")
            >>> b.id
            'openai_whisper'
        """
        self.id = tag

    async def is_available(self) -> bool:
        """Network STT is unavailable in the closed stub.

        Returns:
            bool: Always ``False`` until credentials land.

        Examples:
            >>> import asyncio
            >>> asyncio.run(_HttpClosedSTTBackend("x").is_available())
            False
        """
        return False

    async def transcribe(
        self,
        *,
        audio_path: Path,
        mime_type: str | None,
        duration_s: float | None,
        locale: str | None = None,
    ) -> TranscriptionResult:
        """Fail fast: cloud STT is not wired in v1.

        Args:
            audio_path (Path): On-disk input path.
            mime_type (str | None): MIME hint.
            duration_s (float | None): Duration in seconds, if known.
            locale (str | None): Optional locale.

        Returns:
            TranscriptionResult: Not reached (always raises).

        Raises:
            RuntimeError: Always (placeholder).

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> async def _r():
            ...     return await _HttpClosedSTTBackend("t").transcribe(
            ...         audio_path=Path("/a"), mime_type=None, duration_s=None,
            ...     )
            >>> try:
            ...     asyncio.run(_r())
            ... except RuntimeError as e:
            ...     "not available" in str(e)
            True
        """
        _ = audio_path, mime_type, duration_s, locale
        msg = f"{self.id} is not available without configured credentials and egress"
        raise RuntimeError(msg)


class _UnavailableLocalTTSBackend:
    """Local TTS slot — unavailable until Kitten binaries ship in-tree."""

    def __init__(self, tag: str) -> None:
        """Store the registry tag for error messages.

        Args:
            tag (str): TTS tag from config.

        Returns:
            None: Always.

        Examples:
            >>> _UnavailableLocalTTSBackend("kokoro").id
            'kokoro'
        """
        self.id = tag

    async def is_available(self) -> bool:
        """Local engines are absent until bundled binaries exist.

        Returns:
            bool: Always ``False`` in v1.

        Examples:
            >>> import asyncio
            >>> asyncio.run(_UnavailableLocalTTSBackend("kokoro").is_available())
            False
        """
        return False

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        """Placeholder synthesizer — raises until packaged runtime exists.

        Args:
            text (str): Assistant reply text.
            voice_id (str | None): Voice override.
            out_path (Path): Target media path.

        Returns:
            None: Not reached (always raises).

        Raises:
            RuntimeError: Always (placeholder).

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> async def _r():
            ...     await _UnavailableLocalTTSBackend("kokoro").synthesize(
            ...         text="hi", voice_id=None, out_path=Path("/tmp/o.bin"))
            >>> try:
            ...     asyncio.run(_r())
            ... except RuntimeError as e:
            ...     "not installed" in str(e)
            True
        """
        _ = text, voice_id, out_path
        msg = f"{self.id} local runtime not installed"
        raise RuntimeError(msg)


def _find_text_to_voice_skill_dir(workspace_root: Path | None) -> Path | None:
    """Locate ``text-to-voice`` (or legacy ``kokoro-tts``) skill scripts.

    Discovery order: ``SEVN_TEXT_TO_VOICE_SKILL_DIR``, ``SEVN_KOKORO_SKILL_DIR`` (legacy),
    then ``skills/{core,user}/text-to-voice``, then ``skills/{core,user}/kokoro-tts``.

    Args:
        workspace_root (Path | None): Workspace content root.

    Returns:
        Path | None: Skill directory containing ``scripts/generate.py``.

    Examples:
        >>> _find_text_to_voice_skill_dir(None) is None or True
        True
    """
    for env_key in ("SEVN_TEXT_TO_VOICE_SKILL_DIR", "SEVN_KOKORO_SKILL_DIR"):
        env_raw = os.environ.get(env_key, "").strip()
        if env_raw:
            candidate = Path(env_raw).expanduser()
            if (candidate / "scripts" / "generate.py").is_file():
                return candidate
    roots: list[Path] = []
    if workspace_root is not None:
        roots.append(workspace_root.expanduser().resolve())
    ws_env = os.environ.get("SEVN_WORKSPACE", "").strip()
    if ws_env:
        roots.append(Path(ws_env).expanduser().resolve())
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        for ns in ("core", "user"):
            for skill_name in ("text-to-voice", "kokoro-tts"):
                skill = root / "skills" / ns / skill_name
                if (skill / "scripts" / "generate.py").is_file():
                    return skill
    return None


# Backward-compatible alias used by older tests / imports.
_find_kokoro_skill_dir = _find_text_to_voice_skill_dir


def _normalise_local_tts_engine(engine: str | None) -> str:
    """Return a known local TTS engine tag (default ``kokoro``).

    Args:
        engine (str | None): Configured or forced engine name.

    Returns:
        str: ``kokoro`` or ``supertonic``.

    Examples:
        >>> _normalise_local_tts_engine("supertonic")
        'supertonic'
        >>> _normalise_local_tts_engine(None)
        'kokoro'
    """
    raw = (engine or "").strip().casefold()
    if raw in KNOWN_LOCAL_TTS_ENGINES:
        return raw
    return "kokoro"


def _requirements_file_for_engine(skill_dir: Path, engine: str) -> Path | None:
    """Resolve the engine-specific requirements file under ``skill_dir``.

    Prefers ``requirements-<engine>.txt``, then legacy ``requirements.txt``.

    Args:
        skill_dir (Path): Skill root.
        engine (str): ``kokoro`` or ``supertonic``.

    Returns:
        Path | None: Requirements file when present.
    """
    specific = skill_dir / f"requirements-{engine}.txt"
    if specific.is_file():
        return specific
    legacy = skill_dir / "requirements.txt"
    return legacy if legacy.is_file() else None


class TextToVoiceBackend:
    """Unified local TTS via the ``text-to-voice`` skill (kokoro / supertonic engines)."""

    id = "text_to_voice"

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        engine: str | None = None,
        registry_id: str | None = None,
    ) -> None:
        """Store workspace root, resolved engine, and optional registry id override.

        Args:
            workspace_root (Path | None): Workspace content root.
            engine (str | None): ``kokoro`` or ``supertonic`` (default ``kokoro``).
            registry_id (str | None): Override ``id`` (used by deprecated ``kokoro`` alias).

        Examples:
            >>> TextToVoiceBackend().id
            'text_to_voice'
            >>> TextToVoiceBackend(engine="supertonic").engine
            'supertonic'
        """
        self._workspace_root = workspace_root
        self._engine = _normalise_local_tts_engine(engine)
        if registry_id:
            self.id = registry_id

    @property
    def engine(self) -> str:
        """Active local TTS engine (``kokoro`` or ``supertonic``)."""
        return self._engine

    async def is_available(self) -> bool:
        """Return whether the text-to-voice skill script is discoverable.

        Returns:
            bool: ``True`` when ``scripts/generate.py`` exists.

        Examples:
            >>> import asyncio
            >>> isinstance(asyncio.run(TextToVoiceBackend().is_available()), bool)
            True
        """
        return _find_text_to_voice_skill_dir(self._workspace_root) is not None

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        """Generate speech via ``uv run python generate.py --engine …``.

        Args:
            text (str): Assistant reply to speak.
            voice_id (str | None): Engine-specific voice id.
            out_path (Path): Destination media path (``.ogg`` or ``.wav``).

        Raises:
            RuntimeError: When the skill is missing or subprocess fails.

        Examples:
            >>> TextToVoiceBackend.id
            'text_to_voice'
        """
        skill_dir = _find_text_to_voice_skill_dir(self._workspace_root)
        if skill_dir is None:
            msg = (
                "text-to-voice skill not found "
                "(install under workspace skills/core/text-to-voice)"
            )
            raise RuntimeError(msg)
        script = skill_dir / "scripts" / "generate.py"
        req_file = _requirements_file_for_engine(skill_dir, self._engine)
        cmd = ["uv", "run", "--python", "3.12"]
        if req_file is not None:
            cmd.extend(["--with-requirements", str(req_file)])
        cmd.extend(
            [
                "python",
                str(script),
                text,
                "--engine",
                self._engine,
                "--output",
                str(out_path),
            ],
        )
        if voice_id:
            cmd.extend(["--voice", voice_id])
        env = dict(os.environ)
        env["SEVN_LOCAL_TTS_ENGINE"] = self._engine
        if self._workspace_root is not None:
            env["SEVN_WORKSPACE"] = str(self._workspace_root.resolve())
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(skill_dir / "scripts"),
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            msg = f"text_to_voice ({self._engine}) synthesize timed out"
            raise RuntimeError(msg) from None
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="replace")[:500]
            msg = (
                f"text_to_voice ({self._engine}) synthesize failed "
                f"rc={proc.returncode}: {err}"
            )
            raise RuntimeError(msg)
        if out_path.is_file() and out_path.stat().st_size > 0:
            return
        out_line = (stdout or b"").decode("utf-8", errors="replace").strip().splitlines()
        if out_line:
            candidate = Path(out_line[-1].strip())
            if candidate.is_file() and candidate.stat().st_size > 0:
                if candidate.resolve() != out_path.resolve():
                    out_path.write_bytes(candidate.read_bytes())
                return
        msg = f"text_to_voice ({self._engine}) synthesize produced no audio"
        raise RuntimeError(msg)

    async def warmup(self) -> None:
        """Prime the configured engine's subprocess environment (best-effort).

        Runs a throwaway one-word synthesis so ``uv run --with-requirements`` and
        model download happen once in the background before a user-facing call.

        Returns:
            None: Always.

        Examples:
            >>> import asyncio
            >>> asyncio.run(TextToVoiceBackend().warmup()) is None
            True
        """
        skill_dir = _find_text_to_voice_skill_dir(self._workspace_root)
        if skill_dir is None:
            logger.debug("text_to_voice_warmup_skipped reason=skill_not_found")
            return
        with tempfile.TemporaryDirectory(prefix="sevn-text-to-voice-warmup-") as tmp:
            out_path = Path(tmp) / "warmup.wav"
            try:
                await self.synthesize(text="warm up", voice_id=None, out_path=out_path)
            except Exception as exc:  # best-effort warmup, never raises
                logger.debug(
                    "text_to_voice_warmup_failed engine={} error={}",
                    self._engine,
                    exc,
                )
                return
        logger.debug("text_to_voice_warmup_completed engine={}", self._engine)


class KokoroBackend(TextToVoiceBackend):
    """Deprecated alias for :class:`TextToVoiceBackend` with ``engine=kokoro``.

    Prefer ``text_to_voice`` + ``voice.local_tts_engine``. Kept so older imports and
    ``tts_providers: ["kokoro"]`` configs keep working.
    """

    id = "kokoro"

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        """Construct a kokoro-forced text-to-voice backend.

        Args:
            workspace_root (Path | None): Workspace content root.

        Examples:
            >>> KokoroBackend().id
            'kokoro'
            >>> KokoroBackend().engine
            'kokoro'
        """
        super().__init__(workspace_root=workspace_root, engine="kokoro", registry_id="kokoro")


class _HttpClosedTTSBackend:
    """Cloud TTS placeholder — fails closed without credentials."""

    def __init__(self, tag: str) -> None:
        """Store the registry tag for error messages.

        Args:
            tag (str): TTS tag from config.

        Returns:
            None: Always.

        Examples:
            >>> _HttpClosedTTSBackend("openai_tts").id
            'openai_tts'
        """
        self.id = tag

    async def is_available(self) -> bool:
        """Cloud TTS is unavailable without secrets.

        Returns:
            bool: Always ``False`` in v1.

        Examples:
            >>> import asyncio
            >>> asyncio.run(_HttpClosedTTSBackend("openai_tts").is_available())
            False
        """
        return False

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        """Placeholder synthesizer — raises until credentials exist.

        Args:
            text (str): Assistant reply text.
            voice_id (str | None): Voice override.
            out_path (Path): Target media path.

        Returns:
            None: Not reached (always raises).

        Raises:
            RuntimeError: Always (placeholder).

        Examples:
            >>> import asyncio
            >>> from pathlib import Path
            >>> async def _r():
            ...     await _HttpClosedTTSBackend("openai_tts").synthesize(
            ...         text="hi", voice_id=None, out_path=Path("/tmp/o.bin"))
            >>> try:
            ...     asyncio.run(_r())
            ... except RuntimeError as e:
            ...     "not available" in str(e)
            True
        """
        _ = text, voice_id, out_path
        msg = f"{self.id} is not available without configured credentials and egress"
        raise RuntimeError(msg)


class EdgeTtsBackend:
    """Microsoft Edge speech network client — fails closed without ``edge-tts``."""

    id = "edge_tts"

    async def is_available(self) -> bool:
        """Return whether ``edge-tts`` exists on ``PATH``.

        Returns:
            bool: ``True`` when the CLI is discoverable.

        Examples:
            >>> import asyncio
            >>> isinstance(asyncio.run(EdgeTtsBackend().is_available()), bool)
            True
        """
        return shutil.which("edge-tts") is not None

    async def synthesize(
        self,
        *,
        text: str,
        voice_id: str | None,
        out_path: Path,
    ) -> None:
        """Run ``edge-tts`` to write ``out_path``.

        Args:
            text (str): Text to speak.
            voice_id (str | None): Neural voice id (default Aria).
            out_path (Path): Output media path.

        Returns:
            None: On success (writes side-effect).

        Raises:
            RuntimeError: When the CLI is missing or exits non-zero.

        Examples:
            >>> EdgeTtsBackend.id
            'edge_tts'
        """
        if shutil.which("edge-tts") is None:
            msg = "edge-tts CLI not on PATH"
            raise RuntimeError(msg)
        voice = voice_id or "en-US-AriaNeural"
        proc = await asyncio.create_subprocess_exec(
            "edge-tts",
            "--voice",
            voice,
            "--text",
            text,
            "--write-media",
            str(out_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="replace")[:500]
            msg = f"edge-tts failed rc={proc.returncode}: {err}"
            raise RuntimeError(msg)
        _ = stdout


def build_stt_backend(tag: str) -> SpeechToTextBackend:
    """Materialise one STT backend (``tag`` must be validated upstream).

    Args:
        tag (str): Registry tag.

    Returns:
        SpeechToTextBackend: Concrete implementation.

    Raises:
        ValueError: When ``tag`` is unknown.

    Examples:
        >>> build_stt_backend("whisper_cpp").id
        'whisper_cpp'
    """

    if tag == "whisper_cpp":
        return WhisperCppBackend()
    if tag in KNOWN_STT_TAGS and tag != "whisper_cpp":
        return _HttpClosedSTTBackend(tag)
    msg = f"unknown STT tag {tag!r}"
    raise ValueError(msg)


def build_tts_backend(
    tag: str,
    *,
    workspace_root: Path | None = None,
    local_tts_engine: str | None = None,
) -> TextToSpeechBackend:
    """Materialise one TTS backend.

    Args:
        tag (str): Registry tag.
        workspace_root (Path | None): Workspace root for local backends.
        local_tts_engine (str | None): Engine for ``text_to_voice`` (``kokoro`` / ``supertonic``).

    Returns:
        TextToSpeechBackend: Concrete implementation.

    Raises:
        ValueError: When ``tag`` is unknown.

    Examples:
        >>> build_tts_backend("edge_tts").id
        'edge_tts'
        >>> build_tts_backend("text_to_voice", local_tts_engine="supertonic").id
        'text_to_voice'
    """

    if tag == "edge_tts":
        return EdgeTtsBackend()
    if tag == "text_to_voice":
        return TextToVoiceBackend(
            workspace_root=workspace_root,
            engine=local_tts_engine,
        )
    if tag == "kokoro":
        return KokoroBackend(workspace_root=workspace_root)
    if tag == "kitten_tts":
        return _UnavailableLocalTTSBackend(tag)
    if tag in KNOWN_TTS_TAGS:
        return _HttpClosedTTSBackend(tag)
    msg = f"unknown TTS tag {tag!r}"
    raise ValueError(msg)
