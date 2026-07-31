"""Shared host/extra gates for wake-word capture (D24/D25).

Module: sevn.voice.capture_prerequisites
Depends: optional ``openwakeword``, ``sounddevice``

Exports:
    activation_supported_platform — OS/container/headless matrix.
    has_input_device — mic probe without opening a stream.
    voice_wake_extra_installed — optional extra import probe.
"""

from __future__ import annotations

import importlib.util
import os
import sys

from sevn.config.defaults import VOICE_WAKE_ENGINE_MODULE


def voice_wake_extra_installed() -> bool:
    """Return whether the wake-word engine module is importable.

    Returns:
        bool: ``True`` when ``openwakeword`` is on ``sys.path``.

    Examples:
        >>> isinstance(voice_wake_extra_installed(), bool)
        True
    """
    return importlib.util.find_spec(VOICE_WAKE_ENGINE_MODULE) is not None


def activation_supported_platform() -> bool:
    """Return whether this host may run wake-word capture (D25).

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


__all__ = [
    "activation_supported_platform",
    "has_input_device",
    "voice_wake_extra_installed",
]
