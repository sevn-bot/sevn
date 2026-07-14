"""Gateway boot hooks for provider/channel telemetry registration (lane #1 W2.4).

Module: sevn.gateway.runtime.telemetry_boot
Depends: sevn.gateway.boot_registry, sevn.config.workspace_config

Exports:
    register_telemetry_boot_hooks — register channel boot hooks via CW-2 registry.
"""

from __future__ import annotations

from sevn.gateway.boot_registry import BootContext, register_boot_hook


async def _register_enabled_channels(ctx: BootContext) -> None:
    """Register enabled channel adapters in mission state at gateway boot.

    Args:
        ctx (BootContext): Lifespan startup context.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_register_enabled_channels)
        True
    """
    state = getattr(ctx.app.state, "mission_control_state", None)
    if state is None:
        return
    channels = ctx.workspace.channels
    if channels is None:
        return
    if channels.telegram is not None and channels.telegram.enabled is not False:
        state.register_channel("telegram", adapter_type="telegram")
        state.update_channel("telegram", connected=True, connection_state="connected")
    if channels.webchat is not None and channels.webchat.enabled is not False:
        state.register_channel("webchat", adapter_type="webchat")
        state.update_channel("webchat", connected=True, connection_state="connected")


def register_telemetry_boot_hooks() -> None:
    """Register telemetry boot hooks (idempotent module import side-effect).

    Examples:
        >>> from sevn.gateway import boot_registry as br
        >>> any(name == "telemetry_channels" for _, name, _ in br._BOOT_HOOKS)
        True
    """
    register_boot_hook("telemetry_channels", _register_enabled_channels, priority=50)


register_telemetry_boot_hooks()

__all__ = ["register_telemetry_boot_hooks"]
