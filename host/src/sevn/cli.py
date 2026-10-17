"""``sevn serve``, ``sevn probe``, and ``sevn doctor`` (D9, D13)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from sevn import __version__
from sevn.config import Settings
from sevn.errors import ConfigError
from sevn.http import AppState, create_app, web_dist_path
from sevn.paths import Paths
from sevn.probe import ProbeError, call_method, events_since, parse_params

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
probe_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
contracts_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(probe_app, name="probe")
app.add_typer(contracts_app, name="contracts")

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
    """Print host paths, the secret backend, the version, and Claude login."""
    settings = _settings()
    paths = Paths.from_env()
    claude_present, claude_login = _run(_claude_login())
    payload = {
        "home": str(paths.home.resolve()),
        "db": str(paths.db),
        "secrets_backend": _secrets_backend(settings),
        "web_dist": str(web_dist_path()),
        "version": __version__,
        "claude_present": claude_present,
        "claude_login": claude_login,
    }
    if as_json:
        typer.echo(json.dumps(payload))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {value}")


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
