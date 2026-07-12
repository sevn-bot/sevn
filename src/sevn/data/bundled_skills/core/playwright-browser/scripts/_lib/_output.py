"""JSON stdout helpers for bundled ``playwright-browser`` skill scripts.

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._output
Depends: json, sys

Exports:
    emit_ok — write success tool envelope JSON to stdout.
    emit_error — write failure tool envelope JSON to stdout.
    main_guard — decorator wrapping ``main()`` with JSON errors.

Examples:
    >>> from _output import emit_ok
    >>> isinstance(emit_ok.__name__, str)
    True
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[[], int])


def emit_ok(data: dict[str, Any], *, message: str | None = None) -> None:
    """Write a success tool envelope to stdout.

    Args:
        data (dict[str, Any]): JSON-serialisable payload.
        message (str | None, optional): Optional human message.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     emit_ok({"n": 1})
        >>> '"ok":true' in buf.getvalue()
        True
    """
    sys.stdout.write(
        json.dumps({"ok": True, "data": data, "message": message}, separators=(",", ":")),
    )


def emit_error(code: str, error: str) -> None:
    """Write a failure tool envelope to stdout.

    Args:
        code (str): Stable error code.
        error (str): Human-readable detail.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     emit_error("VALIDATION", "bad")
        >>> '"ok":false' in buf.getvalue()
        True
    """
    sys.stdout.write(
        json.dumps({"ok": False, "error": error, "code": code}, separators=(",", ":")),
    )


def playwright_missing() -> int:
    """Emit ``DEPENDENCY_MISSING`` when Playwright is unavailable.

    Returns:
        int: Exit code ``1``.

    Examples:
        >>> playwright_missing()
        1
    """
    emit_error(
        "DEPENDENCY_MISSING",
        "playwright not installed (uv sync --extra browser && playwright install chromium)",
    )
    return 1


def main_guard(fn: _F) -> _F:
    """Wrap ``main()`` with JSON envelope emission on uncaught errors.

    Args:
        fn (Callable[[], int]): Zero-arg main callable.

    Returns:
        Callable[[], int]: Wrapped callable.

    Examples:
        >>> @main_guard
        ... def _demo() -> int:
        ...     return 0
        >>> _demo()
        0
    """

    def wrapped() -> int:
        try:
            return int(fn())
        except ImportError as exc:
            if "playwright" in str(exc).lower():
                return playwright_missing()
            emit_error("IMPORT_ERROR", str(exc))
            return 1
        except RuntimeError as exc:
            emit_error("RUNTIME_ERROR", str(exc))
            return 1
        except Exception as exc:  # noqa: BLE001 — skill script boundary
            emit_error("SCRIPT_FAILED", str(exc))
            return 1

    return wrapped  # type: ignore[return-value]
