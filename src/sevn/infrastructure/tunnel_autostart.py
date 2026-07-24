"""Persistent-tunnel autostart seam shared by gateway boot and the Telegram menu.

Module: sevn.infrastructure.tunnel_autostart
Depends: asyncio, loguru, sevn.infrastructure.tunnel_config, sevn.infrastructure.tunnel_manager

The operator turns the configured tunnel *on* from the Telegram "My sevn bot"
menu. "On" stamps ``infrastructure.tunnel.autostart = true`` in ``sevn.json`` and
starts the provider now; because the gateway itself is a launchd/systemd daemon
that survives host restart, :func:`autostart_tunnel_if_enabled` re-launches the
tunnel on every gateway boot so it "acts like the gateway". "Off" clears the flag
and stops the provider.

Exports:
    tunnel_autostart_enabled — whether ``infrastructure.tunnel.autostart`` is set for a runnable mode.
    start_configured_tunnel — expand secrets + spawn the configured provider (raises on failure).
    autostart_tunnel_if_enabled — best-effort boot start gated on the autostart flag.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from sevn.infrastructure.tunnel_config import RUNNABLE_MODES, prepare_tunnel_runtime_cfg

if TYPE_CHECKING:
    from pathlib import Path

    from sevn.config.workspace_config import SecretsBackendSectionConfig
    from sevn.infrastructure.tunnel_manager import TunnelManager, TunnelStatus

#: Upper bound on a single tunnel spawn. ``cloudflare_quick`` self-bounds its URL read
#: (~45s), but a ``tailscale`` CLI can hang with no subprocess timeout (daemon down /
#: pending auth); wrapping the spawn keeps a stuck provider from stalling gateway boot.
TUNNEL_START_TIMEOUT_S: float = 60.0


def tunnel_autostart_enabled(tunnel_config: dict[str, Any]) -> bool:
    """Return whether the tunnel should auto-start at gateway boot.

    True only when ``infrastructure.tunnel.autostart`` is truthy *and* the
    configured mode is one :class:`~sevn.infrastructure.tunnel_manager.TunnelManager`
    can actually spawn.

    Args:
        tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict.

    Returns:
        bool: ``True`` when boot should start the tunnel.

    Examples:
        >>> tunnel_autostart_enabled({"mode": "cloudflare", "autostart": True})
        True
        >>> tunnel_autostart_enabled({"mode": "cloudflare", "autostart": False})
        False
        >>> tunnel_autostart_enabled({"mode": "none", "autostart": True})
        False
    """
    if not bool(tunnel_config.get("autostart")):
        return False
    return str(tunnel_config.get("mode") or "none") in RUNNABLE_MODES


async def start_configured_tunnel(
    *,
    tunnel_config: dict[str, Any],
    gateway_port: int | None,
    content_root: Path,
    secrets_backend: SecretsBackendSectionConfig | None,
    manager: TunnelManager,
) -> TunnelStatus:
    """Expand secrets and spawn the configured tunnel provider.

    Args:
        tunnel_config (dict[str, Any]): Raw ``infrastructure.tunnel`` sub-dict.
        gateway_port (int | None): Gateway listen port (default local forward port).
        content_root (Path): Workspace content root for encrypted-file backends.
        secrets_backend (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``.
        manager (TunnelManager): Manager bound to the shared tunnel pid file.

    Returns:
        TunnelStatus: State after the spawn attempt.

    Raises:
        RuntimeError: When the provider binary is missing, credentials are absent, or the
            spawn does not complete within :data:`TUNNEL_START_TIMEOUT_S`.
        ValueError: When the configured mode is not runnable.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(start_configured_tunnel)
        True
    """
    runtime_cfg = await prepare_tunnel_runtime_cfg(
        tunnel_config,
        gateway_port=gateway_port,
        content_root=content_root,
        secrets_backend=secrets_backend,
    )
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(manager.start, runtime_cfg, confirm=True),
            timeout=TUNNEL_START_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise RuntimeError(
            f"tunnel provider did not start within {TUNNEL_START_TIMEOUT_S:.0f}s",
        ) from exc


async def autostart_tunnel_if_enabled(
    *,
    tunnel_config: dict[str, Any],
    gateway_port: int | None,
    content_root: Path,
    secrets_backend: SecretsBackendSectionConfig | None,
    manager: TunnelManager,
) -> TunnelStatus | None:
    """Start the configured tunnel at boot when autostart is enabled (best effort).

    Returns ``None`` (and never raises) when autostart is disabled, the mode is not
    runnable, or the provider fails to spawn — a missing ``cloudflared`` binary or an
    unresolved secret must not crash gateway boot.

    Args:
        tunnel_config (dict[str, Any]): ``infrastructure.tunnel`` sub-dict.
        gateway_port (int | None): Gateway listen port (default local forward port).
        content_root (Path): Workspace content root for encrypted-file backends.
        secrets_backend (SecretsBackendSectionConfig | None): Parsed ``secrets_backend``.
        manager (TunnelManager): Manager bound to the shared tunnel pid file.

    Returns:
        TunnelStatus | None: Live status when a start was attempted, else ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(autostart_tunnel_if_enabled)
        True
    """
    if not tunnel_autostart_enabled(tunnel_config):
        return None
    try:
        status = await start_configured_tunnel(
            tunnel_config=tunnel_config,
            gateway_port=gateway_port,
            content_root=content_root,
            secrets_backend=secrets_backend,
            manager=manager,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        # OSError covers a failed subprocess spawn (e.g. binary vanished between the
        # PATH check and exec); RuntimeError covers the start timeout / missing creds.
        logger.warning("tunnel autostart skipped: {}", exc)
        return None
    if status.healthy:
        logger.info(
            "tunnel autostart: mode={} pid={} url={}",
            status.mode,
            status.pid,
            status.mission_control_url or status.public_url or "",
        )
    else:
        logger.warning("tunnel autostart did not become healthy: {}", status.error or "unknown")
    return status


__all__ = [
    "autostart_tunnel_if_enabled",
    "start_configured_tunnel",
    "tunnel_autostart_enabled",
]
