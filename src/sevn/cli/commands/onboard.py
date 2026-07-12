"""``sevn onboard`` argv façade (`specs/23-cli.md` §2.5, `specs/22-onboarding.md`).
Module: sevn.cli.commands.onboard
Depends: asyncio, json, os, platform, secrets, sys, threading, webbrowser, pathlib, typer,
    yaml, uvicorn, sevn.onboarding, sevn.config.*
Exports:
    register — attach ``onboard`` command.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

import typer
import yaml

from sevn.cli.workspace import bound_sevn_json_path
from sevn.config.defaults import ONBOARDING_WIZARD_BIND_HOST
from sevn.onboarding.export_bundle import ExportBundleError, bundle_seed_secrets, parse_export_text
from sevn.onboarding.fast_onboard import (
    FastOnboardError,
    FastOnboardPreconditionError,
    FastOnboardValidationError,
    run_fast_onboard,
)
from sevn.onboarding.install_gate import (
    apply_install_resolution,
    install_gate_state,
    prompt_install_gate_tty,
    prompt_keystore_passphrase_tty,
)
from sevn.onboarding.profiles import load_profile_fragment
from sevn.onboarding.web_app import create_onboarding_app

_CONFIG_SUFFIXES = frozenset({".json", ".yaml", ".yml"})


def _looks_like_config_path(value: str) -> bool:
    """Return True when ``value`` is likely a config file path, not a profile id.

    Args:
        value (str): ``--profile`` value or positional token.

    Returns:
        bool: ``True`` for ``*.json`` / ``*.yaml`` paths or existing files.

    Examples:
        >>> _looks_like_config_path("sevn_test.json")
        True
        >>> _looks_like_config_path("good_value_osx")
        False
    """
    text = value.strip()
    if not text:
        return False
    path = Path(text)
    if path.suffix.lower() in _CONFIG_SUFFIXES:
        return True
    return path.expanduser().is_file()


def _profile_bad_parameter(profile: str, exc: Exception) -> typer.BadParameter:
    """Build a ``BadParameter`` for unknown profile, hinting ``--config`` when appropriate.

    Args:
        profile (str): Supplied ``--profile`` value.
        exc (Exception): Underlying ``load_profile_fragment`` error.

    Returns:
        typer.BadParameter: CLI usage error.

    Examples:
        >>> isinstance(
        ...     _profile_bad_parameter("cfg.json", FileNotFoundError("x")),
        ...     typer.BadParameter,
        ... )
        True
    """
    if _looks_like_config_path(profile):
        msg = (
            f"{profile!r} looks like a config file path, not a preset profile id "
            f"(e.g. good_value_osx). Use: sevn onboard --config {profile}"
        )
        return typer.BadParameter(msg)
    return typer.BadParameter(f"unknown or invalid profile: {profile!r} ({exc})")


def _has_graphical_browser() -> bool:
    """Return True when a system browser is likely usable.
    Heuristic: macOS/Windows always have one; on Linux/other POSIX, require either
    ``$DISPLAY``, ``$WAYLAND_DISPLAY``, or ``$BROWSER`` to be set before defaulting
    to web. ``webbrowser.get`` succeeding is a final sanity check.
    Returns:
        bool: ``True`` when we should default to the web wizard.
    Examples:
        >>> isinstance(_has_graphical_browser(), bool)
        True
    """
    if os.environ.get("SEVN_FORCE_HEADLESS") == "1":
        return False
    system = platform.system()
    if system in ("Darwin", "Windows"):
        graphical = True
    else:
        graphical = bool(
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("BROWSER")
        )
    if not graphical:
        return False
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def register(app: typer.Typer) -> None:
    """Attach ``sevn onboard`` to ``app``.
    Args:
        app (typer.Typer): Root Typer application.
    Examples:
        >>> register(typer.Typer()) is None
        True
    """

    @app.command("onboard")
    def onboard(
        config_file: Path | None = typer.Argument(
            None,
            help=(
                "Config JSON/YAML path (same as ``--config``), or the literal ``fast`` to run "
                "``sevn onboard fast <export.env>`` from an exported bundle."
            ),
        ),
        fast_file: Path | None = typer.Argument(
            None,
            help="With ``onboard fast``: the .env bundle from ``sevn export-secrets``.",
        ),
        web: bool = typer.Option(
            False,
            "--web",
            help="Force the local web wizard (default when a graphical browser is detected).",
        ),
        cli_tui: bool = typer.Option(
            False,
            "--cli",
            help="Force the Textual TUI instead of the web wizard.",
        ),
        no_open: bool = typer.Option(
            False,
            "--no-open",
            help="Skip auto-opening the system browser for --web (print URL only).",
        ),
        install_daemon: bool = typer.Option(
            True,
            "--install-daemon/--no-install-daemon",
            help="After promote, install gateway+proxy launchd/systemd units (default on).",
        ),
        config_path: Path | None = typer.Option(
            None,
            "--config",
            help=(
                "Fast onboarding from a JSON/YAML file: schema + live validation, promote, "
                "seed workspace, install daemons, start proxy/gateway. Requires SEVN_* env "
                "for enabled Telegram/LLM (see --help)."
            ),
        ),
        bot_name: str | None = typer.Option(
            None,
            "--bot-name",
            help="Override agent.display_name (bot name) for narrative templates.",
        ),
        no_prompt_bot_name: bool = typer.Option(
            False,
            "--no-prompt-bot-name",
            help="Do not prompt for bot name on a TTY; require agent.display_name in file.",
        ),
        no_start_services: bool = typer.Option(
            False,
            "--no-start-services",
            help="Skip proxy/gateway handoff after promote (CI or manual start).",
        ),
        from_env: bool = typer.Option(
            False,
            "--from-env",
            help="Build draft from SEVN_* allowlist (stub).",
        ),
        profile: str | None = typer.Option(
            None,
            "--profile",
            help=(
                "Packaged preset id (e.g. good_value_osx), not a JSON file path — "
                "use ``--config`` or pass the file as a positional argument."
            ),
        ),
        host: str = typer.Option(
            ONBOARDING_WIZARD_BIND_HOST,
            "--host",
            help="Bind address for --web.",
        ),
        port: int = typer.Option(
            8844,
            "--port",
            help="Listen port for --web.",
        ),
    ) -> None:
        """Guided onboarding (web by default; ``--cli`` for the Textual TUI).

        ``--config PATH`` runs full fast onboarding when the file and environment pass
        schema, credential, and live validation checks. ``sevn onboard fast <export.env>``
        recreates a bot from a ``sevn export-secrets`` bundle.
        """
        from sevn.branding import maybe_play_logo_splash

        maybe_play_logo_splash()
        if config_file is not None and str(config_file) == "fast":
            _run_onboard_fast(
                fast_file=fast_file,
                install_daemon=install_daemon,
                start_services=not no_start_services,
            )
            return
        if fast_file is not None:
            raise typer.BadParameter(f"unexpected extra argument: {fast_file}")
        if web and cli_tui:
            raise typer.BadParameter("--web and --cli are mutually exclusive")
        if from_env:
            typer.secho(
                "`--from-env` is not implemented; use `--web`, `--cli`, or `--config` instead.",
                err=True,
            )
            raise typer.Exit(4)
        effective_config = config_path
        if config_file is not None:
            if effective_config is not None:
                raise typer.BadParameter(
                    "pass the config file once (positional or --config, not both)"
                )
            effective_config = config_file
        ran_validate_only = False
        if profile is not None and effective_config is None:
            if _looks_like_config_path(profile):
                raise typer.BadParameter(
                    f"{profile!r} looks like a config file path, not a preset profile id "
                    f"(e.g. good_value_osx). Use: sevn onboard --config {profile}"
                )
            try:
                load_profile_fragment(profile)
            except (FileNotFoundError, ValueError, OSError) as exc:
                raise _profile_bad_parameter(profile, exc) from exc
            typer.echo(f"profile {profile!r}: schema validation ok (no files written)")
            ran_validate_only = True
        if effective_config is not None:
            if profile is not None:
                try:
                    load_profile_fragment(profile)
                except (FileNotFoundError, ValueError, OSError) as exc:
                    raise _profile_bad_parameter(profile, exc) from exc
            raw = _read_config_file(effective_config)
            _run_fast_onboard_and_report(
                config_doc=raw,
                profile_id=profile,
                bot_name=bot_name,
                prompt_for_bot_name=not no_prompt_bot_name,
                install_daemon=install_daemon,
                start_services=not no_start_services,
            )
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
        if not (web or cli_tui):
            if not interactive and not ran_validate_only:
                raise typer.BadParameter(
                    "non-interactive context: use `--web`, `--cli`, `--config`, or `--profile`.",
                )
            if not ran_validate_only:
                web = _has_graphical_browser()
                cli_tui = not web
        if web:
            _run_install_gate_tty()
            _run_web_wizard(
                host=host,
                port=port,
                open_browser=not no_open,
                install_daemon=install_daemon,
            )
            raise typer.Exit(0)
        if cli_tui:
            _run_install_gate_tty()
            from sevn.onboarding.tui import run_textual_onboarding

            os.environ["SEVN_ONBOARD_INSTALL_DAEMON"] = "1" if install_daemon else "0"
            os.environ.setdefault("SEVN_ONBOARD_REUSE", "0")
            rc = run_textual_onboarding()
            raise typer.Exit(rc)
        if ran_validate_only:
            raise typer.Exit(0)
        raise typer.BadParameter(
            "non-interactive context: use `--web`, `--cli`, `--config`, or `--profile`.",
        )


def _run_fast_onboard_and_report(**kwargs: Any) -> None:
    """Run ``run_fast_onboard`` with ``kwargs``, map errors, and print the summary.

    Args:
        kwargs (Any): Keyword arguments forwarded verbatim to ``run_fast_onboard``.

    Raises:
        typer.Exit: Always — ``0`` on success, ``2``/``4`` on mapped failures.

    Examples:
        >>> _run_fast_onboard_and_report(config_doc={}, profile_id=None)  # doctest: +SKIP
    """
    try:
        result = asyncio.run(run_fast_onboard(**kwargs))
    except FastOnboardValidationError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(2) from exc
    except FastOnboardPreconditionError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(4) from exc
    except FastOnboardError as exc:
        typer.secho(str(exc), err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:
        raise typer.BadParameter(f"invalid config: {exc}") from exc
    typer.echo(f"promoted config to {result.sevn_json_path}")
    for path in result.seeded_paths:
        typer.echo(f"seeded: {path}")
    if result.daemon_install_line:
        typer.echo(result.daemon_install_line)
    if result.pdf_native_install_line:
        typer.echo(result.pdf_native_install_line)
    if result.services_restart is not None:
        msg = result.services_restart.get("message")
        if isinstance(msg, str) and msg.strip():
            typer.echo(msg)
    raise typer.Exit(0)


def _run_onboard_fast(
    *,
    fast_file: Path | None,
    install_daemon: bool,
    start_services: bool,
) -> None:
    """Recreate a bot from a ``sevn export-secrets`` bundle (``onboard fast``).

    Args:
        fast_file (Path | None): Path to the exported ``.env`` bundle.
        install_daemon (bool): Forwarded to ``run_fast_onboard``.
        start_services (bool): Forwarded to ``run_fast_onboard``.

    Raises:
        typer.Exit: On success or mapped failure (via ``_run_fast_onboard_and_report``).
        typer.BadParameter: When ``fast_file`` is missing.

    Examples:
        >>> _run_onboard_fast(fast_file=None, install_daemon=False, start_services=False)  # doctest: +SKIP
    """
    if fast_file is None:
        raise typer.BadParameter("usage: sevn onboard fast <export.env>")
    path = fast_file.expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.secho(f"cannot read export file {path}: {exc}", err=True)
        raise typer.Exit(4) from exc
    try:
        bundle = parse_export_text(text)
    except ExportBundleError as exc:
        typer.secho(exc.message, err=True)
        raise typer.Exit(exc.exit_code) from exc
    _run_fast_onboard_and_report(
        config_doc=bundle.config_doc,
        profile_id=None,
        bot_name=bundle.bot_name,
        prompt_for_bot_name=False,
        install_daemon=install_daemon,
        start_services=start_services,
        seed_secrets=bundle_seed_secrets(bundle),
    )


def _run_install_gate_tty() -> None:
    """Prompt for reuse / wipe when an existing install is detected on a TTY.
    Examples:
        >>> _run_install_gate_tty() is None  # doctest: +SKIP
        True
    """
    state = install_gate_state()
    resolution = prompt_install_gate_tty(state)
    if resolution is not None:
        apply_install_resolution(resolution)
        if resolution.reuse:
            prompt_keystore_passphrase_tty(sevn_json=bound_sevn_json_path())


def _run_web_wizard(
    *,
    host: str,
    port: int,
    open_browser: bool,
    install_daemon: bool = True,
) -> None:
    """Start the loopback FastAPI wizard and (optionally) open the browser.
    Args:
        host (str): Bind host.
        port (int): Bind port.
        open_browser (bool): When True, schedule ``webbrowser.open`` once uvicorn
            has bound the listening socket.
        install_daemon (bool, optional): Export ``SEVN_ONBOARD_INSTALL_DAEMON`` for
            post-save install. Defaults to True.
    Examples:
        >>> import sys, types
        >>> from unittest.mock import patch
        >>> fake_uvicorn = types.SimpleNamespace(run=lambda *_a, **_kw: None)
        >>> with patch.dict(sys.modules, {"uvicorn": fake_uvicorn}), patch.object(
        ...     typer, "echo"
        ... ), patch.object(typer, "secho"):
        ...     _run_web_wizard(
        ...         host="127.0.0.1", port=18847, open_browser=False, install_daemon=True
        ...     )
    """
    import os as _os

    _os.environ["SEVN_ONBOARD_INSTALL_DAEMON"] = "1" if install_daemon else "0"
    _os.environ.setdefault("SEVN_ONBOARD_REUSE", "0")
    token = _os.environ.get("SEVN_ONBOARD_TOKEN", "").strip() or secrets.token_urlsafe(24)
    wapp = create_onboarding_app(token, onboard_port=port)
    url = f"http://{host}:{port}/?onboard_token={token}"
    from sevn.ui.terminal_theme import brand_header

    typer.echo(brand_header(f"Open: {url}"))
    typer.secho("Serving until Ctrl+C (uvicorn).", err=True)
    try:
        import uvicorn
    except ImportError as exc:
        typer.secho(
            "uvicorn is required for `sevn onboard --web` (install the `sevn` package extras).",
            err=True,
        )
        raise typer.Exit(4) from exc
    if open_browser:

        def _open_when_ready() -> None:
            import socket
            import time as _time

            deadline = _time.monotonic() + 5.0
            while _time.monotonic() < deadline:
                try:
                    with socket.create_connection((host, port), timeout=0.2):
                        break
                except OSError:
                    _time.sleep(0.1)
            try:
                opened = webbrowser.open(url, new=2)
            except webbrowser.Error:
                opened = False
            if not opened:
                typer.secho(
                    "(could not open browser automatically — copy the URL above)",
                    err=True,
                )

        threading.Thread(target=_open_when_ready, daemon=True).start()

    from sevn.logging.bridge import configure_intercept_logging

    configure_intercept_logging()
    uvicorn.run(wapp, host=host, port=port, log_level="info")


def _read_config_file(path: Path) -> dict[str, Any]:
    """Load a JSON or YAML object from ``path``.
    Args:
        path (Path): Config file path.
    Returns:
        dict[str, Any]: Parsed root object.
    Raises:
        typer.BadParameter: When the document is not a JSON object.
    Examples:
        >>> import json, tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp()) / "cfg.json"
        >>> _ = p.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        >>> _read_config_file(p)["schema_version"]
        1
    """
    text = path.expanduser().resolve().read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    doc = yaml.safe_load(text) if suffix in (".yaml", ".yml") else json.loads(text)
    if not isinstance(doc, dict):
        raise typer.BadParameter("config file must contain a JSON/YAML object at root")
    return doc
