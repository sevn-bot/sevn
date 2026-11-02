"""``sevn serve``, ``sevn probe``, ``sevn doctor``, and ``sevn evals`` (D9, D13, D17)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer

from sevn import __version__
from sevn.config import Settings
from sevn.errors import ConfigError
from sevn.http import AppState, create_app, web_dist_path
from sevn.paths import Paths
from sevn.probe import ProbeError, call_method, events_since, parse_params
from sevn.secrets.backends import AgeFileBackend, EnvBackend, KeychainBackend, open_backend
from sevn.secrets.errors import SecretBackendReadOnly, SecretNotFound

if TYPE_CHECKING:
    from sevn.identity.devices import DeviceRecord
    from sevn.identity.pairing import Ticket
    from sevn.protocol.errors import Scope

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
probe_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
contracts_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
secret_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
evals_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(probe_app, name="probe")
app.add_typer(contracts_app, name="contracts")
app.add_typer(secret_app, name="secret")
app.add_typer(evals_app, name="evals")
devices_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(devices_app, name="devices")

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


@app.command()
def serve(
    home: Annotated[Path | None, typer.Option("--home")] = None,
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    open_browser: Annotated[bool, typer.Option("--open")] = False,
    allow_remote_bind: Annotated[bool, typer.Option("--allow-remote-bind")] = False,
) -> None:
    """Serve the host on loopback unless ``--allow-remote-bind`` is set."""
    _apply_home(home)
    settings = _settings()
    bind_host = "127.0.0.1" if host is None else host
    bind_port = settings.http.port if port is None else port
    if bind_host not in _LOOPBACK and not allow_remote_bind:
        typer.echo(f"refusing to bind {bind_host}: pass --allow-remote-bind", err=True)
        raise typer.Exit(code=2)
    from sevn.log import setup

    paths = Paths.from_env()
    setup("INFO", paths.logs / "sevn.json")
    api = create_app(settings)
    state = _app_state(api)
    state.runtime.host = bind_host
    state.runtime.port = bind_port
    state.runtime.open_browser = open_browser
    import uvicorn

    uvicorn.run(
        api,
        host=bind_host,
        port=bind_port,
        log_level="info",
        log_config=None,
    )


@probe_app.command("call")
def probe_call(
    method: str,
    params: str,
    home: Annotated[Path | None, typer.Option("--home")] = None,
) -> None:
    """Call one method and print its result JSON."""
    _apply_home(home)
    _settings()
    try:
        body = parse_params(params)
        result = _run(call_method(method, body))
    except ProbeError as exc:
        _fail(exc)
    typer.echo(json.dumps(result))


@probe_app.command("events")
def probe_events(
    since: Annotated[int, typer.Option("--since")],
    home: Annotated[Path | None, typer.Option("--home")] = None,
) -> None:
    """Print durable events with ``seq`` greater than ``--since``."""
    _apply_home(home)
    _settings()
    try:
        result = _run(events_since(since))
    except ProbeError as exc:
        _fail(exc)
    typer.echo(json.dumps(result))


@contracts_app.command("export")
def contracts_export(
    root: Annotated[Path | None, typer.Option("--root")] = None,
) -> None:
    """Write ``protocol.schema.json`` and the TypeScript method table (D18)."""
    from sevn.contracts.export import export_contracts

    export_contracts(Path.cwd() if root is None else root)


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print host paths, the secret backend, decision routing, and Claude login."""
    settings = _settings()
    paths = Paths.from_env()
    claude_present, claude_login = _run(_claude_login())
    decisions = settings.decisions
    payload = {
        "home": str(paths.home.resolve()),
        "db": str(paths.db),
        "secrets_backend": _secrets_backend(settings),
        "web_dist": str(web_dist_path()),
        "version": __version__,
        "claude_present": claude_present,
        "claude_login": claude_login,
        "jev_key": _jev_key(settings, paths),
        "ollama": _ollama_reachable(),
        "allow_cli_fallback": decisions.allow_cli_fallback,
        "decisions_provider": decisions.provider,
    }
    if as_json:
        typer.echo(json.dumps(payload))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {value}")


