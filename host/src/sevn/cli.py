"""``sevn serve``, ``sevn probe``, ``sevn doctor``, and ``sevn evals`` (D9, D13, D17)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Annotated, NoReturn, cast

import typer

import sevn.runtime.installs
import sevn.secrets
import sevn.system
from sevn import __version__
from sevn.config import Settings
from sevn.errors import ConfigError
from sevn.http import AppState, create_app, web_dist_path
from sevn.paths import Paths
from sevn.probe import ProbeError, call_method, events_since, parse_params
from sevn.secrets.backends import SecretBackend, backend_named, open_backend
from sevn.secrets.errors import SecretBackendReadOnly, SecretNotFound, SecretsBackendError
from sevn.service import ServiceError, ServiceManager, service_home, sevn_executable
from sevn.service import manager as service_manager

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
probe_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
contracts_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
secret_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
evals_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
service_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
runtimes_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(probe_app, name="probe")
app.add_typer(contracts_app, name="contracts")
app.add_typer(secret_app, name="secret")
app.add_typer(evals_app, name="evals")
app.add_typer(service_app, name="service", help="Run the host as a launchd or systemd service.")
app.add_typer(runtimes_app, name="runtimes", help="Install pinned copies of the CLI runtimes.")

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
    _require_secrets(settings)
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
    """Print host paths, the secret backend, decision routing, Claude login, and host checks."""
    settings = _settings()
    paths = Paths.from_env()
    checks = sevn.system.run_checks(_host_checks(settings, paths))
    claude_present, claude_login = _run(_claude_login())
    decisions = settings.decisions
    payload: dict[str, object] = {
        "home": str(paths.home.resolve()),
        "db": str(paths.db),
        "secrets_backend": checks.pop("secrets_backend"),
        "web_dist": str(web_dist_path()),
        "version": __version__,
        "claude_present": claude_present,
        "claude_login": claude_login,
        "jev_key": _jev_key(settings, paths),
        "ollama": _ollama_reachable(),
        "allow_cli_fallback": decisions.allow_cli_fallback,
        "decisions_provider": decisions.provider,
    }
    payload.update(checks)
    if as_json:
        typer.echo(json.dumps(payload))
        return
    for key, value in payload.items():
        typer.echo(f"{key}: {_doctor_text(value)}")


@secret_app.command("set")
def secret_set(name: str) -> None:
    """Store one secret. The value is read without echo and is never printed."""
    import getpass

    value = getpass.getpass("Secret: ")
    if value == "":
        typer.echo("secret value is empty", err=True)
        raise typer.Exit(code=1)
    settings = _settings()
    paths = Paths.from_env()
    chosen = sevn.secrets.selected_backend(settings, paths)
    try:
        backend_named(chosen, paths).set(name, value)
    except (SecretBackendReadOnly, SecretsBackendError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if settings.secrets.backend is None and chosen == "secret-service":
        _pin_secret_service(paths)
    typer.echo(f"stored {name}")


@secret_app.command("list")
def secret_list() -> None:
    """Print secret names. Values stay in the backend."""
    try:
        names = _open_secrets().names()
    except SecretsBackendError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    for name in names:
        typer.echo(name)


@secret_app.command("rm")
def secret_rm(name: str) -> None:
    """Delete one secret by name."""
    try:
        _open_secrets().delete(name)
    except (SecretNotFound, SecretBackendReadOnly, SecretsBackendError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"removed {name}")


@secret_app.command("migrate")
def secret_migrate(
    to: Annotated[str, typer.Option("--to", help="secret-service or age-file")],
) -> None:
    """Move every secret (and the host identity) to another backend, then switch to it.

    Each secret is read back from the target before ``secrets.backend`` is written to
    config.toml, and the source copies are deleted only after that.
    """
    from sevn.secrets.migrate import MigrationError, migrate

    settings = _settings()
    if os.environ.get("SEVN_SECRETS__BACKEND", "").strip():
        typer.echo(
            "SEVN_SECRETS__BACKEND is set and overrides config.toml; unset it after migrating",
            err=True,
        )
    try:
        outcome = migrate(settings, Paths.from_env(), to)
    except MigrationError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    count = len(outcome.names)
    noun = "secret" if count == 1 else "secrets"
    typer.echo(f"migrated {count} {noun} from {outcome.source} to {outcome.target}")
    if outcome.leftovers:
        typer.echo(
            f"could not delete the {outcome.source} copies of: {', '.join(outcome.leftovers)}",
            err=True,
        )
        raise typer.Exit(code=1)


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


@service_app.command("install")
def service_install(
    home: Annotated[Path | None, typer.Option("--home")] = None,
    port: Annotated[int | None, typer.Option("--port", min=1, max=65535)] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Install and start the host as a launchd agent (macOS) or systemd user unit (Linux)."""
    manager = _service_manager()
    try:
        outcome = manager.install(sevn_executable(), service_home(home), port, force=force)
    except ServiceError as exc:
        _service_fail(exc)
    if outcome.action == "unchanged":
        typer.echo(f"{outcome.path} unchanged")
    else:
        verb = "replaced" if outcome.action == "replace" else "installed"
        typer.echo(f"{verb} {outcome.path}")
    for hint in outcome.hints:
        typer.echo(hint)


