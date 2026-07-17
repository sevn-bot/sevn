"""``mail`` subcommands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from proton_cli.service.mail.service import ListOptions, SearchOptions, SendOptions

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="mail", no_args_is_help=True, add_completion=False)

messages_app = typer.Typer(name="messages", no_args_is_help=True, add_completion=False)
labels_app = typer.Typer(name="labels", no_args_is_help=True, add_completion=False)
app.add_typer(messages_app, name="messages")
app.add_typer(labels_app, name="labels")


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


@messages_app.command("list")
def messages_list(
    ctx: typer.Context,
    folder: str = typer.Option("inbox", "--folder"),
    page: int = typer.Option(0, "--page"),
    page_size: int = typer.Option(25, "--page-size"),
    unread: bool = typer.Option(False, "--unread"),
) -> None:
    """List messages in a folder."""
    proton_app = _run(ctx)
    rows, total = proton_app.mail_svc.list_messages(
        ListOptions(folder=folder, page=page, page_size=page_size, unread=unread)
    )
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"messages": rows, "total": total})
        return
    proton_app.renderer.table(
        ["ID", "FROM", "SUBJECT", "TIME", "UNREAD"],
        [
            [
                m.id,
                m.from_address or m.from_name,
                m.subject,
                str(m.time),
                str(m.unread),
            ]
            for m in rows
        ],
    )
    proton_app.renderer.info(f"\n{len(rows)} of {total} message(s)")


@messages_app.command("search")
def messages_search(
    ctx: typer.Context,
    keyword: str = typer.Option("", "--keyword"),
    sender: str = typer.Option("", "--from"),
    recipient: str = typer.Option("", "--to"),
    subject: str = typer.Option("", "--subject"),
    folder: str = typer.Option("all", "--folder"),
    after: str = typer.Option("", "--after", help="YYYY-MM-DD"),
    before: str = typer.Option("", "--before", help="YYYY-MM-DD"),
    limit: int = typer.Option(25, "--limit"),
    unread: bool = typer.Option(False, "--unread"),
) -> None:
    """Search messages."""
    proton_app = _run(ctx)
    rows, total = proton_app.mail_svc.search_messages(
        SearchOptions(
            keyword=keyword,
            sender=sender,
            recipient=recipient,
            subject=subject,
            folder=folder,
            after=after,
            before=before,
            limit=limit,
            unread=unread,
        )
    )
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"messages": rows, "total": total})
        return
    proton_app.renderer.table(
        ["ID", "FROM", "SUBJECT", "TIME"],
        [[m.id, m.from_address, m.subject, str(m.time)] for m in rows],
    )
    proton_app.renderer.info(f"\n{len(rows)} of {total} match(es)")


@messages_app.command("read")
def messages_read(
    ctx: typer.Context,
    message_id: str = typer.Argument(..., help="Message ID or search term"),
    body_only: bool = typer.Option(False, "--body-only", help="Print body to stdout"),
) -> None:
    """Read and decrypt one message."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    summaries, _ = proton_app.mail_svc.list_messages(ListOptions(folder="all", page_size=150))
    resolved = proton_app.mail_svc.resolve_message(message_id, summaries)
    full = proton_app.mail_svc.read_message(unlocked, resolved)
    if body_only:
        sys.stdout.write(full.body)
        if full.body and not full.body.endswith("\n"):
            sys.stdout.write("\n")
        return
    proton_app.renderer.object(full)


@messages_app.command("send")
def messages_send(
    ctx: typer.Context,
    to: list[str] = typer.Option(..., "--to", help="Recipient email (repeatable)"),
    subject: str = typer.Option(..., "--subject"),
    body: str = typer.Option("", "--body", help="Plain-text body"),
    body_file: str = typer.Option("", "--body-file", help="Read body from file; - for stdin"),
    html: bool = typer.Option(False, "--html"),
    attach: list[str] = typer.Option([], "--attach", help="Attachment file path (repeatable)"),
    attach_inline: list[str] = typer.Option(
        [], "--attach-inline", help="Inline image path (repeatable)"
    ),
) -> None:
    """Send an email with optional attachments."""
    proton_app = _run(ctx)
    text = body
    if body_file:
        text = sys.stdin.read() if body_file == "-" else Path(body_file).read_text(encoding="utf-8")
    if not text:
        raise typer.BadParameter("provide --body or --body-file")
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would send to {to!r} subject={subject!r}")
        return
    unlocked = proton_app.unlock()
    message_id = proton_app.mail_svc.send(
        unlocked,
        SendOptions(
            to=list(to),
            subject=subject,
            body=text,
            html=html,
            attachments=list(attach),
            inline_attach=list(attach_inline),
        ),
    )
    if proton_app.renderer.format.value == "text":
        proton_app.renderer.success("Message sent.")
    else:
        proton_app.renderer.object({"message_id": message_id})


attachments_app = typer.Typer(name="attachments", no_args_is_help=True, add_completion=False)
messages_app.add_typer(attachments_app, name="attachments")


@attachments_app.command("list")
def attachments_list(
    ctx: typer.Context,
    message_id: str = typer.Argument(..., help="Message ID"),
    include_inline: bool = typer.Option(False, "--include-inline"),
) -> None:
    """List attachments on a message."""
    proton_app = _run(ctx)
    rows = proton_app.mail_svc.attachments_list(message_id, include_inline=include_inline)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"attachments": rows})
        return
    proton_app.renderer.table(
        ["ID", "NAME", "SIZE", "MIME"],
        [[a.id, a.name, str(a.size), a.mime_type] for a in rows],
    )


@attachments_app.command("download")
def attachments_download(
    ctx: typer.Context,
    message_id: str = typer.Argument(..., help="Message ID"),
    attachment_id: str = typer.Argument(..., help="Attachment ID"),
    output: str = typer.Option("", "--output", help="Output file path"),
) -> None:
    """Download and decrypt one attachment."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    data, name = proton_app.mail_svc.attachment_download(unlocked, message_id, attachment_id)
    if output:
        Path(output).write_bytes(data)
        proton_app.renderer.success(f"Wrote {output}")
        return
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"name": name, "size": len(data)})
        return
    sys.stdout.buffer.write(data)


@messages_app.command("trash")
def messages_trash(
    ctx: typer.Context,
    message_id: str = typer.Argument(..., help="Message ID"),
) -> None:
    """Move a message to trash."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would trash {message_id}")
        return
    proton_app.mail_svc.trash([message_id])
    proton_app.renderer.success("Trashed.")


@messages_app.command("delete")
def messages_delete(
    ctx: typer.Context,
    message_id: str = typer.Argument(..., help="Message ID"),
) -> None:
    """Permanently delete a message."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would delete {message_id}")
        return
    proton_app.mail_svc.delete([message_id])
    proton_app.renderer.success("Deleted.")


@messages_app.command("move")
def messages_move(
    ctx: typer.Context,
    message_id: str = typer.Argument(..., help="Message ID"),
    folder: str = typer.Option(..., "--folder", help="Target folder"),
) -> None:
    """Move a message to another folder."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would move {message_id} to {folder}")
        return
    proton_app.mail_svc.move([message_id], folder)
    proton_app.renderer.success("Moved.")


@labels_app.command("list")
def labels_list(ctx: typer.Context) -> None:
    """List labels and folders."""
    proton_app = _run(ctx)
    labels, folders = proton_app.mail_svc.labels_list()
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"labels": labels, "folders": folders})
        return
    proton_app.renderer.table(
        ["ID", "NAME", "TYPE"],
        [[entry.id, entry.name, str(entry.type)] for entry in labels + folders],
    )
