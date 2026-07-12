"""Rich console factory with TTY / ``--json`` / ``NO_COLOR`` gating.

Module: sevn.cli.render.console
Depends: contextvars, os, sys, rich.console, typer

Exports:
    RenderOptions — frozen render gating flags for one CLI invocation.
    configure_render — update context-local render options.
    is_rich — whether Rich/ANSI formatting is allowed on stdout.
    get_console — singleton Rich ``Console`` respecting ``is_rich()``.
    plain_echo — write plain text to stdout or stderr.
"""

from __future__ import annotations

import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from rich.console import Console

_render_options: ContextVar[RenderOptions | None] = ContextVar(
    "sevn_cli_render_options",
    default=None,
)

_console: Console | None = None
_console_rich: bool | None = None


@dataclass(frozen=True)
class RenderOptions:
    """Render gating flags for one CLI process or test invocation."""

    json_mode: bool = False
    no_color: bool = False
    force_plain: bool = False


def _current_options() -> RenderOptions:
    """Return context-local render options, or defaults when unset.

    Returns:
        RenderOptions: Active options for this context.

    Examples:
        >>> _current_options().json_mode is False
        True
    """
    opts = _render_options.get()
    if opts is None:
        return RenderOptions()
    return opts


def configure_render(
    *,
    json_mode: bool | None = None,
    no_color: bool | None = None,
    force_plain: bool | None = None,
) -> RenderOptions:
    """Update context-local render options (merged with prior values).

    Args:
        json_mode (bool | None): When True, force plain output (``--json``).
        no_color (bool | None): When True, disable ANSI (``--no-color``).
        force_plain (bool | None): When True, disable Rich regardless of TTY.

    Returns:
        RenderOptions: Effective options after the merge.

    Examples:
        >>> opts = configure_render(json_mode=True)
        >>> opts.json_mode
        True
        >>> is_rich()
        False
    """
    current = _current_options()
    merged = RenderOptions(
        json_mode=json_mode if json_mode is not None else current.json_mode,
        no_color=no_color if no_color is not None else current.no_color,
        force_plain=force_plain if force_plain is not None else current.force_plain,
    )
    _render_options.set(merged)
    _reset_console_cache()
    return merged


def _env_no_color() -> bool:
    """Return True when ``NO_COLOR`` or ``SEVN_NO_COLOR`` is set.

    Returns:
        bool: Whether environment disables ANSI color.

    Examples:
        >>> isinstance(_env_no_color(), bool)
        True
    """
    return bool(os.environ.get("NO_COLOR") or os.environ.get("SEVN_NO_COLOR"))


def _stdout_is_tty() -> bool:
    """Return True when stdout reports an interactive TTY.

    Returns:
        bool: Whether stdout is a TTY.

    Examples:
        >>> isinstance(_stdout_is_tty(), bool)
        True
    """
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def is_rich(*, json_mode: bool | None = None) -> bool:
    """Return True when Rich/ANSI formatting is allowed on stdout.

    Args:
        json_mode (bool | None): Optional per-call override for JSON mode.

    Returns:
        bool: True when stdout is a TTY and color/json/plain gates allow Rich.

    Examples:
        >>> configure_render(json_mode=False, no_color=False, force_plain=True)
        RenderOptions(json_mode=False, no_color=False, force_plain=True)
        >>> is_rich()
        False
    """
    opts = _current_options()
    json_active = opts.json_mode if json_mode is None else json_mode
    if json_active or opts.force_plain:
        return False
    if opts.no_color or _env_no_color():
        return False
    return _stdout_is_tty()


def _reset_console_cache() -> None:
    """Drop cached Rich console so the next ``get_console()`` rebuilds.

    Examples:
        >>> _reset_console_cache()
    """
    global _console, _console_rich
    _console = None
    _console_rich = None


def get_console() -> Console:
    """Return a cached Rich ``Console`` configured for the current gating state.

    Returns:
        Console: Rich console with ``force_terminal``/``no_color`` from ``is_rich()``.

    Examples:
        >>> console = get_console()
        >>> console is get_console()
        True
    """
    global _console, _console_rich
    rich = is_rich()
    if _console is None or _console_rich is not rich:
        from rich.console import Console

        _console = Console(force_terminal=rich, no_color=not rich, stderr=False)
        _console_rich = rich
    return _console


def plain_echo(message: str, *, err: bool = False) -> None:
    """Write plain text without Rich markup or ANSI escapes.

    Args:
        message (str): Line to print.
        err (bool): When True, write to stderr.

    Examples:
        >>> plain_echo("ok")
        ok
    """
    typer.echo(message, err=err)


__all__ = [
    "RenderOptions",
    "configure_render",
    "get_console",
    "is_rich",
    "plain_echo",
]
