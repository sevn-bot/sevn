"""Tunnel mode registry, config extraction, and runtime preparation.

Module: sevn.infrastructure.tunnel_config
Depends: dataclasses, os, shutil, sevn.security.secrets.*

Constants:
    CF_TOKEN_LOGICAL_KEY — secrets-chain logical id for the cloudflared token.
    CF_TOKEN_CONFIG_REF — ``${SECRET:…}`` ref stamped at ``infrastructure.tunnel.token``.
    NGROK_AUTHTOKEN_LOGICAL_KEY — secrets-chain logical id for the ngrok authtoken.
    NGROK_AUTHTOKEN_CONFIG_REF — ref stamped at ``infrastructure.tunnel.ngrok_authtoken``.
    DEFAULT_TUNNEL_LOCAL_PORT — default local port when unset in tunnel config.
    DEFAULT_METRICS_ADDR — default cloudflared metrics listen address.
    RUNNABLE_MODES — tunnel modes :class:`~sevn.infrastructure.tunnel_manager.TunnelManager`
        can start/stop.

Exports:
    TunnelModeSpec — frozen metadata for one tunnel provider mode.
    normalize_tunnel_mode — map CLI aliases to canonical mode names.
    tunnel_mode_spec — look up mode metadata (raises on unknown mode).
    tunnel_binary — provider binary name for a mode.
    install_hint_for_binary — operator install hint for a provider binary.
    secret_binding — secrets-chain logical key + config ref for setup.
    stale_setup_fields — dotted paths to delete when switching modes at setup.
    runtime_secret_fields — tunnel sub-dict fields to expand for a mode at start.
    tunnel_cfg_from_raw — extract ``infrastructure.tunnel`` from a raw sevn.json doc.
    tunnel_cfg_from_workspace — extract ``infrastructure.tunnel`` from workspace config.
    tunnel_cfg_from_disk — read ``infrastructure.tunnel`` from on-disk sevn.json when available.
    coerce_tunnel_local_port — positive local port with default fallback.
    build_tunnel_launch — spawn argv/env for a runnable mode.
    build_tunnel_stop — argv to reset Tailscale serve/funnel exposure.
    is_tailscale_mode — whether a mode uses Tailscale serve/funnel.
    prepare_tunnel_runtime_cfg — expand secret refs and default the local port.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import SecretsBackendSectionConfig, WorkspaceConfig

CF_TOKEN_LOGICAL_KEY: str = "infrastructure.tunnel.cloudflare.token"
CF_TOKEN_CONFIG_REF: str = "${SECRET:keychain:infrastructure.tunnel.cloudflare.token}"
CF_API_TOKEN_LOGICAL_KEY: str = "infrastructure.tunnel.cloudflare.api_token"
CF_API_TOKEN_CONFIG_REF: str = "${SECRET:keychain:infrastructure.tunnel.cloudflare.api_token}"
NGROK_AUTHTOKEN_LOGICAL_KEY: str = "infrastructure.tunnel.ngrok.authtoken"
NGROK_AUTHTOKEN_CONFIG_REF: str = "${SECRET:keychain:infrastructure.tunnel.ngrok.authtoken}"

DEFAULT_TUNNEL_LOCAL_PORT: int = 3001
DEFAULT_METRICS_ADDR: str = "localhost:20241"

_INSTALL_HINT_BY_BINARY: dict[str, str] = {
    "cloudflared": (
        "install cloudflared: `brew install cloudflared` (macOS) or "
        "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    ),
    "ngrok": "install ngrok: `brew install ngrok` (macOS) or https://ngrok.com/download",
    "tailscale": "install tailscale: https://tailscale.com/download (then run `tailscale up`)",
}


@dataclass(frozen=True)
class TunnelModeSpec:
    """Metadata for one tunnel provider mode.

    Attributes:
        canonical (str): Canonical mode id stored in ``infrastructure.tunnel.mode``.
        binary (str): Provider executable name on ``PATH``.
        install_hint (str): Operator-facing install instructions.
        secret_logical_key (str | None): Secrets-chain id when this mode stores a secret.
        secret_config_path (str | None): Dotted sevn.json path for the ``${SECRET:…}`` ref.
        secret_config_ref (str | None): Ref value stamped at ``secret_config_path``.
        runtime_secret_field (str | None): Tunnel sub-dict field expanded at runtime start.
        runnable (bool): Whether :class:`~sevn.infrastructure.tunnel_manager.TunnelManager`
            can spawn this mode.
    """

    canonical: str
    binary: str
    install_hint: str
    secret_logical_key: str | None = None
    secret_config_path: str | None = None
    secret_config_ref: str | None = None
    runtime_secret_field: str | None = None
    runnable: bool = True

    @property
    def has_setup_secret(self) -> bool:
        """Whether setup may store a provider secret for this mode.

        Returns:
            bool: True when this mode uses a secrets-chain credential at setup.

        Examples:
            >>> TUNNEL_MODE_BY_CANONICAL["ngrok"].has_setup_secret
            True
            >>> TUNNEL_MODE_BY_CANONICAL["tailscale_serve"].has_setup_secret
            False
        """
        return self.secret_logical_key is not None

    def setup_needs_secret(self, *, has_config_path: bool) -> bool:
        """Return whether ``setup`` must collect a secret for this mode.

        Args:
            has_config_path (bool): Whether ``--config-path`` was passed (cloudflare).

        Returns:
            bool: True when a secret must be collected during setup.

        Examples:
            >>> spec = TUNNEL_MODE_BY_CANONICAL["cloudflare"]
            >>> spec.setup_needs_secret(has_config_path=True)
            False
        """
        if not self.has_setup_secret:
            return False
        return not (self.canonical == "cloudflare" and has_config_path)

    def stale_setup_field_paths(
        self,
        *,
        store_secret: bool,
        clear_stale_hostname: bool,
    ) -> tuple[str, ...]:
        """Dotted paths to delete when switching to this mode at setup.

        Args:
            store_secret (bool): Whether a provider secret is stored this run.
            clear_stale_hostname (bool): Whether a prior provider's hostname should
                be removed (mode switch without ``--hostname``).

        Returns:
            tuple[str, ...]: Paths under ``infrastructure.tunnel`` to delete.

        Examples:
            >>> TUNNEL_MODE_BY_CANONICAL["cloudflare"].stale_setup_field_paths(
            ...     store_secret=False,
            ...     clear_stale_hostname=True,
            ... )
            ('infrastructure.tunnel.ngrok_authtoken', 'infrastructure.tunnel.token', 'infrastructure.tunnel.hostname')
            >>> TUNNEL_MODE_BY_CANONICAL["cloudflare"].stale_setup_field_paths(
            ...     store_secret=False,
            ...     clear_stale_hostname=False,
            ... )
            ('infrastructure.tunnel.ngrok_authtoken', 'infrastructure.tunnel.token')
        """
        tok = "infrastructure.tunnel.token"
        cfg = "infrastructure.tunnel.config_path"
        ng = "infrastructure.tunnel.ngrok_authtoken"
        host = "infrastructure.tunnel.hostname"
        if self.canonical == "cloudflare":
            fields: list[str] = [ng, cfg if store_secret else tok]
        elif self.canonical == "cloudflare_quick":
            fields = [tok, cfg, ng]
        elif self.canonical == "ngrok":
            fields = [tok, cfg]
        else:
            fields = [tok, cfg, ng]
        if clear_stale_hostname:
            fields.append(host)
        return tuple(fields)


_TUNNEL_MODES: tuple[TunnelModeSpec, ...] = (
    TunnelModeSpec(
        canonical="cloudflare",
        binary="cloudflared",
        install_hint=_INSTALL_HINT_BY_BINARY["cloudflared"],
        secret_logical_key=CF_TOKEN_LOGICAL_KEY,
        secret_config_path="infrastructure.tunnel.token",  # nosec B106 — config path, not a secret
        secret_config_ref=CF_TOKEN_CONFIG_REF,
        runtime_secret_field="token",
    ),
    TunnelModeSpec(
        canonical="cloudflare_quick",
        binary="cloudflared",
        install_hint=_INSTALL_HINT_BY_BINARY["cloudflared"],
        runnable=True,
    ),
    TunnelModeSpec(
        canonical="ngrok",
        binary="ngrok",
        install_hint=_INSTALL_HINT_BY_BINARY["ngrok"],
        secret_logical_key=NGROK_AUTHTOKEN_LOGICAL_KEY,
        secret_config_path="infrastructure.tunnel.ngrok_authtoken",  # nosec B106 — config path, not a secret
        secret_config_ref=NGROK_AUTHTOKEN_CONFIG_REF,
        runtime_secret_field="ngrok_authtoken",
    ),
    TunnelModeSpec(
        canonical="tailscale_serve",
        binary="tailscale",
        install_hint=_INSTALL_HINT_BY_BINARY["tailscale"],
        runnable=True,
    ),
    TunnelModeSpec(
        canonical="tailscale_funnel",
        binary="tailscale",
        install_hint=_INSTALL_HINT_BY_BINARY["tailscale"],
        runnable=True,
    ),
)

TUNNEL_MODE_BY_CANONICAL: dict[str, TunnelModeSpec] = {m.canonical: m for m in _TUNNEL_MODES}

MODE_ALIASES: dict[str, str] = {
    "cloudflare": "cloudflare",
    "cloudflare-quick": "cloudflare_quick",
    "cloudflare_quick": "cloudflare_quick",
    "ngrok": "ngrok",
    "tailscale-serve": "tailscale_serve",
    "tailscale_serve": "tailscale_serve",
    "tailscale-funnel": "tailscale_funnel",
    "tailscale_funnel": "tailscale_funnel",
}

RUNNABLE_MODES: frozenset[str] = frozenset(m.canonical for m in _TUNNEL_MODES if m.runnable)
TAILSCALE_MODES: frozenset[str] = frozenset({"tailscale_serve", "tailscale_funnel"})


def is_tailscale_mode(mode: str) -> bool:
    """Return whether ``mode`` configures Tailscale serve/funnel exposure.

    Args:
        mode (str): Canonical tunnel mode.

    Returns:
        bool: ``True`` for ``tailscale_serve`` or ``tailscale_funnel``.

    Examples:
        >>> is_tailscale_mode("tailscale_funnel")
        True
        >>> is_tailscale_mode("cloudflare")
        False
    """
    return mode in TAILSCALE_MODES


def normalize_tunnel_mode(raw: str) -> str:
    """Return the canonical tunnel mode for a user-supplied value.

    Args:
        raw (str): User input (hyphen or underscore form).

    Returns:
        str: Canonical mode string.

    Raises:
        ValueError: When the mode is not recognised.

    Examples:
        >>> normalize_tunnel_mode("tailscale-serve")
        'tailscale_serve'
    """
    key = raw.strip().lower()
    if key not in MODE_ALIASES:
        allowed = "cloudflare, cloudflare-quick, ngrok, tailscale-serve, tailscale-funnel"
        msg = f"unknown --mode {raw!r} (expected one of: {allowed})"
        raise ValueError(msg)
    return MODE_ALIASES[key]


def tunnel_mode_spec(mode: str) -> TunnelModeSpec:
    """Return metadata for a canonical tunnel mode.

    Args:
        mode (str): Canonical mode id.

    Returns:
        TunnelModeSpec: Mode metadata.

    Raises:
        ValueError: When ``mode`` is not registered.

    Examples:
        >>> tunnel_mode_spec("ngrok").binary
        'ngrok'
    """
    spec = TUNNEL_MODE_BY_CANONICAL.get(mode)
    if spec is None:
        msg = f"unknown tunnel mode {mode!r}"
        raise ValueError(msg)
    return spec


def tunnel_binary(mode: str) -> str:
    """Return the provider binary name for ``mode``.

    Args:
        mode (str): Canonical mode id.

    Returns:
        str: Executable name (e.g. ``cloudflared``).

    Examples:
        >>> tunnel_binary("cloudflare")
        'cloudflared'
    """
    return tunnel_mode_spec(mode).binary


def install_hint_for_binary(binary: str) -> str:
    """Return operator install instructions for a provider binary.

    Args:
        binary (str): Executable name.

    Returns:
        str: Install hint text.

    Examples:
        >>> "ngrok" in install_hint_for_binary("ngrok")
        True
    """
    return _INSTALL_HINT_BY_BINARY.get(binary, f"install {binary}")


def secret_binding(mode: str) -> tuple[str | None, str | None, str | None]:
    """Return ``(logical_key, config_ref_path, config_ref_value)`` for setup.

    Args:
        mode (str): Canonical tunnel mode.

    Returns:
        tuple[str | None, str | None, str | None]: Secret binding, or all-None when the
        mode stores no secret.

    Examples:
        >>> secret_binding("ngrok")[1]
        'infrastructure.tunnel.ngrok_authtoken'
        >>> secret_binding("tailscale_serve")
        (None, None, None)
    """
    spec = tunnel_mode_spec(mode)
    return spec.secret_logical_key, spec.secret_config_path, spec.secret_config_ref


def stale_setup_fields(
    mode: str,
    *,
    store_secret: bool,
    clear_stale_hostname: bool = False,
) -> list[str]:
    """Return config paths to clear so no stale credential lingers after setup.

    Args:
        mode (str): Canonical tunnel mode.
        store_secret (bool): Whether a provider secret is being stored this run
            (cloudflare token vs. cloudflared config file).
        clear_stale_hostname (bool): Whether to remove a prior provider's hostname
            (typically when switching tunnel modes without ``--hostname``).

    Returns:
        list[str]: Dotted paths under ``infrastructure.tunnel`` to delete.

    Examples:
        >>> stale_setup_fields("cloudflare", store_secret=False, clear_stale_hostname=True)
        ['infrastructure.tunnel.ngrok_authtoken', 'infrastructure.tunnel.token', 'infrastructure.tunnel.hostname']
        >>> stale_setup_fields("ngrok", store_secret=True, clear_stale_hostname=False)
        ['infrastructure.tunnel.token', 'infrastructure.tunnel.config_path']
    """
    return list(
        tunnel_mode_spec(mode).stale_setup_field_paths(
            store_secret=store_secret,
            clear_stale_hostname=clear_stale_hostname,
        ),
    )


def tunnel_cfg_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``infrastructure.tunnel`` sub-dict from a raw sevn.json document.

    Args:
        raw (dict[str, Any]): Parsed sevn.json document.

    Returns:
        dict[str, Any]: Tunnel sub-config (possibly empty).

    Examples:
        >>> tunnel_cfg_from_raw({"infrastructure": {"tunnel": {"mode": "ngrok"}}})
        {'mode': 'ngrok'}
        >>> tunnel_cfg_from_raw({})
        {}
    """
    infra = raw.get("infrastructure")
    if not isinstance(infra, dict):
        return {}
    tunnel = infra.get("tunnel")
    return cast("dict[str, Any]", tunnel) if isinstance(tunnel, dict) else {}


