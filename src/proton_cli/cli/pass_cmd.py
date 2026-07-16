"""``pass`` subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="pass", no_args_is_help=True, add_completion=False)

vaults_app = typer.Typer(name="vaults", no_args_is_help=True, add_completion=False)
items_app = typer.Typer(name="items", no_args_is_help=True, add_completion=False)
app.add_typer(vaults_app, name="vaults")
app.add_typer(items_app, name="items")


@vaults_app.command("list")
def vaults_list(ctx: typer.Context) -> None:
    """List Pass vaults."""
    proton_app: App = ctx.obj
    proton_app.authenticate()
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


@items_app.command("list")
def items_list(
    ctx: typer.Context,
    vault: str = typer.Option("", "--vault", help="Filter by vault name or ID"),
) -> None:
    """List Pass items across vaults."""
    proton_app: App = ctx.obj
    proton_app.authenticate()
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
    share_id: str = typer.Argument(..., help="Share ID"),
    item_id: str = typer.Argument(..., help="Item ID"),
) -> None:
    """Get a decrypted Pass item."""
    proton_app: App = ctx.obj
    proton_app.authenticate()
    unlocked = proton_app.unlock()
    item = proton_app.pass_svc.item_get(unlocked, share_id, item_id)
    proton_app.renderer.object(item)
