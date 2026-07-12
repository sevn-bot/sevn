"""Terminal formatting helpers for interactive CLI output.

Module: sevn.cli.terminal_util
Depends: sys

Exports:
    terminal_hyperlink — OSC-8 hyperlink when stdout is a TTY.
"""

from __future__ import annotations

import sys


def terminal_hyperlink(url: str, label: str) -> str:
    """Format a terminal hyperlink when stdout is a TTY.

    Args:
        url (str): Destination URL.
        label (str): Visible link text.

    Returns:
        str: OSC-8 hyperlink sequence, or ``label (url)`` when not a TTY.

    Examples:
        >>> "Example" in terminal_hyperlink("https://example.com", "Example")
        True
    """
    if sys.stdout.isatty():
        return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"
    return f"{label} ({url})"


__all__ = ["terminal_hyperlink"]
