"""Typer CLI entry for proton-cli."""

from __future__ import annotations

import sys

import typer

from proton_cli import __version__
from proton_cli.app import Options, new_app
from proton_cli.errors import classify_exit_code
from proton_cli.render.output import Format, parse_format

app = typer.Typer(
    name="proton-cli",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    profile: str = typer.Option("", "--profile", envvar="PROTON_PROFILE", help="Profile name"),
    user: str = typer.Option("", "--user", help="Proton account email"),
    password: str = typer.Option("", "--password", help="Account password"),
    totp: str = typer.Option("", "--totp", help="TOTP 2FA code"),
    api_url: str = typer.Option("", "--api-url", help="API base URL"),
    app_version: str = typer.Option("", "--app-version", help="App version header"),
    output: str = typer.Option("text", "--output", help="Output format: text, json, yaml"),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress non-essential stderr"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview mutations without applying"),
    full_ids: bool = typer.Option(False, "--full-ids", help="Show full IDs in text output"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    fmt = parse_format(output)
    ctx.obj = new_app(
        Options(
            profile=profile,
            user=user,
            password=password,
            totp=totp,
            api_url=api_url,
            app_version=app_version,
            output=fmt,
            quiet=quiet,
            dry_run=dry_run,
            full_ids=full_ids,
        )
    )


from proton_cli.cli import api_cmd, calendar_cmd, contacts_cmd, drive_cmd, mail_cmd, pass_cmd, settings_cmd, status_cmd  # noqa: E402

app.add_typer(status_cmd.app, name="status")
app.add_typer(api_cmd.app, name="api")
app.add_typer(settings_cmd.app, name="settings")
app.add_typer(calendar_cmd.app, name="calendar")
app.add_typer(contacts_cmd.app, name="contacts")
app.add_typer(drive_cmd.app, name="drive")
app.add_typer(mail_cmd.app, name="mail")
app.add_typer(pass_cmd.app, name="pass")


def cli_main() -> None:
    try:
        app()
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code) from exc
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(classify_exit_code(exc)) from exc


if __name__ == "__main__":
    cli_main()