def tunnel_cfg_from_workspace(ws: WorkspaceConfig) -> dict[str, Any]:
    """Extract ``infrastructure.tunnel`` from a parsed workspace config.

    Args:
        ws (WorkspaceConfig): Active workspace document.

    Returns:
        dict[str, Any]: Tunnel sub-config (possibly empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     workspace_root=".",
        ...     infrastructure={"tunnel": {"mode": "cloudflare"}},
        ... )
        >>> tunnel_cfg_from_workspace(ws)["mode"]
        'cloudflare'
    """
    extra = ws.model_extra or {}
    infra = extra.get("infrastructure")
    if not isinstance(infra, dict):
        return {}
    tunnel = infra.get("tunnel")
    return cast("dict[str, Any]", tunnel) if isinstance(tunnel, dict) else {}


def tunnel_cfg_from_disk(
    ws: WorkspaceConfig,
    *,
    sevn_json: Path | None = None,
) -> dict[str, Any]:
    """Return ``infrastructure.tunnel`` from on-disk ``sevn.json`` when readable.

    Gateway and Telegram code keep an in-memory :class:`WorkspaceConfig` from boot;
    ``sevn tunnel setup`` mutates ``sevn.json`` without restarting. When the on-disk
    document includes ``infrastructure.tunnel``, that section wins (including
    ``mode: none``); otherwise the in-memory document is used.

    Args:
        ws (WorkspaceConfig): Active workspace document (used for fallback).
        sevn_json (Path | None): Explicit ``sevn.json`` path (e.g. gateway layout).

    Returns:
        dict[str, Any]: Tunnel sub-config (possibly empty).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     workspace_root=".",
        ...     infrastructure={"tunnel": {"mode": "none"}},
        ... )
        >>> tunnel_cfg_from_disk(ws).get("mode", "none")
        'none'
    """
    from pathlib import Path

    from sevn.config.loader import bound_sevn_json_path, resolve_sevn_json_path

    path = sevn_json
    if path is None:
        bound = bound_sevn_json_path()
        if bound.is_file():
            path = bound
    if path is None:
        start = Path(ws.workspace_root).expanduser()
        path = resolve_sevn_json_path(start=start if start.is_dir() else None)
    if path is None or not path.is_file():
        return tunnel_cfg_from_workspace(ws)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tunnel_cfg_from_workspace(ws)
    infra = raw.get("infrastructure")
    if isinstance(infra, dict) and "tunnel" in infra:
        return tunnel_cfg_from_raw(raw)
    return tunnel_cfg_from_workspace(ws)


