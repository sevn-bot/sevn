"""Turn-scoped routing profile ``secrets_scope`` for secret logical-key prefixing.

Module: sevn.security.secrets.routing_scope
Depends: contextvars

Exports:
    bind_routing_secrets_scope — set scope for the current async task.
    current_routing_secrets_scope — read active scope (``None`` when unset).
    reset_routing_secrets_scope — restore prior scope token.
    scoped_secret_logical_key — prefix a logical key with the active scope.

Examples:
    >>> from sevn.security.secrets.routing_scope import current_routing_secrets_scope
    >>> current_routing_secrets_scope() is None
    True
"""

from __future__ import annotations

import contextvars

_routing_secrets_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "routing_secrets_scope",
    default=None,
)


def current_routing_secrets_scope() -> str | None:
    """Return the active routing profile ``secrets_scope`` for this task.

    Returns:
        str | None: Scope label when a gateway turn bound one; else ``None``.

    Examples:
        >>> current_routing_secrets_scope() is None
        True
    """
    return _routing_secrets_scope.get()


def scoped_secret_logical_key(logical_key: str, *, scope: str | None = None) -> str:
    """Prefix *logical_key* with the active routing ``secrets_scope``.

    Args:
        logical_key (str): Backend logical key from ``${SECRET:source:key}``.
        scope (str | None): Explicit scope; defaults to :func:`current_routing_secrets_scope`.

    Returns:
        str: Scoped key ``"{scope}/{logical_key}"`` when scope is set.

    Examples:
        >>> scoped_secret_logical_key("api.token", scope="research")
        'research/api.token'
        >>> scoped_secret_logical_key("api.token", scope=None)
        'api.token'
    """
    active = scope if scope is not None else current_routing_secrets_scope()
    key = logical_key.strip()
    label = active.strip() if isinstance(active, str) else ""
    if not label:
        return key
    return f"{label.strip().strip('/')}/{key}"


def bind_routing_secrets_scope(scope: str | None) -> contextvars.Token[str | None]:
    """Bind *scope* for secret logical-key prefixing on the current task.

    Args:
        scope (str | None): Profile ``secrets_scope`` label; ``None`` clears overlay.

    Returns:
        contextvars.Token[str | None]: Token for :func:`reset_routing_secrets_scope`.

    Examples:
        >>> token = bind_routing_secrets_scope("research")
        >>> current_routing_secrets_scope()
        'research'
        >>> reset_routing_secrets_scope(token)
        >>> current_routing_secrets_scope() is None
        True
    """
    return _routing_secrets_scope.set(scope)


def reset_routing_secrets_scope(token: contextvars.Token[str | None]) -> None:
    """Restore the prior routing secrets scope after a turn.

    Args:
        token (contextvars.Token[str | None]): Token from :func:`bind_routing_secrets_scope`.

    Examples:
        >>> token = bind_routing_secrets_scope("ops")
        >>> reset_routing_secrets_scope(token)
        >>> current_routing_secrets_scope() is None
        True
    """
    _routing_secrets_scope.reset(token)


__all__ = [
    "bind_routing_secrets_scope",
    "current_routing_secrets_scope",
    "reset_routing_secrets_scope",
    "scoped_secret_logical_key",
]
