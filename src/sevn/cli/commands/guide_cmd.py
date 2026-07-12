"""``sevn guide`` — narrative CLI walkthroughs (D11).

Module: sevn.cli.commands.guide_cmd
Depends: typer, sevn.cli.help.guide, sevn.cli.render.console

Exports:
    register — attach ``guide`` command to the root Typer app.
"""

from __future__ import annotations

import typer

from sevn.cli.help.guide import guide_title, list_guide_topics, load_guide
from sevn.cli.render.console import configure_render, get_console, is_rich, plain_echo


def register(app: typer.Typer) -> None:
    """Attach ``sevn guide`` to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command(
        "guide",
        help=(
            "Narrative operator walkthroughs for common sevn CLI workflows. "
            "Run without a topic to list bundled guides."
        ),
    )
    def guide_cmd(
        topic: str | None = typer.Argument(
            None,
            help="Guide topic slug (e.g. getting-started, doctor, logs-traces).",
        ),
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit JSON with topic list or guide body metadata.",
        ),
    ) -> None:
        """Show a bundled guide or list available topics."""
        configure_render(json_mode=json_out)
        topics = list_guide_topics()
        if topic is None:
            if json_out:
                import json

                typer.echo(json.dumps({"topics": topics}, sort_keys=True))
                raise typer.Exit(0)
            plain_echo("Available guides (sevn guide <topic>):\n")
            for slug in topics:
                try:
                    body = load_guide(slug)
                    title = guide_title(slug, body)
                except FileNotFoundError:
                    title = slug.replace("-", " ").title()
                plain_echo(f"  {slug:<18} {title}")
            plain_echo("\nSee also: sevn --help (grouped by Mission Control panels).")
            raise typer.Exit(0)

        try:
            body = load_guide(topic)
        except FileNotFoundError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(2) from exc
        except ValueError as exc:
            typer.secho(str(exc), err=True)
            raise typer.Exit(2) from exc

        if json_out:
            import json

            payload = {
                "topic": topic.strip().lower(),
                "title": guide_title(topic, body),
                "body": body,
            }
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(0)

        if is_rich():
            get_console().print(body)
        else:
            plain_echo(body)
        raise typer.Exit(0)
