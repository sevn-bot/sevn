"""``sevn tunnel`` — set up and control the public tunnel (cloudflare/ngrok/tailscale).

Module: sevn.cli.commands.tunnel_cmd
Depends: shutil, sys, typer, sevn.cli.*, sevn.infrastructure.*

Exports:
    register — attach the ``tunnel`` Typer group to the root app.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from typing import Any

import typer

from sevn.cli.errors import CliPreconditionError
from sevn.cli.json_util import emit_json_failure, emit_json_success
from sevn.cli.prompt_util import prompt_with_field_help
from sevn.infrastructure.tunnel_config import (
    TUNNEL_MODE_BY_CANONICAL,
    install_hint_for_binary,
    normalize_tunnel_mode,
    secret_binding,
    stale_setup_fields,
    tunnel_binary,
    tunnel_cfg_from_raw,
    tunnel_mode_spec,
)

_SETUP_HELP: str = (
    "Configure a public tunnel to the gateway. Stores provider secrets in the "
    "workspace secrets chain (never in sevn.json) and stamps ${SECRET:...} references.\n\n"
    "Modes: cloudflare, cloudflare-quick, ngrok, tailscale-serve, tailscale-funnel.\n\n"
    "Cloudflare (recommended): pass --account-id, --api-token-stdin, and --hostname. "
    "sevn creates the tunnel, publishes DNS, installs cloudflared, and starts it.\n\n"
    "Cloudflare quick (no domain): --mode cloudflare-quick or --mode cloudflare --quick. "
    "Runs `cloudflared tunnel --url` and prints a random https://*.trycloudflare.com URL.\n\n"
    "Legacy cloudflare: pass --token-stdin with a dashboard Install-as-service command."
)

_SECRET_FIELD_BY_MODE: dict[str, str] = {
    "cloudflare": "infrastructure.tunnel.cloudflare.token",
    "ngrok": "infrastructure.tunnel.ngrok.authtoken",
}

_CF_API_TOKEN_FIELD = "infrastructure.tunnel.cloudflare.api_token"  # nosec B105 — secrets chain field id


def register(app: typer.Typer) -> None:
    """Attach ``sevn tunnel`` (setup/status/start/stop) to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    tn = typer.Typer(help="Set up and control the public tunnel to the gateway.")
    app.add_typer(tn, name="tunnel")

    _register_setup(tn)
    _register_lifecycle(tn)


def _register_setup(tn: typer.Typer) -> None:
    """Attach the ``setup`` subcommand to the tunnel group.

    Args:
        tn (typer.Typer): The ``sevn tunnel`` sub-app.

    Examples:
        >>> _register_setup(typer.Typer()) is None
        True
    """

    @tn.command("setup", help=_SETUP_HELP)
    def setup_cmd(
        mode: str = typer.Option(
            ...,
            "--mode",
            help="cloudflare | cloudflare-quick | ngrok | tailscale-serve | tailscale-funnel",
        ),
        quick: bool = typer.Option(
            False,
            "--quick",
            help="Use Cloudflare quick tunnel (trycloudflare.com) when --mode cloudflare.",
        ),
        hostname: str | None = typer.Option(
            None, "--hostname", help="Public hostname to display / reserved domain."
        ),
        local_port: int | None = typer.Option(
            None, "--local-port", help="Local gateway port to forward (ngrok/tailscale)."
        ),
        metrics_addr: str | None = typer.Option(
            None, "--metrics-addr", help="cloudflared metrics address (cloudflare)."
        ),
        config_path: str | None = typer.Option(
            None,
            "--config-path",
            help="cloudflared config YAML path (cloudflare, alternative to token).",
        ),
        tunnel_id: str | None = typer.Option(
            None, "--tunnel-id", help="Cloudflare tunnel UUID (cloudflare, optional)."
        ),
        account_id: str | None = typer.Option(
            None, "--account-id", help="Cloudflare account id (cloudflare API setup)."
        ),
        api_token: str | None = typer.Option(
            None,
            "--api-token",
            help="Cloudflare API token (cloudflare API setup; prefer --api-token-stdin).",
        ),
        api_token_stdin: bool = typer.Option(
            False,
            "--api-token-stdin",
            help="Read the Cloudflare API token from stdin (cloudflare API setup).",
        ),
        token: str | None = typer.Option(
            None, "--token", help="Provider secret (visible in argv/ps — prefer --token-stdin)."
        ),
        token_stdin: bool = typer.Option(
            False, "--token-stdin", help="Read the provider secret as one line from standard input."
        ),
        confirm_fingerprint: str | None = typer.Option(
            None,
            "--confirm-fingerprint",
            help="Required when overwriting a differing stored secret: its SHA-256 hex.",
        ),
        json_out: bool = typer.Option(
            False, "--json", help="JSON envelope (never prints the secret)."
        ),
    ) -> None:
        """Store the tunnel provider secret and stamp infrastructure.tunnel config."""
        _run_setup(
            mode=mode,
            quick=quick,
            hostname=hostname,
            local_port=local_port,
            metrics_addr=metrics_addr,
            config_path=config_path,
            tunnel_id=tunnel_id,
            account_id=account_id,
            api_token=api_token,
            api_token_stdin=api_token_stdin,
            token=token,
            token_stdin=token_stdin,
            confirm_fingerprint=confirm_fingerprint,
            json_out=json_out,
        )


