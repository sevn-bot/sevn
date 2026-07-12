"""Rich tables with plain column alignment fallback.

Module: sevn.cli.render.tables
Depends: sevn.cli.render.console

Exports:
    render_table — print headers + rows as a Rich table or plain text.
"""

from __future__ import annotations

from collections.abc import Sequence

from sevn.cli.render.console import get_console, is_rich, plain_echo


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    title: str | None = None,
) -> None:
    """Render a table to stdout with Rich or plain aligned columns.

    Args:
        headers (Sequence[str]): Column titles.
        rows (Sequence[Sequence[str]]): Body rows (same width as ``headers``).
        title (str | None): Optional table title.

    Examples:
        >>> render_table(["id", "ok"], [["a", "yes"]], title="checks")  # doctest: +SKIP
    """
    if not headers:
        return
    if is_rich():
        from rich.table import Table

        table = Table(title=title, show_header=True, header_style="bold")
        for header in headers:
            table.add_column(header)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        get_console().print(table)
        return
    if title:
        plain_echo(title)
    widths = [len(str(h)) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            if idx < len(widths):
                widths[idx] = max(widths[idx], len(str(cell)))
    header_line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    plain_echo(header_line)
    for row in rows:
        plain_echo("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))


__all__ = ["render_table"]