def runtime_secret_fields(mode: str) -> tuple[str, ...]:
    """Return tunnel sub-dict fields whose secrets should be expanded for ``mode``.

    Args:
        mode (str): Canonical tunnel mode from ``infrastructure.tunnel.mode``.

    Returns:
        tuple[str, ...]: Field names to expand (empty when none or unknown).

    Examples:
        >>> runtime_secret_fields("cloudflare")
        ('token',)
        >>> runtime_secret_fields("tailscale_funnel")
        ()
    """
    spec = TUNNEL_MODE_BY_CANONICAL.get(mode)
    if spec is None or spec.runtime_secret_field is None:
        return ()
    return (spec.runtime_secret_field,)


def coerce_tunnel_local_port(tunnel_config: dict[str, Any]) -> int:
    """Return the local port ngrok/tailscale forward to.

    Args:
        tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict.

    Returns:
        int: Positive local port, or :data:`DEFAULT_TUNNEL_LOCAL_PORT` when unset/invalid.

    Examples:
        >>> coerce_tunnel_local_port({"local_port": 8080})
        8080
        >>> coerce_tunnel_local_port({})
        3001
    """
    raw = tunnel_config.get("local_port")
    try:
        port = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TUNNEL_LOCAL_PORT
    return port if port > 0 else DEFAULT_TUNNEL_LOCAL_PORT


