"""CDP protocol error type and dependency guard.

The module-level ``HAS_CDP`` flag reports whether the optional ``websockets``
dependency is importable (used to gate engine registration).

Module: sevn.browser.cdp.protocol
Depends: importlib.util

Exports:
    CDPError — raised when Chrome returns a protocol ``error`` reply to a command.

Examples:
    >>> HAS_CDP in (True, False)
    True
    >>> err = CDPError("Page.navigate", code=-32000, message="boom")
    >>> err.method
    'Page.navigate'
"""

from __future__ import annotations

import importlib.util
from typing import Any

HAS_CDP: bool = importlib.util.find_spec("websockets") is not None


class CDPError(RuntimeError):
    """A Chrome DevTools Protocol command returned an ``error`` reply.

    Attributes:
        method (str): The CDP method that failed (for example ``Page.navigate``).
        code (int | None): Protocol error code when provided by Chrome.
        data (Any): Optional structured error data.
    """

    def __init__(
        self,
        method: str,
        *,
        code: int | None = None,
        message: str = "",
        data: Any = None,
    ) -> None:
        """Store the failing method plus Chrome's error code/message/data.

        Args:
            method (str): CDP method that produced the error reply.
            code (int | None): Protocol error code.
            message (str): Human-readable protocol error message.
            data (Any): Optional structured error payload.

        Returns:
            None

        Examples:
            >>> CDPError("DOM.querySelector", message="no node").method
            'DOM.querySelector'
        """
        detail = f"{method} failed"
        if code is not None:
            detail += f" [{code}]"
        if message:
            detail += f": {message}"
        super().__init__(detail)
        self.method = method
        self.code = code
        self.message = message
        self.data = data


__all__ = ["HAS_CDP", "CDPError"]