def _register_lifecycle(tn: typer.Typer) -> None:
    """Attach ``status`` / ``start`` / ``stop`` subcommands to the tunnel group.

    Args:
        tn (typer.Typer): The ``sevn tunnel`` sub-app.

    Examples:
        >>> _register_lifecycle(typer.Typer()) is None
        True
    """

    @tn.command("status")
    def status_cmd(
        json_out: bool = typer.Option(
            False, "--json", help="JSON envelope with the tunnel status."
        ),
    ) -> None:
        """Show the current tunnel mode and process health."""
        _run_lifecycle("status", json_out=json_out)

    @tn.command("start")
    def start_cmd(
        json_out: bool = typer.Option(
            False, "--json", help="JSON envelope with the tunnel status."
        ),
    ) -> None:
        """Start the configured tunnel (resolves the secret, then spawns the provider)."""
        _run_lifecycle("start", json_out=json_out)

    @tn.command("stop")
    def stop_cmd(
        json_out: bool = typer.Option(
            False, "--json", help="JSON envelope with the tunnel status."
        ),
    ) -> None:
        """Stop the running tunnel."""
        _run_lifecycle("stop", json_out=json_out)


def _interactive_setup_enabled(*, json_out: bool) -> bool:
    """Return whether ``setup`` may prompt for missing values.

    Args:
        json_out (bool): Whether ``--json`` is active.

    Returns:
        bool: True when stdin is a TTY and JSON mode is off.

    Examples:
        >>> _interactive_setup_enabled(json_out=True)
        False
    """
    return not json_out and sys.stdin.isatty()


