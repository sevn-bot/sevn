"""Gateway boot: resolve sandbox image digest once and refuse when absent (C4.2, C5.1).

Module: sevn.gateway.runtime.sandbox_image_boot
Depends: sevn.gateway.boot_registry, sevn.security.sandbox_runtime

Exports:
    ensure_gateway_sandbox_image_ready — fail-closed digest resolve at lifespan start.
    register_sandbox_image_boot_hooks — register the boot hook (import side-effect).
"""

from __future__ import annotations

from loguru import logger

from sevn.gateway.boot_registry import BootContext, register_boot_hook
from sevn.security.sandbox_runtime import (
    configured_sandbox_image,
    docker_daemon_reachable,
    ensure_sandbox_image_ready,
    sandbox_image_stamp_missing,
)


async def ensure_gateway_sandbox_image_ready(ctx: BootContext) -> str | None:
    """Resolve and cache the configured sandbox image at gateway startup (C4.2 / C5.1).

    When Docker is reachable and the configured image is stamped, pulls (if needed)
    and validates the digest once for the process lifetime. Raises
    ``SandboxConfigurationError`` when a stamped release digest is absent and cannot
    be fetched so failure surfaces at boot, not first tier-B turn. Unstamped
    defaults (local checkout) skip with a warning — spawn still fail-closes (W7.4).

    Args:
        ctx (BootContext): Lifespan startup context.

    Returns:
        str | None: Digest-pinned ref when resolved; ``None`` when skipped.

    Raises:
        SandboxConfigurationError: When a stamped Docker image resolve/pull fails.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ensure_gateway_sandbox_image_ready)
        True
    """
    if not docker_daemon_reachable():
        logger.info("sandbox_image_boot skipped: docker daemon not reachable")
        return None
    image = configured_sandbox_image(ctx.workspace)
    if sandbox_image_stamp_missing(image):
        logger.warning(
            "sandbox_image_boot skipped: unstamped image {} (stamp before release)",
            image,
        )
        return None
    pinned = await ensure_sandbox_image_ready(image)
    logger.info("sandbox_image_ready configured={} pinned={}", image, pinned)
    return pinned


async def _sandbox_image_boot_hook(ctx: BootContext) -> None:
    """Boot-hook wrapper (logging path); fail-closed call lives in lifespan.

    Args:
        ctx (BootContext): Lifespan startup context.

    Returns:
        None: Always ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_sandbox_image_boot_hook)
        True
    """
    await ensure_gateway_sandbox_image_ready(ctx)


def register_sandbox_image_boot_hooks() -> None:
    """Register the sandbox image readiness boot hook (idempotent import side-effect).

    Examples:
        >>> from sevn.gateway import boot_registry as br
        >>> any(name == "sandbox_image" for _, name, _ in br._BOOT_HOOKS)
        True
    """
    register_boot_hook("sandbox_image", _sandbox_image_boot_hook, priority=15)


register_sandbox_image_boot_hooks()

__all__ = [
    "ensure_gateway_sandbox_image_ready",
    "register_sandbox_image_boot_hooks",
]
