"""Doctor-style section banners and severity rows (`specs/23-cli.md` §3 preview).

Module: sevn.cli.render.sections
Depends: sevn.cli.render.console

Exports:
    section — section banner for doctor-style reports.
    check_ok — passing severity row.
    check_warn — warning severity row.
    check_fail — failing severity row.
    check_info — informational follow-up row.
"""

from __future__ import annotations

from sevn.cli.render.console import get_console, is_rich, plain_echo

_SEVERITY_STYLES: dict[str, str] = {
    "ok": "green",
    "warn": "yellow",
    "fail": "red",
    "info": "cyan",
}

_SEVERITY_GLYPHS: dict[str, str] = {
    "ok": "✓",
    "warn": "⚠",
    "fail": "✗",
    "info": "→",
}


def section(title: str) -> None:
    """Print a section banner (blank line + ``◆ title``).

    Args:
        title (str): Section heading text.

    Examples:
        >>> section("Workspace")
        <BLANKLINE>
        ◆ Workspace
    """
    banner = f"◆ {title}"
    if is_rich():
        console = get_console()
        console.print()
        console.print(banner, style="bold cyan")
        return
    plain_echo("")
    plain_echo(banner)


def _check_row(severity: str, text: str, detail: str) -> None:
    """Emit one severity row using Rich or plain glyphs.

    Args:
        severity (str): One of ``ok``, ``warn``, ``fail``, ``info``.
        text (str): Primary row text.
        detail (str): Optional detail suffix.

    Examples:
        >>> _check_row("ok", "fine", "")  # doctest: +SKIP
    """
    glyph = _SEVERITY_GLYPHS[severity]
    style = _SEVERITY_STYLES[severity]
    prefix = "    " if severity == "info" else "  "
    if is_rich():
        console = get_console()
        line = f"{prefix}{glyph} {text}"
        console.print(line, style=style)
        if detail:
            console.print(f"      {detail}", style="dim")
        return
    line = f"{prefix}{glyph} {text}"
    if detail:
        line = f"{line} {detail}"
    plain_echo(line)


def check_ok(text: str, detail: str = "") -> None:
    """Print a passing check row.

    Args:
        text (str): Primary message.
        detail (str): Optional dim detail suffix.

    Examples:
        >>> check_ok("sevn.json present")
          ✓ sevn.json present
    """
    _check_row("ok", text, detail)


def check_warn(text: str, detail: str = "") -> None:
    """Print a warning check row.

    Args:
        text (str): Primary message.
        detail (str): Optional dim detail suffix.

    Examples:
        >>> check_warn("proxy idle")
          ⚠ proxy idle
    """
    _check_row("warn", text, detail)


def check_fail(text: str, detail: str = "") -> None:
    """Print a failing check row.

    Args:
        text (str): Primary message.
        detail (str): Optional dim detail suffix.

    Examples:
        >>> check_fail("gateway down")
          ✗ gateway down
    """
    _check_row("fail", text, detail)


def check_info(text: str) -> None:
    """Print an informational follow-up row.

    Args:
        text (str): Info message.

    Examples:
        >>> check_info("run sevn doctor --fix")
            → run sevn doctor --fix
    """
    _check_row("info", text, "")


__all__ = ["check_fail", "check_info", "check_ok", "check_warn", "section"]