def _resolve_cloudflare_api_setup(
    *,
    account_id: str | None,
    api_token: str | None,
    api_token_stdin: bool,
    hostname: str | None,
    gateway_port: int | None,
    json_out: bool,
) -> tuple[Any, dict[str, Any], str]:
    """Provision a Cloudflare tunnel via API when account credentials are available.

    Args:
        account_id (str | None): ``--account-id`` value.
        api_token (str | None): ``--api-token`` value.
        api_token_stdin (bool): Whether to read the API token from stdin.
        hostname (str | None): Public hostname / ``--hostname`` value.
        gateway_port (int | None): Local gateway port for ingress routing.
        json_out (bool): Whether JSON mode is active.

    Returns:
        tuple[Any, dict[str, Any], str]: Provision result, extra config fields, API token
            plaintext.

    Raises:
        ValueError: When required API fields are missing or invalid.

    Examples:
        >>> _resolve_cloudflare_api_setup(  # doctest: +SKIP
        ...     account_id="acct",
        ...     api_token="tok",
        ...     api_token_stdin=False,
        ...     hostname="sevn.example.com",
        ...     gateway_port=3001,
        ...     json_out=True,
        ... )
    """
    from sevn.infrastructure.cloudflare_tunnel_api import (
        normalize_public_hostname,
        provision_cloudflare_tunnel,
    )

    acct = (account_id or "").strip()
    api = (api_token or "").strip()
    if api_token_stdin:
        api = sys.stdin.readline().strip()
    host = (hostname or "").strip()

    if _interactive_setup_enabled(json_out=json_out):
        if not acct:
            acct = str(typer.prompt("Cloudflare account id")).strip()
        if not api:
            api = prompt_with_field_help(
                _CF_API_TOKEN_FIELD,
                "Paste the Cloudflare API token:",
                hide_input=True,
                collect_only=True,
            )
        if not host:
            host = normalize_public_hostname(
                str(
                    typer.prompt(
                        "Public hostname for Mission Control (e.g. sevn.example.com):",
                    )
                )
            )
    elif host:
        host = normalize_public_hostname(host)

    if not acct or not api or not host:
        msg = (
            "Cloudflare API setup requires account id, API token, and hostname "
            "(--account-id, --api-token-stdin, --hostname)"
        )
        raise ValueError(msg)

    result = provision_cloudflare_tunnel(
        account_id=acct,
        api_token=api,
        hostname=host,
        gateway_port=gateway_port,
    )
    extra_fields = {
        "infrastructure.tunnel.cloudflare.account_id": acct,
        "infrastructure.tunnel.hostname": result.hostname,
        "infrastructure.tunnel.tunnel_id": result.tunnel_id,
    }
    return result, extra_fields, api


def _store_extra_secret(bootstrap: Any, *, logical_key: str, plaintext: str) -> None:
    """Store an additional secrets-chain value after tunnel setup.

    Args:
        bootstrap (GatewayTokenBootstrap): Bound workspace bootstrap view.
        logical_key (str): Secrets-chain logical id.
        plaintext (str): Secret plaintext.

    Examples:
        >>> _store_extra_secret(None, logical_key="k", plaintext="v")  # doctest: +SKIP
    """
    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.cli.tunnel_setup_store import _write_secret_key
    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain

    key_source = effective_encrypted_file_key_source(bootstrap.secrets_backend)
    run_sync_coro(reconcile_unlock_env_with_keychain(key_source=key_source))
    run_sync_coro(
        _write_secret_key(
            bootstrap.chain(),
            logical_key=logical_key,
            plaintext=plaintext,
            confirm_fingerprint=None,
        )
    )


def _acquire_secret(
    *,
    mode: str,
    token: str | None,
    token_stdin: bool,
    json_out: bool,
) -> str | None:
    """Resolve the provider secret plaintext for ``setup`` (None when not needed).

    Args:
        mode (str): Canonical tunnel mode.
        token (str | None): ``--token`` value, if given.
        token_stdin (bool): Whether to read the secret from standard input.
        json_out (bool): Whether JSON mode is active (disables the interactive prompt).

    Returns:
        str | None: Secret plaintext, or None for tailscale modes.

    Raises:
        ValueError: When a required secret is empty or cannot be collected.

    Examples:
        >>> _acquire_secret(mode="tailscale_serve", token=None, token_stdin=False, json_out=True)
    """
    spec = TUNNEL_MODE_BY_CANONICAL.get(mode)
    if spec is None or not spec.has_setup_secret:
        return None

    supplied: str | None = token
    if token_stdin:
        supplied = sys.stdin.readline().strip()
    if supplied is None and _interactive_setup_enabled(json_out=json_out):
        field_path = _SECRET_FIELD_BY_MODE.get(mode)
        if field_path is None:
            msg = f"mode {mode!r} does not accept a provider secret"
            raise ValueError(msg)
        label = "ngrok authtoken" if mode == "ngrok" else "Cloudflare Install as service command"
        supplied = prompt_with_field_help(
            field_path,
            f"Paste the {label}:",
            hide_input=True,
            collect_only=True,
        )
    if not supplied:
        if _interactive_setup_enabled(json_out=json_out):
            msg = (
                "a provider secret is required: pass --token, --token-stdin, or paste at the prompt"
            )
        else:
            msg = "a provider secret is required: pass --token or --token-stdin"
        raise ValueError(msg)
    normalized = supplied.strip()
    if mode == "cloudflare":
        from sevn.infrastructure.cloudflared_provision import parse_cloudflared_tunnel_input

        normalized = parse_cloudflared_tunnel_input(normalized)
    return normalized


