"""Interactive CLI prompts with packaged field help.

Module: sevn.cli.prompt_util
Depends: typer, sevn.config.field_help, sevn.cli.terminal_util

Exports:
    echo_field_collect_guide — print long description and collection hints.
    prompt_with_field_help — prompt after showing field help.
"""

from __future__ import annotations

import typer

from sevn.cli.terminal_util import terminal_hyperlink
from sevn.config.field_help import field_help_for, urls_in_help_text


def echo_field_collect_guide(field_path: str, *, collect_only: bool = False) -> None:
    """Print field help for one config path.

    Args:
        field_path (str): Dotted sevn.json path.
        collect_only (bool): When True, print only ``how_to_collect`` (for secret prompts).

    Examples:
        >>> echo_field_collect_guide("missing.path")  # doctest: +SKIP
    """
    entry = field_help_for(field_path)
    if entry is None:
        return
    if not collect_only and (description := entry.get("long_description")):
        typer.echo(description)
        typer.echo("")
    if how_to := entry.get("how_to_collect"):
        typer.echo("How to collect:")
        urls = urls_in_help_text(how_to)
        for url in urls:
            typer.echo(f"  {terminal_hyperlink(url, url)}")
        if urls:
            typer.echo("")
        typer.echo(how_to)
        typer.echo("")


def prompt_with_field_help(
    field_path: str,
    prompt: str,
    *,
    hide_input: bool = False,
    default: str | None = None,
    collect_only: bool = False,
) -> str:
    """Show field help, then prompt the operator.

    Args:
        field_path (str): Dotted sevn.json path for help lookup.
        prompt (str): Typer prompt label.
        hide_input (bool): Hide typed input (secrets).
        default (str | None): Optional default value.
        collect_only (bool): When True, show only ``how_to_collect`` before prompting.

    Returns:
        str: Operator input (stripped).

    Examples:
        >>> prompt_with_field_help("x", "Value", default="")  # doctest: +SKIP
        ''
    """
    echo_field_collect_guide(field_path, collect_only=collect_only)
    return str(typer.prompt(prompt, hide_input=hide_input, default=default)).strip()


__all__ = ["echo_field_collect_guide", "prompt_with_field_help"]