@service_app.command("uninstall")
def service_uninstall() -> None:
    """Stop the service and remove its unit or plist."""
    manager = _service_manager()
    try:
        outcome = manager.uninstall()
    except ServiceError as exc:
        _service_fail(exc)
    for warning in outcome.warnings:
        typer.echo(warning, err=True)
    typer.echo(f"removed {outcome.path}" if outcome.removed else "not-installed")


@service_app.command("status")
def service_status(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Print running, stopped, failed or not-installed, with the last exit code."""
    manager = _service_manager()
    try:
        status = manager.status()
    except ServiceError as exc:
        _service_fail(exc)
    if as_json:
        typer.echo(json.dumps(status.to_json()))
        return
    if status.exit_code is None:
        typer.echo(status.state)
    else:
        typer.echo(f"{status.state} (exit code {status.exit_code})")


@service_app.command("logs")
def service_logs(follow: Annotated[bool, typer.Option("--follow", "-f")] = False) -> None:
    """Show the service log (journalctl on Linux, the launchd log file on macOS)."""
    manager = _service_manager()
    try:
        text = manager.logs(follow=follow)
    except ServiceError as exc:
        _service_fail(exc)
    if text:
        typer.echo(text, nl=not text.endswith("\n"))


@service_app.command("restart")
def service_restart() -> None:
    """Restart the service."""
    manager = _service_manager()
    try:
        manager.restart()
    except ServiceError as exc:
        _service_fail(exc)
    typer.echo("restarted")


@runtimes_app.command("install")
def runtimes_install(
    name: Annotated[str | None, typer.Argument()] = None,
    install_all: Annotated[bool, typer.Option("--all")] = False,
    version: Annotated[str | None, typer.Option("--version")] = None,
    sha256: Annotated[str | None, typer.Option("--sha256")] = None,
) -> None:
    """Download, verify and install a pinned CLI runtime, then make it current.

    A version outside the manifest needs ``--sha256``.
    """
    installs = sevn.runtime.installs
    if (name is None) == (not install_all):
        typer.echo("pass a runtime name or --all", err=True)
        raise typer.Exit(code=2)
    if install_all and (version is not None or sha256 is not None):
        typer.echo("--version and --sha256 need a runtime name, not --all", err=True)
        raise typer.Exit(code=2)
    try:
        names = list(installs.load_manifest().runtimes) if name is None else [name]
        for runtime in names:
            typer.echo(f"installing {runtime}…")
            path = installs.install(runtime, version=version, sha256=sha256)
            typer.echo(f"installed {runtime} {path.name} in {path}")
    except (installs.InstallError, ConfigError) as exc:
        _runtimes_fail(exc)


@runtimes_app.command("list")
def runtimes_list(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Show the managed versions, the system copy and which one the host uses."""
    installs = sevn.runtime.installs
    report: dict[str, dict[str, object]] = {}
    try:
        for runtime in installs.load_manifest().runtimes:
            found = installs.installed(runtime)
            system = shutil.which(runtime)
            used = installs.resolve(runtime)
            report[runtime] = {
                "managed": list(found.versions),
                "current": found.current,
                "system": system if system is not None and Path(system).is_absolute() else None,
                "used": "none" if used is None else used.source,
            }
    except (installs.InstallError, ConfigError) as exc:
        _runtimes_fail(exc)
    if as_json:
        typer.echo(json.dumps(report))
        return
    for runtime, entry in report.items():
        versions = cast("list[str]", entry["managed"])
        typer.echo(
            f"{runtime}: uses {entry['used']}; current {entry['current'] or '-'}; "
            f"managed {', '.join(versions) or '-'}; system {entry['system'] or '-'}"
        )


@runtimes_app.command("remove")
def runtimes_remove(
    name: str,
    version: Annotated[str | None, typer.Option("--version")] = None,
) -> None:
    """Remove a managed version, or every managed version of a runtime.

    Refused while a turn of that runtime is running and ``current`` would go.
    """
    installs = sevn.runtime.installs
    try:
        installs.remove(name, version=version)
    except (installs.InstallError, ConfigError) as exc:
        _runtimes_fail(exc)
    typer.echo(f"removed {name}" if version is None else f"removed {name} {version}")


def _runtimes_fail(exc: Exception) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _service_manager() -> ServiceManager:
    try:
        return service_manager()
    except ServiceError as exc:
        _service_fail(exc)


def _service_fail(exc: ServiceError) -> NoReturn:
    typer.echo(exc.message, err=True)
    raise typer.Exit(code=exc.exit_code) from exc


def _open_secrets() -> SecretBackend:
    return open_backend(_settings(), Paths.from_env())


def _pin_secret_service(paths: Paths) -> None:
    """Pin ``secret-service`` in config.toml once secrets live there (D4).

    Without the pin, a later start with a locked keyring would select the age file and
    silently start on a fresh one (and a new host identity) instead of refusing.
    """
    try:
        path = sevn.secrets.pin_backend(paths, "secret-service")
    except (ConfigError, OSError) as exc:
        typer.echo(f"could not pin the secret backend: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f'pinned [secrets] backend = "secret-service" in {path}', err=True)


def _require_secrets(settings: Settings) -> None:
    """Refuse to start on a configured Secret Service that is locked or missing (D4).

    When no backend is configured and the selection picks the Secret Service, pin that
    choice in config.toml (see :func:`_pin_secret_service`).
    """
    paths = Paths.from_env()
    configured = settings.secrets.backend
    if configured is None:
        if sevn.secrets.selected_backend(settings, paths) == "secret-service":
            _pin_secret_service(paths)
        return
    if configured != "secret-service":
        return
    state = sevn.secrets.probe_secret_service()
    if state == "unlocked":
        return
    if state == "locked":
        message = (
            "secrets_locked: the Secret Service collection is locked; "
            "unlock it (log in to the desktop session) and start again"
        )
    else:
        message = (
            "secrets_unavailable: secrets.backend is secret-service but no Secret Service "
            "answered on the session bus; sevn will not fall back to another backend"
        )
    typer.echo(message, err=True)
    raise typer.Exit(code=1)


def _host_checks(settings: Settings, paths: Paths) -> dict[str, Callable[[], object]]:
    """The doctor checks that run concurrently, each bounded at 2 s (plan 0025 D7)."""
    system = sevn.system
    checks: dict[str, Callable[[], object]] = {
        "secrets_backend": lambda: _secrets_backend(settings, paths),
        "platform": lambda: system.probe_platform(),
        "service": lambda: system.probe_service(),
        "runtimes": _runtimes_report,
    }
    if sys.platform.startswith("linux"):
        checks["bubblewrap"] = lambda: system.probe_bubblewrap(in_container=system.in_container())
        checks["display"] = lambda: system.probe_display()
        checks["portals"] = lambda: system.probe_portals()
        checks["linger"] = lambda: system.probe_linger()
    else:
        for key in ("bubblewrap", "display", "portals", "linger"):
            checks[key] = lambda: system.NOT_APPLICABLE
    ordered = ("secrets_backend", "platform", "service", "bubblewrap", "display", "portals")
    keys = (*ordered, "linger", "runtimes")
    return {key: checks[key] for key in keys}


def _runtimes_report() -> dict[str, dict[str, str | None]]:
    report: dict[str, dict[str, str | None]] = {}
    for name in sevn.runtime.installs.RUNTIMES:
        found = sevn.runtime.installs.resolve(name)
        if found is None:
            report[name] = {"source": "none", "version": None}
        else:
            report[name] = {"source": found.source, "version": found.version}
    return report


def _doctor_text(value: object) -> str:
    if not isinstance(value, dict):
        return str(value)
    parts: list[str] = []
    for name, entry in cast("dict[str, object]", value).items():
        if isinstance(entry, dict):
            fields = cast("dict[str, object]", entry)
            words = [str(fields.get("source", "")), str(fields.get("version") or "")]
            parts.append(f"{name}={' '.join(word for word in words if word)}")
        else:
            parts.append(f"{name}={entry}")
    return ", ".join(parts)


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
    except SecretsBackendError:
        return "unknown"
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


def _secrets_backend(settings: Settings, paths: Paths) -> str:
    """The selected backend; a configured Secret Service that is not unlocked says so."""
    choice = sevn.secrets.selected_backend(settings, paths)
    if settings.secrets.backend == "secret-service":
        state = sevn.secrets.probe_secret_service()
        if state != "unlocked":
            return f"{choice} ({state})"
    return choice


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