def _auto_provision_and_start_cloudflare() -> dict[str, Any]:
    """Install cloudflared when missing and start the configured Cloudflare tunnel.

    Returns:
        dict[str, Any]: Install/start metadata for CLI success envelopes.

    Raises:
        RuntimeError: When cloudflared cannot be installed or the tunnel fails to start.

    Examples:
        >>> _auto_provision_and_start_cloudflare()  # doctest: +SKIP
    """
    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.cli.workspace import load_bound_workspace
    from sevn.infrastructure.cloudflared_provision import ensure_cloudflared_binary
    from sevn.infrastructure.tunnel_config import prepare_tunnel_runtime_cfg, tunnel_cfg_from_raw
    from sevn.infrastructure.tunnel_manager import TunnelManager, tunnel_pid_file

    path, detail = ensure_cloudflared_binary()
    if path is None:
        raise RuntimeError(detail)

    bw = load_bound_workspace()
    tunnel_cfg = tunnel_cfg_from_raw(bw.raw)
    gateway_port = bw.config.gateway.port if bw.config.gateway else None
    runtime_cfg = run_sync_coro(
        prepare_tunnel_runtime_cfg(
            tunnel_cfg,
            gateway_port=gateway_port,
            content_root=bw.layout.content_root,
            secrets_backend=bw.config.secrets_backend,
        ),
    )
    manager = TunnelManager(pid_file=tunnel_pid_file(bw.layout.content_root))
    status = manager.start(runtime_cfg, confirm=True)
    if not status.healthy:
        raise RuntimeError(status.error or "cloudflared failed to start")
    return {
        "cloudflared_path": path,
        "cloudflared_detail": detail,
        "started": True,
        "pid": status.pid,
        "public_url": status.public_url,
        "mission_control_url": status.mission_control_url,
    }


def _cloudflare_already_configured(bootstrap: Any, current_tunnel: dict[str, Any]) -> bool:
    """Return whether Cloudflare tunnel credentials are already stored.

    Args:
        bootstrap (GatewayTokenBootstrap): Bound workspace bootstrap view.
        current_tunnel (dict[str, Any]): Existing ``infrastructure.tunnel`` sub-dict.

    Returns:
        bool: ``True`` when setup can update fields without re-provisioning via API.

    Examples:
        >>> _cloudflare_already_configured(None, {"mode": "cloudflare"})  # doctest: +SKIP
        False
    """
    if _setup_secret_already_stored(bootstrap, "cloudflare"):
        return True
    cf = current_tunnel.get("cloudflare")
    return isinstance(cf, dict) and bool(str(cf.get("account_id") or "").strip())


def _should_use_cloudflare_api(
    *,
    canonical: str,
    config_path: str | None,
    token: str | None,
    token_stdin: bool,
    account_id: str | None,
    api_token: str | None,
    api_token_stdin: bool,
    bootstrap: Any,
    current_tunnel: dict[str, Any],
) -> bool:
    """Decide whether setup should provision Cloudflare via the API.

    Args:
        canonical (str): Normalized tunnel mode.
        config_path (str | None): ``--config-path`` value.
        token (str | None): Legacy ``--token`` value.
        token_stdin (bool): Whether ``--token-stdin`` was passed.
        account_id (str | None): ``--account-id`` value.
        api_token (str | None): ``--api-token`` value.
        api_token_stdin (bool): Whether ``--api-token-stdin`` was passed.
        bootstrap (GatewayTokenBootstrap): Bound workspace bootstrap view.
        current_tunnel (dict[str, Any]): Existing ``infrastructure.tunnel`` sub-dict.

    Returns:
        bool: ``True`` when API provisioning should run.

    Examples:
        >>> _should_use_cloudflare_api(  # doctest: +SKIP
        ...     canonical="cloudflare", config_path=None, token=None, token_stdin=False,
        ...     account_id=None, api_token=None, api_token_stdin=False,
        ...     bootstrap=None, current_tunnel={},
        ... )
        True
    """
    if canonical != "cloudflare" or config_path or token or token_stdin:
        return False
    if account_id or api_token or api_token_stdin:
        return True
    return not _cloudflare_already_configured(bootstrap, current_tunnel)