def build_tunnel_launch(
    mode: str,
    tunnel_config: dict[str, Any],
) -> tuple[list[str], dict[str, str] | None]:
    """Build the ``(argv, env)`` used to spawn the tunnel for ``mode``.

    Args:
        mode (str): One of :data:`RUNNABLE_MODES`.
        tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict (secrets
            already expanded to plaintext by the caller).

    Returns:
        tuple[list[str], dict[str, str] | None]: Command argv and optional environment
        overrides (ngrok passes the authtoken via ``NGROK_AUTHTOKEN``).

    Raises:
        RuntimeError: When the provider binary is missing or credentials are absent.

    Examples:
        >>> build_tunnel_launch.__name__
        'build_tunnel_launch'
    """
    if mode == "cloudflare_quick":
        binary = shutil.which("cloudflared")
        if not binary:
            raise RuntimeError(
                "cloudflared binary not found on PATH; install cloudflared first",
            )
        port = coerce_tunnel_local_port(tunnel_config)
        return [binary, "tunnel", "--url", f"http://127.0.0.1:{port}"], None

    if mode == "cloudflare":
        binary = shutil.which("cloudflared")
        if not binary:
            raise RuntimeError(
                "cloudflared binary not found on PATH; install cloudflared first",
            )
        token = str(tunnel_config.get("token") or "").strip()
        config_path = str(tunnel_config.get("config_path") or "").strip()
        metrics_addr = str(tunnel_config.get("metrics_addr") or DEFAULT_METRICS_ADDR).strip()
        argv = [binary, "tunnel", "--metrics", metrics_addr]
        if token:
            argv += ["run", "--token", token]
        elif config_path:
            argv += ["--config", config_path, "run"]
        else:
            raise RuntimeError(
                "infrastructure.tunnel.token or infrastructure.tunnel.config_path required"
                " to start cloudflared",
            )
        return argv, None

    if mode == "ngrok":
        binary = shutil.which("ngrok")
        if not binary:
            raise RuntimeError("ngrok binary not found on PATH; install ngrok first")
        authtoken = str(tunnel_config.get("ngrok_authtoken") or "").strip()
        if not authtoken:
            raise RuntimeError("infrastructure.tunnel.ngrok_authtoken required to start ngrok")
        argv = [binary, "http", str(coerce_tunnel_local_port(tunnel_config))]
        hostname = str(tunnel_config.get("hostname") or "").strip()
        if hostname:
            argv += ["--domain", hostname]
        env = dict(os.environ)
        env["NGROK_AUTHTOKEN"] = authtoken
        return argv, env

    binary = shutil.which("tailscale")
    if not binary:
        raise RuntimeError("tailscale binary not found on PATH; install tailscale first")
    sub = "serve" if mode == "tailscale_serve" else "funnel"
    return [binary, sub, "--bg", str(coerce_tunnel_local_port(tunnel_config))], None


