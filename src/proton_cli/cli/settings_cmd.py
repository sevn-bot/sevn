"""``settings`` — account and mail settings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import typer

from proton_cli.proton.client import Request

if TYPE_CHECKING:
    from proton_cli.app import App

app = typer.Typer(name="settings", no_args_is_help=True, add_completion=False)

MAIL_SETTINGS: dict[str, tuple[str, str, bool, str]] = {
    "page-size": (
        "/mail/v4/settings/pagesize",
        "PageSize",
        True,
        "messages per page (50, 100, 200)",
    ),
    "view-mode": ("/mail/v4/settings/viewmode", "ViewMode", True, "0=conversations, 1=messages"),
    "sign": ("/mail/v4/settings/sign", "Sign", True, "0=off, 1=sign outgoing"),
    "attach-public-key": ("/mail/v4/settings/attachpublic", "AttachPublicKey", True, "0/1"),
    "auto-save-contacts": ("/mail/v4/settings/autocontacts", "AutoSaveContacts", True, "0/1"),
    "hide-remote-images": ("/mail/v4/settings/hide-remote-images", "HideRemoteImages", True, "0/1"),
    "draft-type": ("/mail/v4/settings/drafttype", "MIMEType", False, "text/html or text/plain"),
    "pm-signature": ("/mail/v4/settings/pmsignature", "PMSignature", True, "0=off, 1=on"),
    "delay-send": ("/mail/v4/settings/delaysend", "DelaySendSeconds", True, "seconds (0-20)"),
}


def _run(ctx: typer.Context) -> App:
    proton_app: App = ctx.obj
    proton_app.authenticate()
    return proton_app


@app.command("get")
def settings_get(ctx: typer.Context) -> None:
    """Show current account settings."""
    proton_app = _run(ctx)
    resp = proton_app.api.do(Request(method="GET", path="/core/v4/settings"))
    data = json.loads(resp.body)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object(data)
        return
    user = data.get("UserSettings") or {}
    lines = [
        ("Locale", str(user.get("Locale", ""))),
        ("Telemetry", str(user.get("Telemetry", ""))),
        ("CrashReports", str(user.get("CrashReports", ""))),
    ]
    proton_app.renderer.table(["KEY", "VALUE"], [[k, v] for k, v in lines if v])


@app.command("mail")
def settings_mail(ctx: typer.Context) -> None:
    """Show mail settings."""
    proton_app = _run(ctx)
    resp = proton_app.api.do(Request(method="GET", path="/mail/v4/settings"))
    data = json.loads(resp.body)
    if proton_app.renderer.format.value != "text":
        proton_app.renderer.object(data)
        return
    ms = data.get("MailSettings") or {}
    rows = [
        ("Display Name", str(ms.get("DisplayName", ""))),
        ("Page Size", str(ms.get("PageSize", ""))),
        ("View Mode", str(ms.get("ViewMode", ""))),
        ("Draft MIME Type", str(ms.get("DraftMIMEType", ""))),
        ("PM Signature", str(ms.get("PMSignature", ""))),
        ("Sign Outgoing", str(ms.get("Sign", ""))),
    ]
    proton_app.renderer.table(["KEY", "VALUE"], [[k, v] for k, v in rows])


@app.command("set")
def settings_set(
    ctx: typer.Context,
    key: str = typer.Argument("", help="Setting key (omit to list keys)"),
    value: str = typer.Argument("", help="New value"),
) -> None:
    """Update a mail setting (run without args to list keys)."""
    proton_app = _run(ctx)
    if not key:
        rows = sorted((k, spec[3]) for k, spec in MAIL_SETTINGS.items())
        proton_app.renderer.table(["KEY", "DESCRIPTION"], list(rows))
        return
    spec = MAIL_SETTINGS.get(key)
    if spec is None:
        raise typer.BadParameter(
            f"unknown setting {key!r}; run `settings set` with no args to list keys"
        )
    path, field, is_int, _desc = spec
    if proton_app.dry_run:
        proton_app.renderer.info(f"dry-run: would set {key} = {value}")
        return
    if is_int:
        try:
            parsed: int | str = int(value)
        except ValueError as exc:
            raise typer.BadParameter(f"setting {key!r} expects an integer value") from exc
    else:
        parsed = value
    proton_app.api.decode(
        Request(method="PUT", path=path, body={field: parsed}),
    )
    proton_app.renderer.success(f"Set {key} = {value}")
