"""Local GGML whisper.cpp model provisioning (mirrors pyclaww's voice-transcription skill).

Module: sevn.voice.whisper_model_provisioner
Depends: httpx (sync streaming client, import-deferred), pathlib, sevn.config.defaults,
    sevn.config.loader (``operator_home_dir`` only, import-deferred to avoid a config ->
    voice -> config import cycle: ``sevn.config.loader`` pulls in ``workspace_config`` ->
    ``sections.provisioning``, which lazily imports this package for its own allowlist)

Mirrors ``pyclaww/skills/voice-transcription/scripts/download_model.py`` (model registry, size
table, default ``"base"``) so the operator gets the same GGML weights pyclaww used, cached once
under the operator home instead of ``~/.pyclaww``. No network call happens at import time — only
:func:`ensure_whisper_model` touches the network, and only when the model is not already cached.

``WHISPER_MODELS`` (the tiny/base/small/medium/large GGML registry) and ``DEFAULT_MODEL``
(``"base"``) are plain module constants — see the module body.

Exports:
    WhisperModelSpec — one downloadable GGML model (name/url/size/description).
    default_whisper_model_cache_dir — ``{operator_home}/voice-models`` cache root.
    model_path_for — deterministic on-disk path for one model (no I/O).
    is_whisper_model_cached — cheap on-disk probe (no network).
    ensure_whisper_model — idempotent download-or-reuse, returns the cached model path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from sevn.config.defaults import DEFAULT_VOICE_STT_WHISPER_MODEL

DEFAULT_MODEL: str = DEFAULT_VOICE_STT_WHISPER_MODEL

_DEFAULT_DOWNLOAD_TIMEOUT_S = 30.0
_MIN_DOWNLOAD_TIMEOUT_S = 60.0
_DOWNLOAD_TIMEOUT_PER_MB_S = 2.0
_MAX_DOWNLOAD_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class WhisperModelSpec:
    """One downloadable GGML whisper.cpp model."""

    name: str
    url: str
    size_mb: int
    description: str


WHISPER_MODELS: dict[str, WhisperModelSpec] = {
    "tiny": WhisperModelSpec(
        name="tiny",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        size_mb=39,
        description="Fastest, lowest accuracy",
    ),
    "base": WhisperModelSpec(
        name="base",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        size_mb=74,
        description="Recommended default — balanced speed/accuracy on Apple Silicon",
    ),
    "small": WhisperModelSpec(
        name="small",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        size_mb=244,
        description="Better accuracy, slower",
    ),
    "medium": WhisperModelSpec(
        name="medium",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
        size_mb=769,
        description="High accuracy, requires more RAM",
    ),
    "large": WhisperModelSpec(
        name="large",
        url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large.bin",
        size_mb=1550,
        description="Best accuracy, heaviest resource use",
    ),
}


def default_whisper_model_cache_dir() -> Path:
    """Return the default on-disk cache root for downloaded GGML models.

    Returns:
        Path: ``{operator_home}/voice-models`` (``~/.sevn/voice-models`` unless ``SEVN_HOME``
        is set).

    Examples:
        >>> default_whisper_model_cache_dir().name
        'voice-models'
    """
    from sevn.config.loader import operator_home_dir

    return operator_home_dir() / "voice-models"


def model_path_for(model: str, *, cache_dir: Path | None = None) -> Path:
    """Return the on-disk path a cached ``model`` would live at (no I/O).

    Args:
        model (str): GGML model name (``"tiny"``/``"base"``/``"small"``/``"medium"``/``"large"``).
        cache_dir (Path | None): Cache root override; defaults to
            :func:`default_whisper_model_cache_dir`.

    Returns:
        Path: ``{cache_dir}/ggml-{model}.bin``.

    Raises:
        ValueError: When ``model`` is not a known GGML model name.

    Examples:
        >>> model_path_for("base", cache_dir=Path("/tmp/x")).name
        'ggml-base.bin'
    """
    if model not in WHISPER_MODELS:
        msg = f"unknown whisper.cpp model {model!r}; known models: {sorted(WHISPER_MODELS)!r}"
        raise ValueError(msg)
    root = cache_dir if cache_dir is not None else default_whisper_model_cache_dir()
    return root / f"ggml-{model}.bin"


def is_whisper_model_cached(model: str, *, cache_dir: Path | None = None) -> bool:
    """Return whether ``model`` is already downloaded (no network I/O).

    Args:
        model (str): GGML model name.
        cache_dir (Path | None): Cache root override.

    Returns:
        bool: ``True`` when the weights file exists and is non-empty.

    Examples:
        >>> is_whisper_model_cached("base", cache_dir=Path("/nonexistent-sevn-voice-cache"))
        False
    """
    path = model_path_for(model, cache_dir=cache_dir)
    return path.is_file() and path.stat().st_size > 0


def _default_downloader(url: str, dest: Path, timeout_s: float) -> None:
    """Stream ``url`` to ``dest`` via a synchronous HTTP GET (``httpx``).

    Args:
        url (str): Source URL (HuggingFace GGML weights).
        dest (Path): Destination file (a ``.part`` temp path — the caller renames on success).
        timeout_s (float): Connect/read timeout in seconds.

    Returns:
        None: Writes ``dest`` on success.

    Raises:
        Exception: Any ``httpx`` transport/status error (caller catches and degrades).

    Examples:
        >>> _default_downloader.__name__
        '_default_downloader'
    """
    import httpx

    # Connect fails fast (no network / offline dev box) while a genuinely slow-but-live
    # transfer still gets the full ``timeout_s`` between chunks — httpx's read timeout resets
    # on each received chunk rather than bounding the whole request.
    timeout = httpx.Timeout(connect=5.0, read=timeout_s, write=timeout_s, pool=5.0)
    with (
        httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response,
        dest.open("wb") as fh,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes(chunk_size=1 << 20):
            fh.write(chunk)


def ensure_whisper_model(
    *,
    model: str = DEFAULT_MODEL,
    cache_dir: Path | None = None,
    downloader: Callable[[str, Path, float], None] | None = None,
    timeout_s: float = _DEFAULT_DOWNLOAD_TIMEOUT_S,
) -> Path:
    """Ensure a GGML whisper.cpp model is cached locally; return its path (idempotent).

    Mirrors pyclaww's ``skills/voice-transcription/scripts/download_model.py``: models download
    once into ``cache_dir`` (default :func:`default_whisper_model_cache_dir`) and are reused on
    every subsequent call — no network I/O once cached. Downloads land in a ``.part`` sibling
    file first and are only renamed into place once fully written, so a partial or interrupted
    download can never be mistaken for a valid cached model (checksum-safe by atomic
    all-or-nothing construction, since upstream does not publish per-file digests to verify
    against).

    Network/download failures are logged and swallowed rather than raised — the target path is
    always returned so repeated calls stay deterministic and idempotent even when offline.
    Callers should check :func:`is_whisper_model_cached` (or the returned path's ``is_file()``)
    before relying on the weights actually being present.

    Args:
        model (str): GGML model name (``"tiny"``/``"base"``/``"small"``/``"medium"``/``"large"``).
        cache_dir (Path | None): Cache root override (tests inject a ``tmp_path``).
        downloader (Callable | None): ``(url, dest, timeout_s) -> None`` override for tests;
            defaults to a synchronous ``httpx`` streaming GET.
        timeout_s (float): Per-request timeout passed to the downloader.

    Returns:
        Path: ``{cache_dir}/ggml-{model}.bin`` — present on disk only on success.

    Raises:
        ValueError: When ``model`` is not a known GGML model name.

    Examples:
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> def fake_dl(url: str, dest: Path, timeout_s: float) -> None:
        ...     dest.write_bytes(b"weights")
        >>> p1 = ensure_whisper_model(model="base", cache_dir=td, downloader=fake_dl)
        >>> p2 = ensure_whisper_model(model="base", cache_dir=td, downloader=fake_dl)
        >>> p1 == p2
        True
        >>> is_whisper_model_cached("base", cache_dir=td)
        True
    """
    target = model_path_for(model, cache_dir=cache_dir)
    if target.is_file() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    fetch = downloader or _default_downloader
    tmp_path = target.with_name(target.name + ".part")
    spec = WHISPER_MODELS[model]
    timeout_s = max(
        timeout_s,
        _MIN_DOWNLOAD_TIMEOUT_S,
        float(spec.size_mb) * _DOWNLOAD_TIMEOUT_PER_MB_S,
    )
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_DOWNLOAD_ATTEMPTS + 1):
        try:
            fetch(spec.url, tmp_path, timeout_s)
            if tmp_path.is_file() and tmp_path.stat().st_size > 0:
                tmp_path.replace(target)
                return target
            tmp_path.unlink(missing_ok=True)
            last_exc = RuntimeError("whisper model download produced an empty file")
        except Exception as exc:
            last_exc = exc
            tmp_path.unlink(missing_ok=True)
            logger.warning(
                "whisper_model_download_failed model={} attempt={}/{} error={}",
                model,
                attempt,
                _MAX_DOWNLOAD_ATTEMPTS,
                exc,
            )
    if last_exc is not None:
        logger.error(
            "whisper_model_download_exhausted model={} url={} hint={}",
            model,
            spec.url,
            "check network connectivity or pre-download with sevn sync after adding "
            'provisioning.auto_install ["whisper_cpp"]',
        )
    return target
