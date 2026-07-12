"""Reusable Textual single-select section picker for CLI menus.

Module: sevn.cli.tui.menu
Depends: textual, sevn.cli.render.console

Exports:
    SectionPickerApp — single-select list for section/topic navigation.
    run_section_picker — blocking helper returning the chosen label or None.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, ListItem, ListView, Static

from sevn.cli.render.console import plain_echo

if TYPE_CHECKING:
    from textual.binding import BindingType


class SectionPickerApp(App[None]):
    """Textual single-select picker over string section labels."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("q", "cancel", "Quit", show=False),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #prompt {
        padding: 1 2;
    }
    ListView {
        height: 1fr;
    }
    """

    def __init__(
        self,
        sections: list[str],
        *,
        title: str = "sevn",
        prompt: str = "Choose a section",
    ) -> None:
        """Initialize picker state and section labels.

        Args:
            sections (list[str]): Selectable section labels.
            title (str): Textual app title.
            prompt (str): Prompt shown above the list.

        Examples:
            >>> app = SectionPickerApp(["one"], title="pick")
            >>> app.title
            'pick'
        """
        super().__init__()
        self._sections = sections
        self.title = title
        self._prompt = prompt
        self.selected: str | None = None

    def compose(self) -> ComposeResult:
        """Build header, prompt, list, and footer widgets.

        Returns:
            ComposeResult: Generator of root widgets consumed by Textual.

        Examples:
            >>> app = SectionPickerApp(["a"])
            >>> len(list(app.compose())) >= 3
            True
        """
        yield Header()
        yield Static(self._prompt, id="prompt")
        items = [
            ListItem(Static(label), id=f"section-{idx}") for idx, label in enumerate(self._sections)
        ]
        picker = ListView(*items, id="picker")
        yield picker
        yield Footer()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Store the chosen section label and exit.

        Args:
            event (ListView.Selected): Textual selection event.

        Examples:
            >>> from unittest.mock import MagicMock
            >>> app = SectionPickerApp(["a"])
            >>> event = MagicMock()
            >>> event.item.id = "section-0"
            >>> app.on_list_view_selected(event)
            >>> app.selected
            'a'
        """
        idx = int(str(event.item.id or "section-0").split("-", 1)[1])
        if 0 <= idx < len(self._sections):
            self.selected = self._sections[idx]
        self.exit()

    def action_cancel(self) -> None:
        """Exit without a selection.

        Examples:
            >>> app = SectionPickerApp(["x"])
            >>> app.action_cancel()
            >>> app.selected is None
            True
        """
        self.selected = None
        self.exit()


def run_section_picker(
    sections: list[str],
    *,
    title: str = "sevn",
    prompt: str = "Choose a section",
) -> str | None:
    """Run the section picker and return the chosen label.

    Args:
        sections (list[str]): Selectable section labels.
        title (str): Textual app title.
        prompt (str): Prompt shown above the list.

    Returns:
        str | None: Chosen label, or None when cancelled.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     out = run_section_picker(["A", "B"])
        >>> out is None
        True
    """
    if not sections:
        return None
    from sevn.cli.tui import textual_ui_allowed

    if not textual_ui_allowed():
        plain_echo(prompt)
        for label in sections:
            plain_echo(f"  - {label}")
        return None
    app = SectionPickerApp(sections, title=title, prompt=prompt)
    app.run()
    return app.selected


__all__ = ["SectionPickerApp", "run_section_picker"]
