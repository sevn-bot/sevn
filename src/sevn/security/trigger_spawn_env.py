"""Minimize host env inheritance on webhook ingress paths (issue #81).

Module: sevn.security.trigger_spawn_env
Depends: contextvars, os, sevn.runtime.operator_path

Exports:
    augment_operator_path_for_subprocess — PATH augmentation on filtered host env.
    bind_webhook_minimal_host_env — context manager for webhook HTTP handlers.
    host_env_base_for_subprocess — host env base for sandbox/skill subprocesses.
    is_webhook_trigger_scope — detect trigger sessions spawned from webhooks.
    minimal_webhook_host_env — strip secret keys from a host env mapping.
    redact_telegram_bot_token — redact bot tokens from free-form error text.
"""

from __future__ import annotations

import contextvars
import os
import re
from collections.abc import Iterator  # noqa: TC003
from contextlib import contextmanager
from typing import TYPE_CHECKING, Final

from sevn.runtime.operator_path import augment_operator_path

if TYPE_CHECKING:
    from collections.abc import Mapping

_WEBHOOK_MINIMAL_HOST_ENV: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "webhook_minimal_host_env",
    default=False,
)

_BLOCKED_ENV_SUFFIXES: Final[tuple[str, ...]] = (
    "_API_KEY",
    "_SECRET",
    "_TOKEN",
    "_PASSWORD",
    "_PASSPHRASE",
)

_BLOCKED_ENV_KEYS: Final[frozenset[str]] = frozenset(
    {
        "SEVN_GATEWAY_TOKEN",
        "SEVN_SECRETS_PASSPHRASE",
        "SEVN_DASHBOARD_JWT_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "BOT_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    },
)

_ALLOWED_TOKEN_KEYS: Final[frozenset[str]] = frozenset({"SEVN_SESSION_TOKEN"})

_TELEGRAM_BOT_URL_RE = re.compile(r"/bot[^/]+/", re.IGNORECASE)


def is_webhook_trigger_scope(scope_key: str) -> bool:
    """Return ``True`` for non-interactive sessions created from signed webhooks.

    Args:
        scope_key (str): Gateway session scope key.

    Returns:
        bool: Whether subprocess host env should be minimized.

    Examples:
        >>> is_webhook_trigger_scope("trigger:webhook:abc")
        True
        >>> is_webhook_trigger_scope("telegram:42")
        False
    """
    return scope_key.startswith("trigger:webhook:")


def _env_key_blocked(key: str) -> bool:
    """Return ``True`` when ``key`` must not pass to webhook subprocesses.

    Args:
        key (str): Environment variable name.

    Returns:
        bool: Whether the key is blocked.

    Examples:
        >>> _env_key_blocked("OPENAI_API_KEY")
        True
        >>> _env_key_blocked("SEVN_SESSION_TOKEN")
        False
    """
    upper = key.upper()
    if upper in _ALLOWED_TOKEN_KEYS:
        return False
    if upper in _BLOCKED_ENV_KEYS:
        return True
    return any(upper.endswith(suffix) for suffix in _BLOCKED_ENV_SUFFIXES)


def minimal_webhook_host_env(*, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a host env with gateway secrets stripped for webhook ingress paths.

    Args:
        base (Mapping[str, str] | None): Optional starting env; defaults to ``os.environ``.

    Returns:
        dict[str, str]: Filtered env safe to merge into skill/sandbox subprocesses.

    Examples:
        >>> env = minimal_webhook_host_env(base={"PATH": "/usr/bin", "OPENAI_API_KEY": "x"})
        >>> "OPENAI_API_KEY" not in env
        True
    """
    source = dict(os.environ if base is None else base)
    return {key: value for key, value in source.items() if not _env_key_blocked(key)}


def host_env_base_for_subprocess(*, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolve the host env base before workspace/sandbox shims are applied.

    Args:
        base (Mapping[str, str] | None): Optional explicit base env.

    Returns:
        dict[str, str]: Full or minimized host env depending on webhook ingress context.

    Examples:
        >>> isinstance(host_env_base_for_subprocess(), dict)
        True
    """
    if _WEBHOOK_MINIMAL_HOST_ENV.get():
        return minimal_webhook_host_env(base=base)
    return dict(os.environ if base is None else base)


def augment_operator_path_for_subprocess(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Like :func:`sevn.runtime.operator_path.augment_operator_path` with webhook filtering.

    Args:
        env (Mapping[str, str] | None): Optional explicit base env.

    Returns:
        dict[str, str]: Operator PATH augmentation on the resolved host env base.

    Examples:
        >>> "PATH" in augment_operator_path_for_subprocess({"PATH": "/usr/bin"})
        True
    """
    return augment_operator_path(host_env_base_for_subprocess(base=env))


@contextmanager
def bind_webhook_minimal_host_env() -> Iterator[None]:
    """Bind webhook-minimal host env for the current async context.

    Yields:
        None: While bound, :func:`host_env_base_for_subprocess` strips secret env keys.

    Returns:
        None: Always ``None``.

    Examples:
        >>> with bind_webhook_minimal_host_env():
        ...     _WEBHOOK_MINIMAL_HOST_ENV.get()
        True
    """
    token = _WEBHOOK_MINIMAL_HOST_ENV.set(True)
    try:
        yield
    finally:
        _WEBHOOK_MINIMAL_HOST_ENV.reset(token)


def redact_telegram_bot_token(text: str, token: str) -> str:
    """Remove a Telegram bot token from free-form error text.

    Args:
        text (str): Raw error or log line.
        token (str): Bot token that must not appear in output.

    Returns:
        str: Redacted text.

    Examples:
        >>> redact_telegram_bot_token("bad bot123:ABC", "123:ABC")
        'bad bot<redacted>'
    """
    if not token:
        return text
    cleaned = text.replace(token, "<redacted>")
    return _TELEGRAM_BOT_URL_RE.sub("/bot<redacted>/", cleaned)


__all__ = [
    "augment_operator_path_for_subprocess",
    "bind_webhook_minimal_host_env",
    "host_env_base_for_subprocess",
    "is_webhook_trigger_scope",
    "minimal_webhook_host_env",
    "redact_telegram_bot_token",
]
