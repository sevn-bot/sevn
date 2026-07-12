"""Command / callback registry (`specs/17-gateway.md` §2.4, §4.1).

Module: sevn.gateway.commands.registry
Depends: typing, dataclasses

Exports:
    CommandSpec — matcher + bypass policy for dispatcher.

Notes:
    ``DEFAULT_COMMAND_SPECS`` (module constant) is re-exported alongside the
    dataclass and consumed by :class:`sevn.gateway.commands.dispatcher.CommandDispatcher`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    """One dispatcher rule evaluated before the inbound scanner."""

    name: str
    matcher: Callable[[object], bool]
    """Return ``True`` when this spec owns the message (scanner bypass)."""


def _match_help(msg: object) -> bool:
    """Match the bare ``/help`` slash command or ``/help <args>`` form.

    Args:
        msg (object): Duck-typed inbound message with ``text`` attribute.

    Returns:
        bool: ``True`` when the text matches.

    Examples:
        >>> class _M:
        ...     text = "/help"
        ...     metadata: dict = {}
        >>> _match_help(_M())
        True
    """
    t = getattr(msg, "text", "") or ""
    if not isinstance(t, str):
        return False
    t = t.strip()
    return t == "/help" or t.startswith("/help ")


def _match_qa_callback(msg: object) -> bool:
    """Quick-action callback namespace (`specs/18-channel-telegram.md` §4.5).

    Args:
        msg (object): Inbound message; checks ``metadata['callback_data']``.

    Returns:
        bool: ``True`` when callback data starts with ``qa:``.

    Examples:
        >>> class _M:
        ...     text = "qa:1:up"
        ...     metadata = {"callback_data": "qa:1:up"}
        >>> _match_qa_callback(_M())
        True
    """

    md = getattr(msg, "metadata", None)
    if not isinstance(md, dict):
        return False
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        raw = getattr(msg, "text", "") or ""
    if not isinstance(raw, str):
        return False
    return raw.strip().startswith("qa:")


def _match_plan_callback(msg: object) -> bool:
    """Plan approval callback namespace (`specs/18-channel-telegram.md` §10.8).

    Args:
        msg (object): Inbound message; checks ``metadata['callback_data']``.

    Returns:
        bool: ``True`` when callback data starts with ``plan:``.

    Examples:
        >>> class _M:
        ...     text = "plan:abc:approve"
        ...     metadata = {"callback_data": "plan:abc:approve"}
        >>> _match_plan_callback(_M())
        True
    """

    md = getattr(msg, "metadata", None)
    if not isinstance(md, dict):
        return False
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        raw = getattr(msg, "text", "") or ""
    if not isinstance(raw, str):
        return False
    return raw.strip().startswith("plan:")


def _match_menu_callback(msg: object) -> bool:
    """Navigation-style callback namespace (`specs/18-channel-telegram.md` §4).

    Args:
        msg (object): Inbound message; checks ``metadata['callback_data']``.

    Returns:
        bool: ``True`` when callback data is in the ``menu:`` / ``nav:`` namespace.

    Examples:
        >>> class _M:
        ...     text = ""
        ...     metadata = {"callback_data": "menu:home"}
        >>> _match_menu_callback(_M())
        True
    """
    md = getattr(msg, "metadata", None)
    if not isinstance(md, dict):
        return False
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        return False
    return raw.startswith(("menu:", "nav:"))


def _match_menu_slash(msg: object) -> bool:
    """Bare ``/menu`` opens the inline-keyboard menu (recovery Wave B1).

    Args:
        msg (object): Inbound message with ``text`` attribute.

    Returns:
        bool: ``True`` for ``/menu`` or ``/menu <args>``.

    Examples:
        >>> class _M:
        ...     text = "/menu"
        ...     metadata: dict = {}
        >>> _match_menu_slash(_M())
        True
    """
    t = getattr(msg, "text", "") or ""
    if not isinstance(t, str):
        return False
    t = t.strip()
    return t == "/menu" or t.startswith("/menu ")


def _match_topic_command(msg: object) -> bool:
    """Bare ``/topic`` bypasses; ``/topic <free text>`` defers to scanner (§2.4).

    Args:
        msg (object): Inbound message with ``text`` attribute.

    Returns:
        bool: ``True`` only for the bare ``/topic`` form.

    Examples:
        >>> class _M:
        ...     text = "/topic"
        ...     metadata: dict = {}
        >>> _match_topic_command(_M())
        True
    """

    t = getattr(msg, "text", "") or ""
    if not isinstance(t, str):
        return False
    t = t.strip()
    return t == "/topic"


def _match_steer(msg: object) -> bool:
    """Match ``/steer`` bypass; gateway enqueues owner steer text (Wave 7).

    Args:
        msg (object): Inbound message with ``text`` attribute.

    Returns:
        bool: ``True`` for ``/steer`` and ``/steer <args>``.

    Examples:
        >>> class _M:
        ...     text = "/steer now"
        ...     metadata: dict = {}
        >>> _match_steer(_M())
        True
    """

    t = getattr(msg, "text", "") or ""
    if not isinstance(t, str):
        return False
    t = t.strip()
    return t == "/steer" or t.startswith("/steer ")


def _match_slash_command(cmd: str) -> Callable[[object], bool]:
    """Build a matcher that fires for ``cmd`` or ``cmd <args>``.

    Args:
        cmd (str): Slash command literal including the leading ``/``.

    Returns:
        Callable[[object], bool]: Closure matching the bypass form.

    Examples:
        >>> m = _match_slash_command("/start")
        >>> class _M:
        ...     text = "/start"
        ...     metadata: dict = {}
        >>> m(_M())
        True
    """

    def _inner(msg: object) -> bool:
        """Match ``cmd`` exactly or with a trailing space-separated argument.

        Args:
            msg (object): Inbound message with ``text`` attribute.

        Returns:
            bool: Match result.

        Examples:
            >>> _match_slash_command("/new")(type("M", (), {"text": "/new"})())
            True
        """
        t = getattr(msg, "text", "") or ""
        if not isinstance(t, str):
            return False
        t = t.strip()
        return t == cmd or t.startswith(f"{cmd} ")

    return _inner


def _match_ask_config(msg: object) -> bool:
    """Match ``/ask-config`` closed-vocabulary helper.

    Args:
        msg (object): Duck-typed inbound message with ``text`` attribute.

    Returns:
        bool: ``True`` when the text matches.

    Examples:
        >>> class _M:
        ...     text = "/ask-config voice"
        ...     metadata: dict = {}
        >>> _match_ask_config(_M())
        True
    """
    return _match_slash_command("/ask-config")(msg)


def _match_cfg_callback(msg: object) -> bool:
    """Match ``cfg:*`` and shortcut action callback namespaces.

    Args:
        msg (object): Inbound message; checks ``metadata['callback_data']``.

    Returns:
        bool: ``True`` for config and shortcut action callbacks.

    Examples:
        >>> class _M:
        ...     text = ""
        ...     metadata = {"callback_data": "cfg:voice:mode:off"}
        >>> _match_cfg_callback(_M())
        True
    """
    md = getattr(msg, "metadata", None)
    if not isinstance(md, dict):
        return False
    raw = md.get("callback_data")
    if not isinstance(raw, str):
        raw = getattr(msg, "text", "") or ""
    if not isinstance(raw, str):
        return False
    stripped = raw.strip()
    return stripped.startswith(("cfg:", "short:", "act:", "scene:", "form:"))


DEFAULT_COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("start", _match_slash_command("/start")),
    CommandSpec("help", _match_help),
    CommandSpec("new", _match_slash_command("/new")),
    CommandSpec("status", _match_slash_command("/status")),
    CommandSpec("stop", _match_slash_command("/stop")),
    CommandSpec("config", _match_slash_command("/config")),
    CommandSpec("ask_config", _match_ask_config),
    CommandSpec("menu", _match_menu_slash),
    CommandSpec("voice", _match_slash_command("/voice")),
    CommandSpec("model", _match_slash_command("/model")),
    CommandSpec("logs", _match_slash_command("/logs")),
    CommandSpec("traces", _match_slash_command("/traces")),
    CommandSpec("steer", _match_steer),
    CommandSpec("topic_bare", _match_topic_command),
    CommandSpec("callback_nav", _match_menu_callback),
    CommandSpec("callback_cfg", _match_cfg_callback),
    CommandSpec("callback_qa", _match_qa_callback),
    CommandSpec("callback_plan", _match_plan_callback),
)