@secret_app.command("set")
def secret_set(name: str) -> None:
    """Store one secret. The value is read without echo and is never printed."""
    import getpass

    value = getpass.getpass("Secret: ")
    if value == "":
        typer.echo("secret value is empty", err=True)
        raise typer.Exit(code=1)
    try:
        _open_secrets().set(name, value)
    except SecretBackendReadOnly as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stored {name}")


@secret_app.command("list")
def secret_list() -> None:
    """Print secret names. Values stay in the backend."""
    for name in _open_secrets().names():
        typer.echo(name)


@secret_app.command("rm")
def secret_rm(name: str) -> None:
    """Delete one secret by name."""
    try:
        _open_secrets().delete(name)
    except (SecretNotFound, SecretBackendReadOnly) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"removed {name}")


@evals_app.command("run")
def evals_run(suite: str) -> None:
    """Replay one synthetic suite. Nothing runs unless ``evals_on`` is set."""
    if suite != "decisions":
        typer.echo(f"unknown eval suite: {suite}", err=True)
        raise typer.Exit(code=2)
    from sevn.evals.decisions import run_decisions
    from sevn.evals.errors import EvalsError

    try:
        outcome = run_decisions()
    except EvalsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if outcome.disabled:
        typer.echo("evals disabled")


_PAIR_SCOPES: dict[str, Scope] = {"owner": "owner", "member": "member", "read_only": "read_only"}


@app.command()
def pair(
    scope: Annotated[str, typer.Option("--scope")] = "member",
    name: Annotated[str | None, typer.Option("--name")] = None,
    home: Annotated[Path | None, typer.Option("--home")] = None,
) -> None:
    """Print a one-time pairing code, URI and QR (plan 0055 D1). No host needs to run."""
    _apply_home(home)
    settings = _settings()
    chosen = _PAIR_SCOPES.get(scope)
    if chosen is None:
        typer.echo(f"unknown scope {scope}: use owner, member or read_only", err=True)
        raise typer.Exit(code=2)
    ticket = _run(_pair_ticket(settings, chosen, name))
    # The code comes first: it is what a browser user types.
    typer.echo(f"Pairing code: {ticket.short_code}")
    typer.echo(f"Scope: {chosen}, expires {ticket.expires_at:%H:%M:%S} UTC")
    typer.echo(ticket.qr_uri)
    typer.echo(_qr_text(ticket.qr_uri))


@devices_app.command("list")
def devices_list(
    as_json: Annotated[bool, typer.Option("--json")] = False,
    home: Annotated[Path | None, typer.Option("--home")] = None,
) -> None:
    """List paired devices from the store. No host needs to run."""
    _apply_home(home)
    _settings()
    rows = _run(_devices_list())
    if as_json:
        typer.echo(json.dumps([row.model_dump(mode="json") for row in rows]))
        return
    for row in rows:
        state = "revoked" if row.revoked_at is not None else "active"
        typer.echo(f"{row.id}  {row.scope:<9}  {state:<7}  {row.name} ({row.platform})")


@devices_app.command("revoke")
def devices_revoke(
    device_id: str,
    home: Annotated[Path | None, typer.Option("--home")] = None,
) -> None:
    """Revoke a device. A running host revokes it and closes its live sessions at once."""
    from sevn.identity.devices import DeviceError

    _apply_home(home)
    _settings()
    try:
        record = _run(_devices_revoke(device_id))
    except DeviceError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"revoked {record.id}")


async def _store_ready() -> None:
    from sevn.store.db import upgrade

    await upgrade(f"sqlite+aiosqlite:///{Paths.from_env().db}")


async def _pair_ticket(settings: Settings, scope: Scope, name: str | None) -> Ticket:
    from sevn.identity import load_or_create
    from sevn.identity.pairing import start

    await _store_ready()
    identity = load_or_create(open_backend(settings, Paths.from_env()))
    return await start(identity=identity, http=settings.http, scope=scope, name=name)


