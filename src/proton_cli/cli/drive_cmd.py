"""``drive`` subcommands."""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from proton_cli.service.drive.service import UploadOptions

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="drive", no_args_is_help=True, add_completion=False)

items_app = typer.Typer(name="items", no_args_is_help=True, add_completion=False)
folders_app = typer.Typer(name="folders", no_args_is_help=True, add_completion=False)
trash_app = typer.Typer(name="trash", no_args_is_help=True, add_completion=False)
app.add_typer(items_app, name="items")
app.add_typer(folders_app, name="folders")
app.add_typer(trash_app, name="trash")


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


def _drive_ctx(proton_app: App):
    unlocked = proton_app.unlock()
    return proton_app.drive_svc.resolve(unlocked)


def _type_label(t: int) -> str:
    return "DIR" if t == 1 else "FILE"


@items_app.command("list")
def items_list(
    ctx: typer.Context,
    path: str = typer.Argument("/", help="Folder path"),
) -> None:
    """List folder contents (decrypted names)."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    rows = proton_app.drive_svc.list_children(dc, path)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"items": rows})
        return
    proton_app.renderer.table(
        ["TYPE", "SIZE", "NAME", "LINK_ID"],
        [[_type_label(r.type), str(r.size), r.name, r.link_id] for r in rows],
    )


@items_app.command("upload")
def items_upload(
    ctx: typer.Context,
    src: str = typer.Argument(..., help="Local file path or - for stdin"),
    dest: str = typer.Argument("/", help="Destination folder"),
    mime_type: str = typer.Option("application/octet-stream", "--mime-type"),
) -> None:
    """Upload a file (SRC=- reads from stdin)."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if src == "-":
        name = f"stdin-{int(time.time())}"
        data = sys.stdin.buffer.read()
        if proton_app.dry_run:
            proton_app.renderer.info(f"dry-run: would upload {name} to {dest}")
            return
        proton_app.drive_svc.upload(
            dc,
            dest,
            name,
            io.BytesIO(data),
            UploadOptions(mime_type=mime_type),
        )
        proton_app.renderer.success(f"Uploaded {name}")
        return

    local = Path(src)
    if not local.is_file():
        raise typer.BadParameter(f"{src} is not a file")
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would upload {local.name} to {dest}")
        return
    with local.open("rb") as handle:
        proton_app.drive_svc.upload(
            dc,
            dest,
            local.name,
            handle,
            UploadOptions(mime_type=mime_type),
        )
    proton_app.renderer.success(f"Uploaded {local.name}")


@items_app.command("download")
def items_download(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Remote file path"),
    output: str = typer.Option("", "--output", help="Output file (- for stdout)"),
) -> None:
    """Download and decrypt a file."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would download {path}")
        return
    if output == "-":
        buf = io.BytesIO()
        proton_app.drive_svc.download(dc, path, buf)
        sys.stdout.buffer.write(buf.getvalue())
        return
    target = Path(output or Path(path).name)
    with target.open("wb") as handle:
        proton_app.drive_svc.download(dc, path, handle)
    proton_app.renderer.success(f"Downloaded to {target}")


@items_app.command("trash")
def items_trash(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="File or folder path"),
) -> None:
    """Move an item to trash."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would trash {path}")
        return
    proton_app.drive_svc.delete(dc, path, permanent=False)
    proton_app.renderer.success("Moved to trash.")


@items_app.command("delete")
def items_delete(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="File or folder path"),
) -> None:
    """Permanently delete an item (trash then purge)."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would permanently delete {path}")
        return
    proton_app.drive_svc.delete(dc, path, permanent=True)
    proton_app.renderer.success("Permanently deleted.")


@folders_app.command("create")
def folders_create(
    ctx: typer.Context,
    path: str = typer.Argument(..., help="Folder path to create"),
) -> None:
    """Create a folder."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would create folder {path}")
        return
    proton_app.drive_svc.create_folder(dc, path)
    proton_app.renderer.success(f"Created folder {path}")


@trash_app.command("list")
def trash_list(ctx: typer.Context) -> None:
    """List trashed items."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    rows = proton_app.drive_svc.trash_list(dc)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"trash": rows})
        return
    if not rows:
        proton_app.renderer.info("(trash is empty)")
        return
    proton_app.renderer.table(
        ["LINK_ID", "TYPE", "SIZE"],
        [[r.link_id, _type_label(r.type), str(r.size)] for r in rows],
    )


@trash_app.command("restore")
def trash_restore(
    ctx: typer.Context,
    link_id: list[str] = typer.Argument(..., help="Link IDs to restore"),
) -> None:
    """Restore items from trash by link ID."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would restore {len(link_id)} item(s)")
        return
    proton_app.drive_svc.trash_restore(dc, list(link_id))
    proton_app.renderer.success(f"Restored {len(link_id)} item(s).")


@trash_app.command("empty")
def trash_empty(ctx: typer.Context) -> None:
    """Empty the trash."""
    proton_app = _run(ctx)
    dc = _drive_ctx(proton_app)
    if proton_app.dry_run:
        proton_app.renderer.info("dry-run: would empty trash")
        return
    proton_app.drive_svc.trash_empty(dc)
    proton_app.renderer.success("Trash emptied.")
