"""Interactive ``sevn config`` section picker (D3).

Module: sevn.cli.tui.config_menu
Depends: sevn.cli.config_paths, sevn.cli.tui.menu

Exports:
    run_config_menu — Textual or plain section picker; returns slug or None.
"""

from __future__ import annotations

from sevn.cli.config_paths import iter_config_sections, section_by_slug
from sevn.cli.tui.menu import run_section_picker


def run_config_menu() -> str | None:
    """Prompt for a ``/config`` section and return its slug.

    Returns:
        str | None: Section slug, or None when cancelled / non-interactive.

    Examples:
        >>> import io
        >>> from contextlib import redirect_stdout
        >>> buf = io.StringIO()
        >>> with redirect_stdout(buf):
        ...     out = run_config_menu()
        >>> out is None
        True
    """
    sections = iter_config_sections()
    if not sections:
        return None
    labels = [f"{sec.label} ({sec.slug})" for sec in sections]
    chosen = run_section_picker(
        labels,
        title="sevn config",
        prompt="Choose a /config section (Telegram parity)",
    )
    if chosen is None:
        return None
    slug = chosen.rsplit("(", 1)[-1].rstrip(")")
    if section_by_slug(slug) is None:
        return None
    return slug