def _setup_secret_already_stored(bootstrap: Any, mode: str) -> bool:
    """Return whether setup can skip secret collection for ``mode``.

    Args:
        bootstrap (GatewayTokenBootstrap): Bound workspace bootstrap view.
        mode (str): Canonical tunnel mode.

    Returns:
        bool: ``True`` when ``sevn.json`` already references a stored chain secret.

    Examples:
        >>> _setup_secret_already_stored(None, "cloudflare")  # doctest: +SKIP
        False
    """
    spec = tunnel_mode_spec(mode)
    if (
        not spec.has_setup_secret
        or spec.runtime_secret_field is None
        or spec.secret_logical_key is None
    ):
        return False
    raw = json.loads(bootstrap.sevn_json_path.read_text(encoding="utf-8"))
    tunnel = tunnel_cfg_from_raw(raw)
    ref = tunnel.get(spec.runtime_secret_field)
    if not isinstance(ref, str) or not ref.strip().startswith("${SECRET:"):
        return False

    async def _has_secret() -> bool:
        return await bootstrap.chain().get_resilient(spec.secret_logical_key) is not None

    return asyncio.run(_has_secret())


def _build_config_fields(
    *,
    mode: str,
    hostname: str | None,
    local_port: int | None,
    metrics_addr: str | None,
    config_path: str | None,
    tunnel_id: str | None,
) -> dict[str, Any]:
    """Assemble the dotted-path config edits for ``sevn tunnel setup``.

    Args:
        mode (str): Canonical tunnel mode.
        hostname (str | None): Public hostname / reserved domain.
        local_port (int | None): Local gateway port to forward.
        metrics_addr (str | None): cloudflared metrics address.
        config_path (str | None): cloudflared config YAML path.
        tunnel_id (str | None): Cloudflare tunnel UUID.

    Returns:
        dict[str, Any]: Dotted-path → value edits under ``infrastructure.tunnel``.

    Examples:
        >>> _build_config_fields(
        ...     mode="ngrok", hostname=None, local_port=3001,
        ...     metrics_addr=None, config_path=None, tunnel_id=None,
        ... )
        {'infrastructure.tunnel.mode': 'ngrok', 'infrastructure.tunnel.local_port': 3001}
    """
    fields: dict[str, Any] = {"infrastructure.tunnel.mode": mode}
    if hostname:
        fields["infrastructure.tunnel.hostname"] = hostname
    if local_port:
        fields["infrastructure.tunnel.local_port"] = local_port
    if metrics_addr:
        fields["infrastructure.tunnel.metrics_addr"] = metrics_addr
    if config_path:
        fields["infrastructure.tunnel.config_path"] = config_path
    if tunnel_id:
        fields["infrastructure.tunnel.tunnel_id"] = tunnel_id
    return fields


def _fail(command: str, code: str, message: str, *, json_out: bool, exit_code: int) -> None:
    """Emit a CLI failure (JSON or stderr) and raise ``typer.Exit``.

    Args:
        command (str): Command label for parsers.
        code (str): Stable machine-readable error code.
        message (str): Human-readable summary.
        json_out (bool): Whether to emit a JSON envelope.
        exit_code (int): Process exit code.

    Examples:
        >>> import typer
        >>> try:
        ...     _fail("sevn tunnel", "E", "boom", json_out=False, exit_code=4)
        ... except typer.Exit as exc:
        ...     exc.exit_code
        4
    """
    if json_out:
        emit_json_failure(command=command, error_code=code, message=message, exit_code=exit_code)
    else:
        typer.secho(message, err=True)
    raise typer.Exit(exit_code)