def build_tunnel_stop(mode: str) -> list[str]:
    """Return argv to tear down Tailscale serve/funnel exposure.

    Tailscale configures ``tailscaled`` via a short CLI invocation; stopping must
    call ``serve reset`` / ``funnel reset`` rather than signalling the CLI pid.

    Args:
        mode (str): ``tailscale_serve`` or ``tailscale_funnel``.

    Returns:
        list[str]: Provider argv for :func:`subprocess.run`.

    Raises:
        RuntimeError: When the tailscale binary is missing.
        ValueError: When ``mode`` is not a Tailscale tunnel mode.

    Examples:
        >>> import shutil as _sh
        >>> build_tunnel_stop("tailscale_funnel")[-1] if _sh.which("tailscale") else "reset"
        'reset'
    """
    if not is_tailscale_mode(mode):
        raise ValueError(f"build_tunnel_stop does not support mode={mode!r}")
    binary = shutil.which("tailscale")
    if not binary:
        raise RuntimeError("tailscale binary not found on PATH; install tailscale first")
    sub = "serve" if mode == "tailscale_serve" else "funnel"
    return [binary, sub, "reset"]


async def prepare_tunnel_runtime_cfg(
    tunnel_config: dict[str, Any],
    *,
    gateway_port: int | None,
    content_root: Path,
    secrets_backend: SecretsBackendSectionConfig | None,
) -> dict[str, Any]:
    """Return a runnable tunnel config with secrets expanded and local port defaulted.

    Copies ``tunnel_config`` and (a) fills ``local_port`` from the gateway port when
    unset, and (b) expands any ``${SECRET:…}``/``${ENV:…}`` refs in the active mode's
    secret field to plaintext so
    :class:`~sevn.infrastructure.tunnel_manager.TunnelManager` can spawn the provider.

    Args:
        tunnel_config (dict[str, Any]): Raw ``infrastructure.tunnel`` sub-dict.
        gateway_port (int | None): Gateway listen port used as the default local port.
        content_root (Path): Workspace content root for encrypted-file backends.
        secrets_backend (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``.

    Returns:
        dict[str, Any]: Copy of ``tunnel_config`` with secrets resolved to plaintext.

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> cfg = asyncio.run(
        ...     prepare_tunnel_runtime_cfg(
        ...         {"mode": "tailscale_funnel"},
        ...         gateway_port=3001,
        ...         content_root=Path("."),
        ...         secrets_backend=None,
        ...     )
        ... )
        >>> cfg["local_port"]
        3001
    """
    resolved: dict[str, Any] = dict(tunnel_config)
    if not resolved.get("local_port"):
        resolved["local_port"] = gateway_port or DEFAULT_TUNNEL_LOCAL_PORT

    mode = str(resolved.get("mode") or "none")
    fields = runtime_secret_fields(mode)
    needs_expand = any("${" in str(resolved.get(field) or "") for field in fields)
    if not needs_expand:
        return resolved

    from sevn.config.workspace_config import effective_encrypted_file_key_source
    from sevn.security.secrets.cache import ResolvedSecretsCache
    from sevn.security.secrets.factory import secrets_chain_from_workspace
    from sevn.security.secrets.passphrase_prime import reconcile_unlock_env_with_keychain
    from sevn.security.secrets.value_expand import expand_refs_env_then_secret

    key_source = effective_encrypted_file_key_source(secrets_backend)
    await reconcile_unlock_env_with_keychain(key_source=key_source)

    chain = secrets_chain_from_workspace(content_root, secrets_backend)
    cache = ResolvedSecretsCache(chain, ttl_seconds=0)
    for field in fields:
        raw = str(resolved.get(field) or "").strip()
        if raw and "${" in raw:
            resolved[field] = await expand_refs_env_then_secret(raw, cache)
    return resolved


__all__ = [
    "CF_TOKEN_CONFIG_REF",
    "CF_TOKEN_LOGICAL_KEY",
    "DEFAULT_METRICS_ADDR",
    "DEFAULT_TUNNEL_LOCAL_PORT",
    "MODE_ALIASES",
    "NGROK_AUTHTOKEN_CONFIG_REF",
    "NGROK_AUTHTOKEN_LOGICAL_KEY",
    "RUNNABLE_MODES",
    "TAILSCALE_MODES",
    "TUNNEL_MODE_BY_CANONICAL",
    "TunnelModeSpec",
    "build_tunnel_launch",
    "build_tunnel_stop",
    "coerce_tunnel_local_port",
    "is_tailscale_mode",
    "normalize_tunnel_mode",
    "prepare_tunnel_runtime_cfg",
    "runtime_secret_fields",
    "secret_binding",
    "stale_setup_fields",
    "tunnel_binary",
    "tunnel_cfg_from_disk",
    "tunnel_cfg_from_raw",
    "tunnel_cfg_from_workspace",
    "tunnel_mode_spec",
]
