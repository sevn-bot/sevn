"""HTTP gateway and session handling (`specs/17-gateway.md`).

Module: sevn.gateway
Depends: gateway boot sweep, FastAPI compose module, channel_types

Exports:
    ChannelAdapter — webhook translation contract (from :mod:`sevn.gateway.channel_types`).
    ChannelRouter — inbound/outbound pipelines (lazy import from :mod:`sevn.gateway.channel_router`).
    CommandDispatcher — pre-LLM command stub.
    IncomingMessage — unified inbound envelope (from :mod:`sevn.gateway.channel_types`).
    OutgoingMessage — unified outbound envelope (from :mod:`sevn.gateway.channel_types`).
    SessionManager — SQLite session façade + dispatch markers.
    create_app — ASGI factory (:mod:`sevn.gateway.http_server`).
    run_harness_boot_sweep — harness snapshot sweep (`specs/16`).
"""

from __future__ import annotations

from typing import Any

from sevn.gateway.boot import run_harness_boot_sweep
from sevn.gateway.channel_types import ChannelAdapter, IncomingMessage, OutgoingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.session_manager import SessionManager

__all__ = [
    "ChannelAdapter",
    "ChannelRouter",
    "CommandDispatcher",
    "IncomingMessage",
    "OutgoingMessage",
    "SessionManager",
    "create_app",
    "run_harness_boot_sweep",
]


def __getattr__(name: str) -> Any:
    """Lazy-import heavy gateway modules to keep ``sevn.gateway`` package init cheap.

    Importing :mod:`sevn.gateway.channel_types` must not eagerly load
    :mod:`sevn.gateway.channel_router` (which imports channel adapters).

    Args:
        name (str): Attribute being looked up on the module.

    Returns:
        Any: The resolved attribute.

    Raises:
        AttributeError: For any unknown attribute name.

    Examples:
        >>> import sevn.gateway as g
        >>> g.create_app.__name__
        'create_app'
        >>> g.ChannelRouter.__name__
        'ChannelRouter'
    """
    if name == "create_app":
        from sevn.gateway.http_server import create_app as create_app_impl

        return create_app_impl
    if name == "ChannelRouter":
        from sevn.gateway.channel_router import ChannelRouter as channel_router_impl

        return channel_router_impl
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
