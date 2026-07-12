"""Voice-specific host-dependency provisioning: whisper.cpp binary + ffmpeg.

Module: sevn.voice.host_deps
Depends: sevn.provisioning.host_deps, sevn.voice.backends, sevn.voice.whisper_model_provisioner

Kept as a registry separate from :mod:`sevn.provisioning.host_deps` (ripgrep/deno/pango/docker)
so that registry's ``host_dep_ids()`` stays exactly stable — ``tests/provisioning/
test_host_deps.py::test_registry_ids_stable`` pins its precise contents. Voice gets its own
opt-in ``provisioning.auto_install`` ids instead: ``whisper_cpp`` (the local STT binary) and
``ffmpeg`` (voice-note format conversion). Both reuse the same
:class:`~sevn.provisioning.host_deps.HostDep` probe/install-plan shape and
:func:`~sevn.provisioning.host_deps.provision_host_deps` engine, so ``sevn sync`` and gateway
(re)start need only pass the operator's full ``auto_install`` list to both registries.

``VOICE_HOST_DEPS`` (the ``whisper_cpp``/``ffmpeg`` registry) is a plain module constant — see
the module body.

Exports:
    voice_host_dep_ids — sorted ids usable in ``provisioning.auto_install`` alongside the core ones.
    maybe_resolve_whisper_model_env — download/reuse GGML model when whisper.cpp binary is on PATH.
    provision_voice_deps — install selected-and-missing voice deps, then resolve the default model.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable

from loguru import logger

from sevn.provisioning.host_deps import HostDep, ProvisionReport, provision_host_deps
from sevn.voice.whisper_model_provisioner import DEFAULT_MODEL


def _probe_whisper_cpp() -> bool:
    """Return whether a whisper.cpp-compatible binary resolves on ``PATH``.

    Returns:
        bool: ``True`` when found.

    Examples:
        >>> isinstance(_probe_whisper_cpp(), bool)
        True
    """
    from sevn.voice.backends import _find_whisper_cpp_binary

    return _find_whisper_cpp_binary() is not None


def _probe_ffmpeg() -> bool:
    """Return whether ``ffmpeg`` resolves on ``PATH``.

    Returns:
        bool: ``True`` when found.

    Examples:
        >>> isinstance(_probe_ffmpeg(), bool)
        True
    """
    return shutil.which("ffmpeg") is not None


VOICE_HOST_DEPS: dict[str, HostDep] = {
    "whisper_cpp": HostDep(
        id="whisper_cpp",
        title="whisper.cpp (local STT binary)",
        probe=_probe_whisper_cpp,
        brew_formula=("whisper-cpp",),
        apt_packages=None,
        fallback_note=(
            "voice-in (speech-to-text) falls through the STT chain to the fail-closed "
            "placeholder instead of a real transcript"
        ),
        manual_hint=(
            "install whisper.cpp: `brew install whisper-cpp` (macOS/Linux Homebrew, MPS/CUDA) "
            "or build from source: https://github.com/ggml-org/whisper.cpp#quick-start"
        ),
        post_install_manual=(
            "On Linux without Homebrew: build whisper.cpp from source and ensure "
            "`whisper-cli` or `whisper-cpp` is on PATH"
        ),
    ),
    "ffmpeg": HostDep(
        id="ffmpeg",
        title="ffmpeg (voice-note format conversion)",
        probe=_probe_ffmpeg,
        brew_formula=("ffmpeg",),
        apt_packages=("ffmpeg",),
        fallback_note=(
            "opus/ogg voice notes are handed to whisper.cpp unconverted, which may fail or "
            "mis-transcribe on builds without native container decoding"
        ),
        manual_hint="install ffmpeg: `brew install ffmpeg` (macOS) or `apt-get install ffmpeg` "
        "(Linux)",
    ),
}


def voice_host_dep_ids() -> tuple[str, ...]:
    """Return the sorted voice host-dependency ids usable in ``provisioning.auto_install``.

    Returns:
        tuple[str, ...]: Sorted dependency ids.

    Examples:
        >>> voice_host_dep_ids()
        ('ffmpeg', 'whisper_cpp')
    """
    return tuple(sorted(VOICE_HOST_DEPS))


def maybe_resolve_whisper_model_env(
    *,
    stt_model: str = DEFAULT_MODEL,
    allow_download: bool = True,
) -> bool:
    """Ensure ``SEVN_WHISPER_CPP_MODEL`` points at a cached GGML file when whisper.cpp is on PATH.

    Opportunistic: runs even when ``whisper_cpp`` is absent from ``provisioning.auto_install`` —
    if the operator installed the binary manually, this still downloads/reuses the default model
    and sets the env var so :class:`~sevn.voice.backends.WhisperCppBackend` becomes available.

    Args:
        stt_model (str): GGML model name to fetch when missing.
        allow_download (bool): When ``False``, only reuse an on-disk cache (no network I/O). Use
            on the gateway hot path so first STT pipeline build cannot block the event loop.

    Returns:
        bool: ``True`` when a valid model path is resolved (pre-existing or freshly cached).

    Examples:
        >>> isinstance(maybe_resolve_whisper_model_env(), bool)
        True
    """
    from sevn.voice.backends import _find_whisper_cpp_binary, _whisper_model_path
    from sevn.voice.whisper_model_provisioner import ensure_whisper_model, is_whisper_model_cached

    if _whisper_model_path() is not None:
        return True
    if _find_whisper_cpp_binary() is None:
        return False
    if is_whisper_model_cached(stt_model):
        from sevn.voice.whisper_model_provisioner import model_path_for

        cached = model_path_for(stt_model)
        if cached.is_file():
            os.environ["SEVN_WHISPER_CPP_MODEL"] = str(cached)
            return True
    if not allow_download:
        return False
    try:
        model_path = ensure_whisper_model(model=stt_model)
        if model_path.is_file():
            os.environ["SEVN_WHISPER_CPP_MODEL"] = str(model_path)
            return True
    except Exception:
        logger.exception("whisper_model_provision_failed (non-fatal)")
    return _whisper_model_path() is not None


def provision_voice_deps(
    selected: Iterable[str],
    *,
    dry_run: bool = False,
    stt_model: str = DEFAULT_MODEL,
) -> ProvisionReport:
    """Install selected-and-missing voice deps, then fetch the default GGML model.

    Filters ``selected`` down to the voice-only ids (core ids like ``ripgrep`` are ignored here
    — callers pass the same ``provisioning.auto_install`` list used for
    :func:`sevn.provisioning.host_deps.provision_host_deps`). When ``whisper_cpp`` ends up
    present (already installed or freshly installed) and ``SEVN_WHISPER_CPP_MODEL`` is not
    already set, opportunistically downloads the default model and points the env var at it so
    :class:`~sevn.voice.backends.WhisperCppBackend` becomes available with no extra config.

    Args:
        selected (Iterable[str]): Ids the operator opted into (``provisioning.auto_install``).
        dry_run (bool): Plan installs without running them or fetching the model.
        stt_model (str): GGML model name to fetch once whisper.cpp is present.

    Returns:
        ProvisionReport: One outcome per selected *voice* dependency (empty when none apply).

    Examples:
        >>> provision_voice_deps(["ripgrep"]).outcomes
        []
    """
    ids = [dep_id for dep_id in dict.fromkeys(selected) if dep_id in VOICE_HOST_DEPS]
    if not ids:
        return ProvisionReport()
    report = provision_host_deps(ids, deps=VOICE_HOST_DEPS, dry_run=dry_run)
    if dry_run:
        return report
    whisper_ready = _probe_whisper_cpp()
    if whisper_ready:
        maybe_resolve_whisper_model_env(stt_model=stt_model)
    return report
