"""``pass`` subcommands."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

import typer

from proton_cli.service.pass_service.service import ItemPatch, NewItem

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="pass", no_args_is_help=True, add_completion=False)

vaults_app = typer.Typer(name="vaults", no_args_is_help=True, add_completion=False)
items_app = typer.Typer(name="items", no_args_is_help=True, add_completion=False)
secrets_app = typer.Typer(name="secrets", no_args_is_help=True, add_completion=False)
app.add_typer(vaults_app, name="vaults")
app.add_typer(items_app, name="items")
app.add_typer(secrets_app, name="secrets")


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


def _emit_credential_stdout(value: str) -> None:
    """Write a credential to stdout for CLI extract and secrets backend contracts."""
    fd = sys.stdout.fileno()
    os.write(fd, value.encode())
    if value and not value.endswith("\n"):
        os.write(fd, b"\n")


def _resolve_secret_value(value: str | None, *, prompt: str) -> str:
    """Read a secret from an explicit value, stdin, or a hidden prompt."""
    if value is not None and value != "-":
        return value
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data:
            return data.rstrip("\n")
    return typer.prompt(prompt, hide_input=True)


@vaults_app.command("list")
def vaults_list(ctx: typer.Context) -> None:
    """List Pass vaults."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    rows = proton_app.pass_svc.vaults_list(unlocked)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object(rows)
        return
    proton_app.renderer.table(
        ["SHARE_ID", "NAME", "OWNER", "SHARED", "MEMBERS"],
        [
            [v.share_id, v.name or v.vault_id, str(v.owner), str(v.shared), str(v.members)]
            for v in rows
        ],
    )
    proton_app.renderer.info(f"\n{len(rows)} vault(s)")


@vaults_app.command("create")
def vaults_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Vault name"),
) -> None:
    """Create a Pass vault."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would create vault {name!r}")
        return
    unlocked = proton_app.unlock()
    share_id = proton_app.pass_svc.vault_create(unlocked, name)
    if proton_app.renderer.format.value == "text":
        typer.echo(share_id)
        proton_app.renderer.success(f"Created vault {name!r}")
    else:
        proton_app.renderer.object({"share_id": share_id, "name": name})


@vaults_app.command("rename")
def vaults_rename(
    ctx: typer.Context,
    share_id: str = typer.Argument(..., help="Vault share ID"),
    name: str = typer.Option(..., "--name", help="New vault name"),
) -> None:
    """Rename a Pass vault."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would rename vault {share_id} to {name!r}")
        return
    unlocked = proton_app.unlock()
    proton_app.pass_svc.vault_rename(unlocked, share_id, name)
    proton_app.renderer.success("Vault renamed.")


@vaults_app.command("delete")
def vaults_delete(
    ctx: typer.Context,
    share_id: str = typer.Argument(..., help="Vault share ID"),
) -> None:
    """Delete a Pass vault."""
    proton_app = _run(ctx)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would delete vault {share_id}")
        return
    proton_app.pass_svc.vault_delete(share_id)
    proton_app.renderer.success("Vault deleted.")


@items_app.command("list")
def items_list(
    ctx: typer.Context,
    vault: str = typer.Option("", "--vault", help="Filter by vault name or ID"),
) -> None:
    """List Pass items across vaults."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    items = proton_app.pass_svc.items_list(unlocked, vault_filter=vault)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object(items)
        return
    proton_app.renderer.table(
        ["TYPE", "NAME", "USERNAME", "SHARE_ID", "ITEM_ID"],
        [
            [
                it.type,
                it.name,
                it.username or it.email,
                it.share_id,
                it.item_id,
            ]
            for it in items
        ],
    )
    proton_app.renderer.info(f"\n{len(items)} item(s)")


@items_app.command("get")
def items_get(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="Share ID + item ID, or search term"),
    item_id: str = typer.Argument(None, help="Item ID when using two-arg form"),
    extract: str = typer.Option("", "--extract", help="Emit one field only (e.g. password)"),
) -> None:
    """Get a decrypted Pass item by IDs or search REF."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    args = [ref] if item_id is None else [ref, item_id]
    share_id, resolved_item_id = proton_app.pass_svc.resolve_item(unlocked, args)
    item = proton_app.pass_svc.item_get(unlocked, share_id, resolved_item_id)
    if extract == "password":
        _emit_credential_stdout(item.password)
        return
    proton_app.renderer.object(item)


