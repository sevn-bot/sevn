"""``contacts`` subcommands."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from proton_cli.service.contacts.service import NewContact

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="contacts", no_args_is_help=True, add_completion=False)
groups_app = typer.Typer(name="groups", no_args_is_help=True, add_completion=False)
app.add_typer(groups_app, name="groups")


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
    proton_app.contacts_svc.create_contact(
        unlocked,
        NewContact(name=name, emails=list(email)),
    )
    if proton_app.renderer.format.value == "text":
        pass
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


@groups_app.command("list")
def groups_list(ctx: typer.Context) -> None:
    """List contact groups."""
    proton_app = _run(ctx)
    rows = proton_app.contacts_svc.groups_list()
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object({"groups": rows})
        return
    proton_app.renderer.table(
        ["ID", "NAME", "COLOR"],
        [[g.id, g.name, g.color] for g in rows],
    )


@groups_app.command("create")
def groups_create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Group name"),
    color: str = typer.Option("", "--color"),
) -> None:
    """Create a contact group."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would create group {name!r}")
        return
    proton_app.contacts_svc.group_create(name, color)
    if proton_app.renderer.format.value == "text":
        pass
    proton_app.renderer.success(f"Created group {name!r}")


@groups_app.command("delete")
def groups_delete(
    ctx: typer.Context,
    group_id: str = typer.Argument(..., help="Group ID"),
) -> None:
    """Delete a contact group."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would delete group {group_id}")
        return
    proton_app.contacts_svc.group_delete(group_id)
    proton_app.renderer.success("Group deleted.")


@groups_app.command("add")
def groups_add(
    ctx: typer.Context,
    group_id: str = typer.Argument(..., help="Group ID"),
    contact_ref: str = typer.Argument(..., help="Contact ID or search term"),
) -> None:
    """Add a contact to a group."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cid = proton_app.contacts_svc.resolve_contact(unlocked, contact_ref)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would add contact {cid} to group {group_id}")
        return
    proton_app.contacts_svc.group_add(group_id, [cid])
    proton_app.renderer.success("Contact added to group.")


@groups_app.command("remove")
def groups_remove(
    ctx: typer.Context,
    group_id: str = typer.Argument(..., help="Group ID"),
    contact_ref: str = typer.Argument(..., help="Contact ID or search term"),
) -> None:
    """Remove a contact from a group."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cid = proton_app.contacts_svc.resolve_contact(unlocked, contact_ref)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would remove contact {cid} from group {group_id}")
        return
    proton_app.contacts_svc.group_remove(group_id, [cid])
    proton_app.renderer.success("Contact removed from group.")


@app.command("pin-key")
def contacts_pin_key(
    ctx: typer.Context,
    contact_ref: str = typer.Argument(..., help="Contact ID or search term"),
    key_path: str = typer.Option(..., "--key", help="Armored public key file (- for stdin)"),
    email: str = typer.Option("", "--email", help="Which email to pin the key to"),
    scheme: str = typer.Option("", "--scheme", help="pgp-mime or pgp-inline"),
    no_encrypt: bool = typer.Option(False, "--no-encrypt"),
) -> None:
    """Pin a public key to a contact email."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    if scheme and scheme not in ("pgp-mime", "pgp-inline"):
        raise typer.BadParameter("invalid --scheme (use pgp-mime or pgp-inline)")
    armored = sys.stdin.read() if key_path == "-" else Path(key_path).read_text(encoding="utf-8")
    cid = proton_app.contacts_svc.resolve_contact(unlocked, contact_ref)
    contact = proton_app.contacts_svc.get_contact(unlocked, cid)
    target = email or contact.email
    if not target:
        raise typer.BadParameter("contact has no email; pass --email")
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would pin key for {target}")
        return
    encrypt = False if no_encrypt else None
    proton_app.contacts_svc.pin_key(unlocked, cid, target, armored, encrypt=encrypt, scheme=scheme)
    proton_app.renderer.success(f"Pinned key for {target}")


@app.command("unpin-key")
def contacts_unpin_key(
    ctx: typer.Context,
    contact_ref: str = typer.Argument(..., help="Contact ID or search term"),
    email: str = typer.Option("", "--email", help="Which email to unpin"),
) -> None:
    """Remove pinned key(s) from a contact email."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    cid = proton_app.contacts_svc.resolve_contact(unlocked, contact_ref)
    contact = proton_app.contacts_svc.get_contact(unlocked, cid)
    target = email or contact.email
    if not target:
        raise typer.BadParameter("contact has no email; pass --email")
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would unpin key for {target}")
        return
    proton_app.contacts_svc.unpin_key(unlocked, cid, target)
    proton_app.renderer.success(f"Removed pinned key for {target}")
