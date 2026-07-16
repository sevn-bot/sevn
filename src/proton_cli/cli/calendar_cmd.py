"""``calendar`` subcommands."""

from __future__ import annotations

from datetime import datetime

import typer

from proton_cli.app import App
from proton_cli.service.calendar.service import default_range

app = typer.Typer(name="calendar", no_args_is_help=True, add_completion=False)

calendars_app = typer.Typer(name="calendars", no_args_is_help=True, add_completion=False)
events_app = typer.Typer(name="events", no_args_is_help=True, add_completion=False)
app.add_typer(calendars_app, name="calendars")
app.add_typer(events_app, name="events")


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


@calendars_app.command("list")
def calendars_list(ctx: typer.Context) -> None:
    """List calendars."""
    proton_app = _run(ctx)
    rows = proton_app.calendar_svc.calendars_list()
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"calendars": rows})
        return
    proton_app.renderer.table(
        ["ID", "NAME", "COLOR", "MEMBERS"],
        [[c.id, c.name, c.color, str(c.member_count)] for c in rows],
    )


@events_app.command("list")
def events_list(
    ctx: typer.Context,
    calendar: str = typer.Option("", "--calendar", help="Calendar ID or name"),
    start: str = typer.Option("", "--start", help="YYYY-MM-DD"),
    end: str = typer.Option("", "--end", help="YYYY-MM-DD"),
) -> None:
    """List events in a date range."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cal_id = proton_app.calendar_svc.resolve_calendar_id(calendar)
    range_start, range_end = default_range()
    if start:
        range_start = datetime.strptime(start, "%Y-%m-%d")
    if end:
        range_end = datetime.strptime(end, "%Y-%m-%d")
    rows = proton_app.calendar_svc.events_list(unlocked, cal_id, range_start, range_end)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"events": rows})
        return
    proton_app.renderer.table(
        ["DATE", "TITLE", "LOCATION", "EVENT_ID"],
        [
            [
                (e.start or range_start).strftime("%Y-%m-%d"),
                e.title,
                e.location,
                e.id,
            ]
            for e in rows
        ],
    )


@events_app.command("get")
def events_get(
    ctx: typer.Context,
    calendar_id: str = typer.Argument(..., help="Calendar ID"),
    event_id: str = typer.Argument(..., help="Event ID"),
) -> None:
    """Get one decrypted event."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    ev = proton_app.calendar_svc.event_get(unlocked, calendar_id, event_id)
    proton_app.renderer.object(ev)


@events_app.command("delete")
def events_delete(
    ctx: typer.Context,
    calendar_id: str = typer.Argument(..., help="Calendar ID"),
    event_id: str = typer.Argument(..., help="Event ID"),
) -> None:
    """Delete an event."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would delete event {event_id}")
        return
    proton_app.calendar_svc.event_delete(unlocked, calendar_id, event_id)
    proton_app.renderer.success("Event deleted.")