@items_app.command("create")
def items_create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Item name"),
    item_type: str = typer.Option("login", "--type", help="Item type (login)"),
    username: str = typer.Option("", "--username"),
    password: str | None = typer.Option(None, "--password", help="Omit to read stdin/prompt"),
    email: str = typer.Option("", "--email"),
    url: str = typer.Option("", "--url"),
    note: str = typer.Option("", "--note"),
    totp: str = typer.Option("", "--totp"),
    vault: str = typer.Option("", "--vault", help="Vault name or ID"),
) -> None:
    """Create a Pass item."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    share_id = proton_app.pass_svc.resolve_vault(unlocked, vault)
    secret = _resolve_secret_value(password, prompt="Password") if item_type == "login" else (password or "")
    new_item = NewItem(
        type=item_type,
        name=name,
        username=username,
        password=secret,
        email=email,
        url=url,
        note=note,
        totp=totp,
    )
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would create {item_type} {name!r} in {share_id}")
        return
    item_id = proton_app.pass_svc.item_create(unlocked, share_id, new_item)
    if proton_app.renderer.format.value == "text":
        typer.echo(item_id)
        proton_app.renderer.success(f"Created {item_type} {name!r}")
    else:
        proton_app.renderer.object({"item_id": item_id, "share_id": share_id, "name": name})


@items_app.command("edit")
def items_edit(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="Share ID + item ID, or search term"),
    item_id: str = typer.Argument(None),
    name: str | None = typer.Option(None, "--name"),
    username: str | None = typer.Option(None, "--username"),
    password: str | None = typer.Option(None, "--password", help="Omit to leave unchanged; use - for stdin"),
    email: str | None = typer.Option(None, "--email"),
    url: str | None = typer.Option(None, "--url"),
    note: str | None = typer.Option(None, "--note"),
    totp: str | None = typer.Option(None, "--totp"),
) -> None:
    """Edit a Pass item."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    args = [ref] if item_id is None else [ref, item_id]
    share_id, resolved_item_id = proton_app.pass_svc.resolve_item(unlocked, args)
    patch_password = password
    if password == "-":
        patch_password = _resolve_secret_value(None, prompt="Password")
    patch = ItemPatch(
        name=name,
        username=username,
        password=patch_password,
        email=email,
        url=url,
        note=note,
        totp=totp,
    )
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would edit {share_id}/{resolved_item_id}")
        return
    proton_app.pass_svc.item_edit(unlocked, share_id, resolved_item_id, patch)
    proton_app.renderer.success("Item updated.")


@items_app.command("delete")
def items_delete(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="Share ID + item ID, or search term"),
    item_id: str = typer.Argument(None),
) -> None:
    """Permanently delete a Pass item."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    args = [ref] if item_id is None else [ref, item_id]
    share_id, resolved_item_id = proton_app.pass_svc.resolve_item(unlocked, args)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would delete {share_id}/{resolved_item_id}")
        return
    proton_app.pass_svc.item_delete(share_id, resolved_item_id)
    proton_app.renderer.success("Item deleted.")


@items_app.command("trash")
def items_trash(
    ctx: typer.Context,
    ref: str = typer.Argument(...),
    item_id: str = typer.Argument(None),
) -> None:
    """Move a Pass item to trash."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    args = [ref] if item_id is None else [ref, item_id]
    share_id, resolved_item_id = proton_app.pass_svc.resolve_item(unlocked, args)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would trash {share_id}/{resolved_item_id}")
        return
    proton_app.pass_svc.item_trash(share_id, resolved_item_id)
    proton_app.renderer.success("Item trashed.")


@items_app.command("restore")
def items_restore(
    ctx: typer.Context,
    ref: str = typer.Argument(...),
    item_id: str = typer.Argument(None),
) -> None:
    """Restore a Pass item from trash."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    args = [ref] if item_id is None else [ref, item_id]
    share_id, resolved_item_id = proton_app.pass_svc.resolve_item(unlocked, args)
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would restore {share_id}/{resolved_item_id}")
        return
    proton_app.pass_svc.item_restore(share_id, resolved_item_id)
    proton_app.renderer.success("Item restored.")


@secrets_app.command("get")
def secrets_get(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Login item name"),
    vault: str = typer.Option("", "--vault", help="Vault name or ID"),
) -> None:
    """Emit login password for sevn secrets backend (stdout only)."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    vault_id = proton_app.pass_svc.resolve_vault(unlocked, vault) if vault else ""
    item = proton_app.pass_svc.find_login_by_name(unlocked, name, vault_filter=vault_id)
    if item is None or not item.password:
        raise typer.Exit(3)
    _emit_credential_stdout(item.password)


@secrets_app.command("set")
def secrets_set(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Login item name"),
    value: str | None = typer.Argument(None, help="Password value; omit or use - for stdin/prompt"),
    vault: str = typer.Option("", "--vault", help="Vault name or ID"),
) -> None:
    """Upsert login password for sevn secrets backend."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    secret = _resolve_secret_value(value, prompt="Password")
    item_id = proton_app.pass_svc.upsert_login_password(
        unlocked,
        name=name,
        password=secret,
        vault_filter=vault,
    )
    if proton_app.renderer.format.value == "text":
        typer.echo(item_id)
    else:
        proton_app.renderer.object({"item_id": item_id, "name": name})


@secrets_app.command("delete")
def secrets_delete(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Login item name"),
    vault: str = typer.Option("", "--vault", help="Vault name or ID"),
) -> None:
    """Delete login item used by sevn secrets backend."""
    proton_app = _run(ctx)
    unlocked = proton_app.unlock()
    vault_id = proton_app.pass_svc.resolve_vault(unlocked, vault) if vault else ""
    item = proton_app.pass_svc.find_login_by_name(unlocked, name, vault_filter=vault_id)
    if item is None:
        raise typer.Exit(0)
    proton_app.pass_svc.item_delete(item.share_id, item.item_id)
