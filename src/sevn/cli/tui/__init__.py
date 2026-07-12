"""Lazy Textual UI loaders for interactive CLI menus (`specs/23-cli.md` §7).

Module: sevn.cli.tui
Depends: sevn.cli.render.console

Exports:
    textual_ui_allowed — whether Textual may be imported for this invocation.
    load_section_picker_app — import ``SectionPickerApp`` when allowed.
    load_log_viewer_app — import ``LogViewerApp`` skeleton when allowed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.cli.render.console import is_rich

if TYPE_CHECKING:
    from sevn.cli.tui.log_viewer import LogViewerApp
    from sevn.cli.tui.menu import SectionPickerApp


def textual_ui_allowed(*, json_mode: bool = False) -> bool:
    """Return True when Textual widgets may be imported and shown.

    Args:
        json_mode (bool): When True, interactive UI is disabled.

    Returns:
        bool: True on a Rich-capable TTY without JSON mode.

    Examples:
        >>> isinstance(textual_ui_allowed(json_mode=True), bool)
        True
    """
    return is_rich(json_mode=json_mode)


def load_section_picker_app() -> type[SectionPickerApp]:
    """Import the section picker Textual app when the TTY gate allows.

    Returns:
        type[SectionPickerApp]: ``SectionPickerApp`` class.

    Raises:
        RuntimeError: When ``textual_ui_allowed()`` is False.

    Examples:
        >>> try:
        ...     load_section_picker_app()
        ... except RuntimeError:
        ...     True
        ... else:
        ...     False
        True
    """
    if not textual_ui_allowed():
        msg = "Textual section picker requires an interactive TTY (not --json/NO_COLOR/pipe)"
        raise RuntimeError(msg)
    from sevn.cli.tui.menu import SectionPickerApp

    return SectionPickerApp


def load_log_viewer_app() -> type[LogViewerApp]:
    """Import the log viewer Textual app skeleton when the TTY gate allows.

    Returns:
        type[LogViewerApp]: ``LogViewerApp`` class.

    Raises:
        RuntimeError: When ``textual_ui_allowed()`` is False.

    Examples:
        >>> try:
        ...     load_log_viewer_app()
        ... except RuntimeError:
        ...     True
        ... else:
        ...     False
        True
    """
    if not textual_ui_allowed():
        msg = "Textual log viewer requires an interactive TTY (not --json/NO_COLOR/pipe)"
        raise RuntimeError(msg)
    from sevn.cli.tui.log_viewer import LogViewerApp

    return LogViewerApp


__all__ = [
    "load_log_viewer_app",
    "load_section_picker_app",
    "textual_ui_allowed",
]
