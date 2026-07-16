"""``calendar`` subcommands."""

from __future__ import annotations

from datetime import datetime

import typer

from proton_cli.app import App
from proton_cli.service.calendar.service import EventInput, default_range, status_from_flag
from proton_cli.service.mail.service import InlineAttachment, SendOptions

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


@events_app.command("create")
def events_create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title"),
    start: str = typer.Option(..., "--start", help="RFC3339 or YYYY-MM-DDTHH:MM"),
    calendar: str = typer.Option("", "--calendar", help="Calendar ID or name"),
    location: str = typer.Option("", "--location"),
    description: str = typer.Option("", "--description"),
    duration: str = typer.Option("1h", "--duration", help="e.g. 1h, 30m, 1d"),
    all_day: bool = typer.Option(False, "--all-day"),
    rrule: str = typer.Option("", "--rrule"),
    remind: list[str] = typer.Option([], "--remind", help="Reminder before start (repeatable)"),
    attendee: list[str] = typer.Option([], "--attendee", help="Attendee email (repeatable)"),
) -> None:
    """Create a calendar event."""
    from proton_cli.crypto import ical as ical_crypto

    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cal_id = proton_app.calendar_svc.resolve_calendar_id(calendar)
    start_dt = ical_crypto.parse_time(start)
    end_dt = start_dt + ical_crypto.parse_duration(duration)
    if proton_app.dry_run:
        proton_app.renderer.info(
            f"dry-run: would create event {title!r} in calendar {cal_id}"
        )
        return
    result = proton_app.calendar_svc.event_create(
        unlocked,
        cal_id,
        EventInput(
            title=title,
            location=location,
            description=description,
            start=start_dt,
            end=end_dt,
            all_day=all_day,
            rrule=rrule,
            reminders=list(remind),
            attendees=list(attendee),
        ),
    )
    if result.invite:
        body = f'You have been invited to "{title}".\n\nThe calendar invitation is attached.'
        try:
            proton_app.mail_svc.send(
                unlocked,
                SendOptions(
                    to=result.invite.recipients,
                    subject=result.invite.subject,
                    body=body,
                    inline_attachments=[
                        InlineAttachment(
                            filename="invite.ics",
                            mime_type="text/calendar; method=REQUEST",
                            data=result.invite.ics.encode(),
                        )
                    ],
                ),
            )
        except Exception as exc:
            proton_app.renderer.info(
                f"event created, but sending invitation email failed: {exc}"
            )
    if proton_app.renderer.format.value == "text":
        print(result.id)
    proton_app.renderer.success(f"Created event {title!r}")


@events_app.command("respond")
def events_respond(
    ctx: typer.Context,
    args: list[str] = typer.Argument(..., help="CALENDAR_ID EVENT_ID or TITLE"),
    status: str = typer.Option(..., "--status", help="accept, tentative, or decline"),
) -> None:
    """Reply to a calendar invitation."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    partstat = status_from_flag(status)
    if not args:
        raise typer.BadParameter("provide CALENDAR_ID EVENT_ID or a title search term")
    cal_id, ev_id = proton_app.calendar_svc.resolve_event(unlocked, args)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would respond {status!r} to event {ev_id}")
        return
    result = proton_app.calendar_svc.event_respond(unlocked, cal_id, ev_id, partstat)
    if result.reply:
        try:
            proton_app.mail_svc.send(
                unlocked,
                SendOptions(
                    to=result.reply.recipients,
                    subject=result.reply.subject,
                    body=result.reply.body,
                    inline_attachments=[
                        InlineAttachment(
                            filename="invite.ics",
                            mime_type="text/calendar; method=REPLY",
                            data=result.reply.ics.encode(),
                        )
                    ],
                ),
            )
        except Exception as exc:
            proton_app.renderer.info(f"responded, but notifying organizer failed: {exc}")
    name = result.title or ev_id
    proton_app.renderer.success(f"Responded {result.status!r} to {name!r}")


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
