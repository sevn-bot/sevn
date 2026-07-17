"""``contacts`` subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from proton_cli.service.contacts.service import NewContact

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="contacts", no_args_is_help=True, add_completion=False)


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


@app.command("list")
def contacts_list(ctx: typer.Context) -> None:
    """List contacts (decrypted)."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    rows = proton_app.contacts_svc.list_contacts(unlocked)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"contacts": rows})
        return
    proton_app.renderer.table(
        ["ID", "NAME", "EMAIL", "PHONE"],
        [[c.id, c.name, c.email, c.phone] for c in rows],
    )


@app.command("get")
def contacts_get(
    ctx: typer.Context,
    contact_ref: str = typer.Argument(..., help="Contact ID or search term"),
) -> None:
    """Get one contact."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cid = proton_app.contacts_svc.resolve_contact(unlocked, contact_ref)
    contact = proton_app.contacts_svc.get_contact(unlocked, cid)
    proton_app.renderer.object(contact)


@app.command("create")
def contacts_create(
    ctx: typer.Context,
    name: str = typer.Option("", "--name"),
    email: list[str] = typer.Option([], "--email"),
) -> None:
    """Create a contact."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would create contact {name!r}")
        return
    cid = proton_app.contacts_svc.create_contact(
        unlocked,
        NewContact(name=name, emails=list(email)),
    )
    if proton_app.renderer.format.value == "text":
        typer.echo(cid)
    proton_app.renderer.success(f"Created contact {name!r}")


@app.command("delete")
def contacts_delete(
    ctx: typer.Context,
    contact_ref: str = typer.Argument(..., help="Contact ID or search term"),
) -> None:
    """Delete a contact."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cid = proton_app.contacts_svc.resolve_contact(unlocked, contact_ref)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would delete contact {cid}")
        return
    proton_app.contacts_svc.delete_contacts([cid])
    proton_app.renderer.success("Contact deleted.")
