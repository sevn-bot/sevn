"""Textual live log viewer for ``sevn logs --follow``.

Module: sevn.cli.tui.log_viewer
Depends: re, textual, sevn.cli.render.console

Exports:
    LogViewerApp — scrollable log buffer with source/level filters.
    run_log_viewer — blocking helper for tests and ``sevn logs --follow``.
"""

from __future__ import annotations

import re
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Header, RichLog, Static


class LogViewerApp(App[None]):
    """Live log viewer with scrollback and optional source/level filters."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "quit", "Quit", show=True),
        Binding("q", "quit", "Quit", show=False),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #status {
        padding: 0 1;
        height: 1;
    }
    RichLog {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        title: str = "sevn logs",
        status: str = "source=all level=INFO",
        level_filter: set[str] | None = None,
        grep: str | None = None,
    ) -> None:
        """Initialize viewer chrome, filters, and empty scrollback.

        Args:
            title (str): Textual window title.
            status (str): Status line above the log buffer.
            level_filter (set[str] | None): Allowed levels (``None`` = all).
            grep (str | None): Case-insensitive substring filter.

        Examples:
            >>> app = LogViewerApp(title="t")
            >>> app.title
            't'
        """
        super().__init__()
        self.title = title
        self._status = status
        self._lines: list[str] = []
        self._level_filter = level_filter
        self._grep = re.compile(grep, re.I) if grep else None

    def compose(self) -> ComposeResult:
        """Build status bar and scrollable log widget.

        Returns:
            ComposeResult: Generator of root widgets consumed by Textual.

        Examples:
            >>> app = LogViewerApp()
            >>> len(list(app.compose())) >= 3
            True
        """
        yield Header()
        yield Static(self._status, id="status")
        yield RichLog(id="log", highlight=True, markup=False)
        yield Footer()

    def _passes_filters(self, line: str, *, level: str) -> bool:
        """Return True when ``line`` passes active level/grep filters.

        Args:
            line (str): Candidate log line.
            level (str): Parsed level token.

        Returns:
            bool: Whether the line should be shown.

        Examples:
            >>> app = LogViewerApp(level_filter={"ERROR"})
            >>> app._passes_filters("boom", level="INFO")
            False
        """
        if self._level_filter is not None:
            token = level.upper()
            if token == "WARNING":  # nosec B105 — log level alias
                token = "WARN"  # nosec B105 — log level alias
            allowed = {item.upper() for item in self._level_filter}
            if "WARN" in allowed:
                allowed.add("WARNING")
            if token not in allowed:
                return False
        return self._grep is None or self._grep.search(line) is not None

    def append_line(self, line: str) -> None:
        """Append one log line without filter checks (legacy API).

        Args:
            line (str): Log line text.

        Examples:
            >>> app = LogViewerApp()
            >>> app.append_line("x")
            >>> app._lines == ["x"]
            True
        """
        self.append_entry(line, source="", level="INFO")

    def append_entry(self, line: str, *, source: str, level: str) -> None:
        """Append one log line when filters allow it.

        Args:
            line (str): Display line.
            source (str): Canonical source name (unused in filter v1).
            level (str): Parsed level token.

        Examples:
            >>> app = LogViewerApp()
            >>> app.append_entry("x", source="gateway", level="INFO")
            >>> app._lines == ["x"]
            True
        """
        _ = source
        if not self._passes_filters(line, level=level):
            return
        self._lines.append(line)
        if not self.is_running:
            return
        log = self.query_one("#log", RichLog)
        log.write(line)

    def on_mount(self) -> None:
        """Replay preloaded lines into the RichLog widget.

        Examples:
            >>> app = LogViewerApp()
            >>> try:
            ...     app.on_mount()
            ... except Exception:
            ...     True
            ... else:
            ...     False
            True
        """
        log = self.query_one("#log", RichLog)
        for line in self._lines:
            log.write(line)

    def seed_lines(self, lines: list[str]) -> None:
        """Preload scrollback (used by tests and tail bootstrap).

        Args:
            lines (list[str]): Initial log lines.

        Examples:
            >>> app = LogViewerApp()
            >>> app.seed_lines(["one"])
            >>> app._lines == ["one"]
            True
        """
        self._lines.extend(lines)


def run_log_viewer(
    lines: list[str] | None = None,
    *,
    title: str = "sevn logs",
) -> None:
    """Run the log viewer when the TTY gate allows.

    Args:
        lines (list[str] | None): Optional initial scrollback lines.
        title (str): Textual window title.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     run_log_viewer(["line"])
    """
    from sevn.cli.render.console import plain_echo
    from sevn.cli.tui import textual_ui_allowed

    if not textual_ui_allowed():
        for line in lines or []:
            plain_echo(line)
        return
    app = LogViewerApp(title=title)
    if lines:
        app.seed_lines(lines)
    app.run()


__all__ = ["LogViewerApp", "run_log_viewer"]