async def _devices_list() -> list[DeviceRecord]:
    from sevn.identity.devices import list_devices

    await _store_ready()
    return await list_devices()


async def _devices_revoke(device_id: str) -> DeviceRecord:
    from sevn.identity.devices import revoke

    live = await _devices_revoke_live(device_id)
    if live is not None:
        return live
    await _store_ready()
    # The host's own CLI is local, so it may revoke the last owner device.
    return await revoke(device_id, allow_last_owner=True)


async def _devices_revoke_live(device_id: str) -> DeviceRecord | None:
    """Revoke through a running host's hub, which closes the device's live sessions (D2).

    ``None`` when no host answers for this home; the caller then writes offline.
    """
    import secrets

    from sevn.identity.devices import DeviceError, DeviceRecord
    from sevn.probe import HostRefused

    run = Paths.from_env().run
    if not (run / "token").is_file() or not (run / "bind").is_file():
        return None
    try:
        result = await call_method(
            "devices.revoke", {"id": device_id, "op_id": "op_cli_" + secrets.token_hex(8)}
        )
    except HostRefused as exc:
        # The host answered: its refusal stands, and nothing is written offline.
        if exc.code == "not_found":
            raise DeviceError("not_found", str(exc)) from exc
        if exc.code == "last_owner":
            raise DeviceError("last_owner", str(exc)) from exc
        raise DeviceError("internal", str(exc)) from exc
    except ProbeError:
        return None
    return DeviceRecord.model_validate(result)


def _qr_text(data: str) -> str:
    import io

    import segno

    out = io.StringIO()
    segno.make(data, error="m").terminal(out=out, compact=True)
    return out.getvalue()


def _open_secrets() -> KeychainBackend | AgeFileBackend | EnvBackend:
    return open_backend(_settings(), Paths.from_env())


def _apply_home(home: Path | None) -> None:
    if home is not None:
        os.environ["SEVN_HOME"] = str(home)


def _settings() -> Settings:
    try:
        return Settings.load()
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


async def _claude_login() -> tuple[bool, int | None]:
    """Whether ``claude`` is on PATH, and the ``claude auth status`` exit code.

    The status text is discarded. A missing binary or a timed-out process
    reports no exit code.
    """
    binary = shutil.which("claude")
    if binary is None or not Path(binary).is_absolute():
        return False, None
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "auth",
            "status",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return True, None
    try:
        code = await asyncio.wait_for(process.wait(), timeout=15)
    except TimeoutError:
        process.kill()
        await process.wait()
        return True, None
    return True, code


def _jev_key(settings: Settings, paths: Paths) -> str:
    """``yes`` when a TypeSafe key is configured. The value is not printed."""
    if os.environ.get("TYPESAFE_API_KEY", "").strip() != "":
        return "yes"
    try:
        open_backend(settings, paths).get("provider/typesafe")
    except SecretNotFound:
        return "no"
    return "yes"


def _ollama_reachable() -> str:
    """``yes`` when ``SEVN_OLLAMA_URL`` answers. A missing or dead URL is ``no``."""
    url = os.environ.get("SEVN_OLLAMA_URL", "").strip()
    if url == "":
        return "no"
    import httpx

    try:
        response = httpx.get(url, timeout=2.0)
    except (httpx.HTTPError, OSError):
        return "no"
    if response.status_code >= 400:
        return "no"
    return "yes"


def _secrets_backend(settings: Settings) -> str:
    choice = settings.secrets.backend
    if choice is not None:
        return choice
    if sys.platform == "darwin":
        return "keychain"
    return "age-file"


def _run[T](main: Coroutine[object, object, T]) -> T:
    return asyncio.run(main)


def _fail(exc: ProbeError) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1)


def _app_state(api: object) -> AppState:
    state = getattr(getattr(api, "state", None), "sevn", None)
    if not isinstance(state, AppState):
        raise RuntimeError("sevn app state is missing")
    return state
