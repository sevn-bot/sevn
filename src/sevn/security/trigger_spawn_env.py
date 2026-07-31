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

# Allowlist for webhook-triggered subprocess host env (issue #81). Workspace/sandbox
# shims inject SEVN_* keys explicitly after this base is resolved.
_WEBHOOK_ENV_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "LC_NUMERIC",
        "LC_TIME",
        "LC_MONETARY",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TERM",
        "COLORTERM",
        "NO_COLOR",
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
        "PWD",
        "HOSTNAME",
        "SSH_AUTH_SOCK",
        "DISPLAY",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "HOMEDRIVE",
        "HOMEPATH",
        "USERPROFILE",
    },
)

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
        >>> env["PATH"]
        '/usr/bin'
    """
    source = dict(os.environ if base is None else base)
    return {key: value for key, value in source.items() if key.upper() in _WEBHOOK_ENV_ALLOWLIST}


def _should_minimize_host_env(*, scope_key: str | None = None) -> bool:
    """Return ``True`` when subprocess host env must be webhook-minimal.

    Args:
        scope_key (str | None): Optional gateway session scope key.

    Returns:
        bool: Whether to strip host secrets before sandbox/skill shims.

    Examples:
        >>> _should_minimize_host_env(scope_key="trigger:webhook:x")
        True
    """
    if _WEBHOOK_MINIMAL_HOST_ENV.get():
        return True
    return bool(scope_key and is_webhook_trigger_scope(scope_key))


def host_env_base_for_subprocess(
    *,
    base: Mapping[str, str] | None = None,
    scope_key: str | None = None,
) -> dict[str, str]:
    """Resolve the host env base before workspace/sandbox shims are applied.

    Args:
        base (Mapping[str, str] | None): Optional explicit base env.
        scope_key (str | None): Gateway session scope key for trigger webhook sessions.

    Returns:
        dict[str, str]: Full or minimized host env depending on webhook ingress context.

    Examples:
        >>> isinstance(host_env_base_for_subprocess(), dict)
        True
    """
    if _should_minimize_host_env(scope_key=scope_key):
        return minimal_webhook_host_env(base=base)
    return dict(os.environ if base is None else base)


def augment_operator_path_for_subprocess(
    env: Mapping[str, str] | None = None,
    *,
    scope_key: str | None = None,
) -> dict[str, str]:
    """Like :func:`sevn.runtime.operator_path.augment_operator_path` with webhook filtering.

    Args:
        env (Mapping[str, str] | None): Optional explicit base env.
        scope_key (str | None): Gateway session scope key for trigger webhook sessions.

    Returns:
        dict[str, str]: Operator PATH augmentation on the resolved host env base.

    Examples:
        >>> "PATH" in augment_operator_path_for_subprocess({"PATH": "/usr/bin"})
        True
    """
    return augment_operator_path(
        host_env_base_for_subprocess(base=env, scope_key=scope_key),
    )


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
