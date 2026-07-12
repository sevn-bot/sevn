"""Closed-vocabulary ``/ask-config`` helper (`plan/telegram-commands-design.md` §8.8).

Module: sevn.gateway.commands.ask_config
Depends: sevn.gateway.commands.shortcuts_store

Exports:
    build_ask_config_vocab — closed vocabulary builder.
    parse_ask_config_query — map free-text to vocabulary entry.
    format_ask_config_reply — user-visible suggestion with tap target.
Examples:
    >>> import tempfile
    >>> from pathlib import Path
    >>> r = parse_ask_config_query(Path(tempfile.mkdtemp()), "tts")
    >>> r is not None and r[1] == "cfg:voice"
    True
"""

from __future__ import annotations

from pathlib import Path

from sevn.gateway.commands.shortcuts_store import load_shortcuts

ASK_CONFIG_MENU_PATHS: tuple[str, ...] = (
    "cfg:session",
    "cfg:voice",
    "cfg:models",
    "cfg:security",
    "cfg:shortcuts",
    "cfg:dashboard",
)

_QUERY_ALIASES: dict[str, str] = {
    "tts": "cfg:voice",
    "voice": "cfg:voice",
    "model": "cfg:models",
    "models": "cfg:models",
    "security": "cfg:security",
    "scanner": "cfg:security",
    "shortcut": "cfg:shortcuts",
    "shortcuts": "cfg:shortcuts",
    "dashboard": "cfg:dashboard",
    "pin": "cfg:dashboard",
    "session": "cfg:session",
    "new": "cfg:session",
}


def build_ask_config_vocab(content_root: Path) -> frozenset[str]:
    """Build closed vocabulary of menu paths and shortcut names.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        frozenset[str]: Allowed outputs (never mutates config).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> vocab = build_ask_config_vocab(Path(tempfile.mkdtemp()))
        >>> "cfg:voice" in vocab
        True
    """
    names = {str(r.get("name", "")).lower() for r in load_shortcuts(content_root)}
    names.discard("")
    return frozenset(set(ASK_CONFIG_MENU_PATHS) | names)


def parse_ask_config_query(content_root: Path, query: str) -> tuple[str, str] | None:
    """Map *query* to ``(kind, target)`` where kind is ``menu`` or ``shortcut``.

    Args:
        content_root (Path): Workspace content root.
        query (str): User text after ``/ask-config``.

    Returns:
        tuple[str, str] | None: ``("menu", path)`` or ``("shortcut", name)`` or ``None``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> parse_ask_config_query(Path(tempfile.mkdtemp()), "voice mode")
        ('menu', 'cfg:voice')
    """
    q = query.strip().lower()
    if not q:
        return None
    token = q.split()[0]
    alias = _QUERY_ALIASES.get(token)
    if alias is not None:
        return ("menu", alias)
    vocab = build_ask_config_vocab(content_root)
    if token in vocab:
        if token.startswith("cfg:"):
            return ("menu", token)
        return ("shortcut", token)
    for entry in vocab:
        if token in entry:
            if entry.startswith("cfg:"):
                return ("menu", entry)
            return ("shortcut", entry)
    return None


def format_ask_config_reply(kind: str, target: str) -> str:
    """Format a non-mutating suggestion for the operator.

    Args:
        kind (str): ``menu`` or ``shortcut``.
        target (str): Menu path or shortcut name.

    Returns:
        str: Plain-text reply with tap hint.

    Examples:
        >>> format_ask_config_reply("menu", "cfg:voice")
        'Try /config and open Voice, or tap: cfg:voice'
        >>> format_ask_config_reply("shortcut", "standup")
        'Try /standup'
    """
    if kind == "shortcut":
        name = target.strip().lstrip("/")
        return f"Try /{name}"
    section = target.removeprefix("cfg:").replace("_", " ").title()
    return f"Try /config and open {section}, or tap: {target}"


__all__ = [
    "ASK_CONFIG_MENU_PATHS",
    "build_ask_config_vocab",
    "format_ask_config_reply",
    "parse_ask_config_query",
]