def _run_setup(
    *,
    mode: str,
    quick: bool,
    hostname: str | None,
    local_port: int | None,
    metrics_addr: str | None,
    config_path: str | None,
    tunnel_id: str | None,
    account_id: str | None,
    api_token: str | None,
    api_token_stdin: bool,
    token: str | None,
    token_stdin: bool,
    confirm_fingerprint: str | None,
    json_out: bool,
) -> None:
    """Implement ``sevn tunnel setup``.

    Args:
        mode (str): Raw ``--mode`` value.
        quick (bool): Whether ``--quick`` was passed for Cloudflare quick tunnel setup.
        hostname (str | None): Public hostname / reserved domain.
        local_port (int | None): Local gateway port to forward.
        metrics_addr (str | None): cloudflared metrics address.
        config_path (str | None): cloudflared config YAML path.
        tunnel_id (str | None): Cloudflare tunnel UUID.
        account_id (str | None): Cloudflare account id for API provisioning.
        api_token (str | None): Cloudflare API token for API provisioning.
        api_token_stdin (bool): Read the Cloudflare API token from stdin.
        token (str | None): Provider secret value.
        token_stdin (bool): Read the secret from standard input.
        confirm_fingerprint (str | None): Fingerprint for secret overwrite.
        json_out (bool): Emit a JSON envelope.

    Examples:
        >>> _run_setup(  # doctest: +SKIP
        ...     mode="cloudflare", hostname=None, local_port=None, metrics_addr=None,
        ...     config_path=None, tunnel_id=None, token=None, token_stdin=False,
        ...     confirm_fingerprint=None, json_out=True,
        ... )
    """
    from sevn.cli.gateway_token_store import load_bootstrap_workspace
    from sevn.cli.tunnel_setup_store import apply_tunnel_setup_local

    command = "sevn tunnel setup"
    if quick and mode.strip().lower() not in {"cloudflare", "cloudflare-quick", "cloudflare_quick"}:
        _fail(
            command,
            "INVALID_USAGE",
            "--quick is only valid with --mode cloudflare or cloudflare-quick",
            json_out=json_out,
            exit_code=4,
        )
    if quick:
        mode = "cloudflare-quick"

    if token is not None and token_stdin:
        _fail(
            command,
            "INVALID_USAGE",
            "pass at most one of --token or --token-stdin",
            json_out=json_out,
            exit_code=4,
        )
    if api_token is not None and api_token_stdin:
        _fail(
            command,
            "INVALID_USAGE",
            "pass at most one of --api-token or --api-token-stdin",
            json_out=json_out,
            exit_code=4,
        )

    try:
        canonical = normalize_tunnel_mode(mode)
    except ValueError as exc:
        _fail(command, "INVALID_MODE", str(exc), json_out=json_out, exit_code=4)
        return

    spec = tunnel_mode_spec(canonical)
    bootstrap = load_bootstrap_workspace()
    raw = json.loads(bootstrap.sevn_json_path.read_text(encoding="utf-8"))
    current_tunnel = tunnel_cfg_from_raw(raw)
    try:
        previous_mode = normalize_tunnel_mode(str(current_tunnel.get("mode") or "none"))
    except ValueError:
        previous_mode = "none"
    mode_switch = previous_mode != canonical
    gateway_port = None
    gw = raw.get("gateway") if isinstance(raw.get("gateway"), dict) else None
    if isinstance(gw, dict) and gw.get("port") is not None:
        gateway_port = int(gw["port"])

    provision_result: Any | None = None
    api_config_fields: dict[str, Any] = {}
    api_token_plaintext: str | None = None
    secret_plaintext: str | None = None
    use_cloudflare_api = _should_use_cloudflare_api(
        canonical=canonical,
        config_path=config_path,
        token=token,
        token_stdin=token_stdin,
        account_id=account_id,
        api_token=api_token,
        api_token_stdin=api_token_stdin,
        bootstrap=bootstrap,
        current_tunnel=current_tunnel,
    )

    if use_cloudflare_api:
        try:
            cf_provision, api_config_fields, api_token_plaintext = _resolve_cloudflare_api_setup(
                account_id=account_id,
                api_token=api_token,
                api_token_stdin=api_token_stdin,
                hostname=hostname,
                gateway_port=gateway_port,
                json_out=json_out,
            )
        except ValueError as exc:
            _fail(command, "SETUP_FAILED", str(exc), json_out=json_out, exit_code=4)
            return
        provision_result = cf_provision
        secret_plaintext = cf_provision.tunnel_token
        hostname = cf_provision.hostname
        tunnel_id = cf_provision.tunnel_id
        token_needed = True
    else:
        token_needed = spec.setup_needs_secret(has_config_path=bool(config_path))
        if (
            token_needed
            and token is None
            and not token_stdin
            and _setup_secret_already_stored(bootstrap, canonical)
        ):
            token_needed = False
        try:
            secret_plaintext = (
                _acquire_secret(
                    mode=canonical,
                    token=token,
                    token_stdin=token_stdin,
                    json_out=json_out,
                )
                if token_needed
                else None
            )
        except ValueError as exc:
            _fail(command, "SECRET_REQUIRED", str(exc), json_out=json_out, exit_code=4)
            return

    config_fields = _build_config_fields(
        mode=canonical,
        hostname=hostname,
        local_port=local_port,
        metrics_addr=metrics_addr,
        config_path=config_path,
        tunnel_id=tunnel_id,
    )
    if provision_result is not None:
        config_fields.update(api_config_fields)
    logical_key, ref_path, ref_value = secret_binding(canonical)
    store_secret = secret_plaintext is not None

    try:
        result = apply_tunnel_setup_local(
            bootstrap,
            config_fields=config_fields,
            clear_fields=stale_setup_fields(
                canonical,
                store_secret=store_secret,
                clear_stale_hostname=mode_switch,
            ),
            secret_logical_key=logical_key if store_secret else None,
            secret_config_ref_path=ref_path if store_secret else None,
            secret_config_ref_value=ref_value if store_secret else None,
            secret_plaintext=secret_plaintext,
            confirm_fingerprint=confirm_fingerprint,
        )
    except CliPreconditionError as exc:
        _fail(
            command, "WORKSPACE_PRECONDITION", str(exc), json_out=json_out, exit_code=exc.exit_code
        )
        return
    except ValueError as exc:
        _fail(command, "SETUP_FAILED", str(exc), json_out=json_out, exit_code=4)
        return

    if api_token_plaintext:
        try:
            _store_extra_secret(
                bootstrap,
                logical_key="infrastructure.tunnel.cloudflare.api_token",
                plaintext=api_token_plaintext,
            )
        except ValueError as exc:
            _fail(command, "SETUP_FAILED", str(exc), json_out=json_out, exit_code=4)
            return

    binary = tunnel_binary(canonical)
    binary_present = shutil.which(binary) is not None
    auto_start_data: dict[str, Any] | None = None
    auto_start_error: str | None = None
    cloudflared_runnable = canonical in {"cloudflare", "cloudflare_quick"} and (
        canonical == "cloudflare_quick" or store_secret or bool(config_path)
    )
    if cloudflared_runnable:
        try:
            auto_start_data = _auto_provision_and_start_cloudflare()
            binary_present = True
        except (RuntimeError, CliPreconditionError, ValueError) as exc:
            auto_start_error = str(exc)
            binary_present = shutil.which(binary) is not None

    data = {
        "mode": canonical,
        "secret_stored": store_secret,
        "secret_ref": result.secret_ref,
        "fingerprint_sha256_hex": result.fingerprint_sha256_hex,
        "overwritten": result.overwritten,
        "binary": binary,
        "binary_present": binary_present,
    }
    if auto_start_data is not None:
        data.update(auto_start_data)
    if provision_result is not None:
        data["public_url"] = provision_result.public_url
        data["mission_control_url"] = provision_result.public_url
    if auto_start_error is not None:
        data["auto_start_attempted"] = True
        data["auto_start_error"] = auto_start_error
    if json_out:
        emit_json_success(command=command, data=data)
    else:
        typer.echo(f"tunnel configured: mode={canonical}")
        if store_secret:
            typer.echo(f"secret stored ({logical_key})")
        if auto_start_data is not None:
            if auto_start_data.get("cloudflared_detail") != "cloudflared already on PATH":
                typer.echo(auto_start_data["cloudflared_detail"])
            line = "tunnel started"
            if auto_start_data.get("pid"):
                line += f" pid={auto_start_data['pid']}"
            mc_url = (
                provision_result.public_url
                if provision_result is not None
                else auto_start_data.get("public_url")
            )
            if mc_url:
                line += f" mission_control_url={mc_url}"
            typer.echo(line)
        elif auto_start_error is not None:
            typer.echo(f"note: tunnel not started — {auto_start_error}")
            if not binary_present:
                typer.echo(f"note: {binary} not found on PATH — {install_hint_for_binary(binary)}")
            typer.echo("Hint: sevn tunnel start")
        elif not binary_present:
            typer.echo(f"note: {binary} not found on PATH — {install_hint_for_binary(binary)}")
            typer.echo("Hint: sevn tunnel start")
    raise typer.Exit(0)


