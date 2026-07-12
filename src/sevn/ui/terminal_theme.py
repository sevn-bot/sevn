"""Terminal palette derived from ``styles/sevn/style`` brand tokens.

Module: sevn.ui.terminal_theme
Depends: os

Exports:
    brand_header — primary-colored banner line.
    style_success — green semantic line.
    style_error — red semantic line.
    style_warning — amber semantic line.
    style_muted — dim line.
"""

from __future__ import annotations

import os

_RESET = "\033[0m"
_PRIMARY = "\033[38;2;95;177;247m"
_SUCCESS = "\033[38;2;106;156;120m"
_WARNING = "\033[38;2;200;154;82m"
_ERROR = "\033[38;2;255;59;59m"
_MUTED = "\033[38;2;148;139;128m"


def _ansi_enabled() -> bool:
    """Return True when stdout should receive ANSI color codes.

    Returns:
        bool: Whether coloring is enabled.

    Examples:
        >>> isinstance(_ansi_enabled(), bool)
        True
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    import sys

    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def brand_header(text: str) -> str:
    """Format a short branded header for CLI output.

    Args:
        text (str): Header text.

    Returns:
        str: Possibly colored string.

    Examples:
        >>> "sevn" in brand_header("sevn onboard")
        True
    """
    if not _ansi_enabled():
        return text
    return f"{_PRIMARY}{text}{_RESET}"


def style_success(text: str) -> str:
    """Color text as success when ANSI is enabled.

    Args:
        text (str): Message.

    Returns:
        str: Styled or plain text.

    Examples:
        >>> isinstance(style_success("ok"), str)
        True
    """
    if not _ansi_enabled():
        return text
    return f"{_SUCCESS}{text}{_RESET}"


def style_error(text: str) -> str:
    """Color text as error when ANSI is enabled.

    Args:
        text (str): Message.

    Returns:
        str: Styled or plain text.

    Examples:
        >>> isinstance(style_error("fail"), str)
        True
    """
    if not _ansi_enabled():
        return text
    return f"{_ERROR}{text}{_RESET}"


def style_warning(text: str) -> str:
    """Color text as warning when ANSI is enabled.

    Args:
        text (str): Message.

    Returns:
        str: Styled or plain text.

    Examples:
        >>> isinstance(style_warning("warn"), str)
        True
    """
    if not _ansi_enabled():
        return text
    return f"{_WARNING}{text}{_RESET}"


def style_muted(text: str) -> str:
    """Dim secondary CLI text when ANSI is enabled.

    Args:
        text (str): Message.

    Returns:
        str: Styled or plain text.

    Examples:
        >>> isinstance(style_muted("hint"), str)
        True
    """
    if not _ansi_enabled():
        return text
    return f"{_MUTED}{text}{_RESET}"


__all__ = [
    "brand_header",
    "style_error",
    "style_muted",
    "style_success",
    "style_warning",
]
