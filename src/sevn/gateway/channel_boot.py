"""Multi-adapter gateway boot loader.

Module: sevn.gateway.channel_boot
Depends: sevn.gateway.boot_registry, sevn.plugins.registry

Exports:
    ChannelBootArtifacts — webchat transport + config side effects.
    register_enabled_channel_adapters — register all enabled adapters on the router.
    register_channel_boot_hooks — CW-2 boot hook registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from loguru import logger

from sevn.channels.telegram import TelegramAdapter, telegram_config_from_workspace
from sevn.channels.webchat import WebChatAdapter, webchat_config_from_workspace
from sevn.config.sections.channels import channel_is_enabled
from sevn.gateway.boot_registry import BootContext, register_boot_hook
from sevn.gateway.channel_router import ChannelAdapter, ChannelRouter
from sevn.gateway.telegram_resolve import resolve_telegram_bot_token
from sevn.gateway.web_transport import WebChannelTransport
from sevn.plugins.registry import load_channel_plugin_classes


@dataclass(frozen=True, slots=True)
class ChannelBootArtifacts:
    """Side-effect objects produced while registering webchat."""

    webchat_config: Any
    webchat_transport: WebChannelTransport
    webchat_jwt_secret: str | None


async def _resolve_webchat_jwt_secret(ctx: BootContext) -> str | None:
    """Resolve webchat JWT secret via gateway http_server helper.

    Args:
        ctx (BootContext): Boot context.

    Returns:
        str | None: Resolved secret or ``None``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_webchat_jwt_secret)
        True
    """
    from sevn.gateway.http_server import _resolve_webchat_jwt_secret as _resolve

    return await _resolve(ctx.workspace, content_root=ctx.content_root)


def _telegram_webhook_secret(ctx: BootContext) -> str:
    """Return configured Telegram webhook secret token.

    Args:
        ctx (BootContext): Boot context.

    Returns:
        str: Secret token (possibly empty).

    Examples:
        >>> from sevn.gateway.http_server import _telegram_webhook_secret
        >>> isinstance(_telegram_webhook_secret, object)
        True
    """
    from sevn.gateway.http_server import _telegram_webhook_secret as _secret

    return _secret(ctx.workspace) or ""


async def register_enabled_channel_adapters(
    ctx: BootContext,
    *,
    router: ChannelRouter | None = None,
) -> ChannelBootArtifacts | None:
    """Register every enabled channel adapter on ``ctx.gateway_router``.

    Built-in adapters (``telegram``, ``webchat``) and ``sevn.channels`` entry
    points whose ``channels.<name>.enabled`` flag is true are registered once.

    Args:
        ctx (BootContext): Lifespan startup context.
        router (ChannelRouter | None): Override router (defaults to ``ctx.gateway_router``).

    Returns:
        ChannelBootArtifacts | None: Webchat side-effect objects, or ``None`` when skipped.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(register_enabled_channel_adapters)
        True
    """
    gateway_router = router or ctx.gateway_router
    if gateway_router.adapter_names():
        return None
    ws = ctx.workspace
    channels = ws.channels
    conn = ctx.conn
    trace = ctx.trace
    webchat_cfg = None
    web_transport = WebChannelTransport()
    webchat_jwt_secret: str | None = None

    if channel_is_enabled(channels, "telegram"):
        resolved_token: str | None = None
        try:
            resolved_token = await resolve_telegram_bot_token(ws, content_root=ctx.content_root)
        except Exception:
            resolved_token = None
        token_ref = None
        if (
            channels is not None
            and channels.telegram is not None
            and channels.telegram.bot_token_ref
        ):
            token_ref = str(channels.telegram.bot_token_ref).strip()
        tg_secret = _telegram_webhook_secret(ctx)
        if not tg_secret.strip() and channels is not None and channels.telegram:
            mode_raw = (channels.telegram.mode or "poll").strip().lower()
            if mode_raw == "webhook":
                from sevn.gateway.telegram_webhook_secret import ensure_webhook_secret_token

                tg_secret = ensure_webhook_secret_token(ws, ctx.layout.sevn_json_path)
        tg_cfg = telegram_config_from_workspace(
            ws,
            bot_token=(resolved_token or "").strip(),
            webhook_secret_token=tg_secret,
        )
        gateway_router.register_adapter(
            TelegramAdapter(
                config=tg_cfg,
                bot_token_ref=token_ref,
                resolved_bot_token=resolved_token,
                sqlite_conn=conn,
                trace=trace,
                pairing_store=gateway_router.pairing_store,
            ),
        )
        logger.info("channel_boot_registered name=telegram")

    if channel_is_enabled(channels, "webchat"):
        webchat_cfg = webchat_config_from_workspace(ws)
        webchat_jwt_secret = await _resolve_webchat_jwt_secret(ctx)
        gateway_router.register_adapter(
            WebChatAdapter(transport=web_transport, config=webchat_cfg, trace=trace),
        )
        logger.info("channel_boot_registered name=webchat")

    for spec in load_channel_plugin_classes(ws):
        try:
            factory = getattr(spec.adapter_cls, "from_gateway_boot", None)
            if callable(factory):
                adapter = cast("ChannelAdapter", factory(ctx))
            else:
                adapter = cast("ChannelAdapter", spec.adapter_cls())
            gateway_router.register_adapter(adapter)
            logger.info("channel_boot_registered name={} plugin=true", spec.entry_name)
        except Exception:
            logger.exception("channel_plugin_boot_failed name={}", spec.entry_name)

    runtime = gateway_router.platform_runtime
    for name in gateway_router.adapter_names():
        runtime.register(name, adapter_type=name)
        runtime.mark_connected(name, connected=True)

    if webchat_cfg is None:
        return None
    return ChannelBootArtifacts(
        webchat_config=webchat_cfg,
        webchat_transport=web_transport,
        webchat_jwt_secret=webchat_jwt_secret,
    )


async def _boot_channel_adapters(ctx: BootContext) -> None:
    """CW-2 boot hook wrapper for :func:`register_enabled_channel_adapters`.

    Args:
        ctx (BootContext): Lifespan startup context.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_boot_channel_adapters)
        True
    """
    artifacts = await register_enabled_channel_adapters(ctx)
    if artifacts is None:
        return
    ctx.app.state.webchat_config = artifacts.webchat_config
    ctx.app.state.webchat_transport = artifacts.webchat_transport
    ctx.app.state.webchat_jwt_secret = artifacts.webchat_jwt_secret


def register_channel_boot_hooks() -> None:
    """Register channel adapter boot hook (idempotent module import side-effect).

    Examples:
        >>> from sevn.gateway import boot_registry as br
        >>> any(name == "channel_adapters" for _, name, _ in br._BOOT_HOOKS)
        True
    """
    register_boot_hook("channel_adapters", _boot_channel_adapters, priority=25)


register_channel_boot_hooks()

__all__ = [
    "ChannelBootArtifacts",
    "register_channel_boot_hooks",
    "register_enabled_channel_adapters",
]