def _run_lifecycle(action: str, *, json_out: bool) -> None:
    """Implement ``sevn tunnel status|start|stop``.

    Args:
        action (str): One of ``status``, ``start``, ``stop``.
        json_out (bool): Emit a JSON envelope.

    Examples:
        >>> _run_lifecycle("status", json_out=True)  # doctest: +SKIP
    """
    from sevn.cli.asyncio_util import run_sync_coro
    from sevn.cli.workspace import load_bound_workspace
    from sevn.infrastructure.tunnel_config import prepare_tunnel_runtime_cfg

    command = f"sevn tunnel {action}"
    try:
        bw = load_bound_workspace()
    except CliPreconditionError as exc:
        _fail(
            command, "WORKSPACE_PRECONDITION", str(exc), json_out=json_out, exit_code=exc.exit_code
        )
        return

    from sevn.infrastructure.tunnel_manager import TunnelManager, tunnel_pid_file

    tunnel_cfg = tunnel_cfg_from_raw(bw.raw)
    manager = TunnelManager(pid_file=tunnel_pid_file(bw.layout.content_root))

    try:
        if action == "status":
            status = manager.status(tunnel_cfg)
        elif action == "stop":
            status = manager.stop(tunnel_cfg, confirm=True)
        else:
            gateway_port = bw.config.gateway.port if bw.config.gateway else None
            runtime_cfg = run_sync_coro(
                prepare_tunnel_runtime_cfg(
                    tunnel_cfg,
                    gateway_port=gateway_port,
                    content_root=bw.layout.content_root,
                    secrets_backend=bw.config.secrets_backend,
                ),
            )
            status = manager.start(runtime_cfg, confirm=True)
    except (RuntimeError, ValueError) as exc:
        _fail(command, "TUNNEL_ERROR", str(exc), json_out=json_out, exit_code=4)
        return

    data = {
        "mode": status.mode,
        "healthy": status.healthy,
        "pid": status.pid,
        "public_url": status.public_url,
        "mission_control_url": status.mission_control_url,
        "error": status.error,
    }
    if json_out:
        emit_json_success(command=command, data=data)
    else:
        state = "running" if status.healthy else "stopped"
        line = f"tunnel {action}: mode={status.mode} {state}"
        if status.pid:
            line += f" pid={status.pid}"
        if status.mission_control_url:
            line += f" mission_control_url={status.mission_control_url}"
        elif status.public_url:
            line += f" url={status.public_url}"
        typer.echo(line)
        if status.error:
            typer.secho(status.error, err=True)
    exit_code = 4 if action == "start" and not status.healthy else 0
    raise typer.Exit(exit_code)


__all__ = ["register"]
