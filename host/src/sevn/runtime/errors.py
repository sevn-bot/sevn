"""Runtime failures."""

from __future__ import annotations

from typing import Literal


class ModelError(Exception):
    """A model name cannot be resolved or is not enabled."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class TurnError(Exception):
    """A turn cannot be loaded or has no result to store.

    ``usage`` is what the failed run used, when the runtime reported it.
    """

    def __init__(self, message: str, *, usage: dict[str, object] | None = None) -> None:
        self.message = message
        self.usage = usage
        super().__init__(message)


type InstallErrorCode = Literal[
    "unknown_runtime",
    "unsupported_platform",
    "invalid_version",
    "invalid_manifest",
    "sha256_required",
    "download_failed",
    "checksum_mismatch",
    "unsafe_archive",
    "runtime_busy",
    "not_installed",
]


class InstallError(Exception):
    """A managed CLI runtime cannot be installed, resolved or removed (plan 0025 D6).

    ``code`` is stable; ``str(exc)`` is the human message.
    """

    def __init__(self, code: InstallErrorCode, message: str) -> None:
        self.code: InstallErrorCode = code
        self.message = message
        super().__init__(message)
