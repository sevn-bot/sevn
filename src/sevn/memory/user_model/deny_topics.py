"""Literal-substring ``deny_topics`` matching (`specs/32-memory-honcho.md` §3.3).

Module: sevn.memory.user_model.deny_topics
Depends: (none)

Exports:
    topic_denied — return True when any pattern is a substring of ``topic``.

Examples:
    >>> from sevn.memory.user_model.deny_topics import topic_denied
    >>> topic_denied("secret_topic", ["secret"])
    True
"""

from __future__ import annotations


def topic_denied(topic: str, deny_patterns: list[str]) -> bool:
    """Return True when ``topic`` contains any non-empty deny pattern.

    Args:
        topic (str): Fact topic label.
        deny_patterns (list[str]): Literal substrings (no glob).

    Returns:
        bool: ``True`` when the topic should be suppressed.

    Examples:
        >>> topic_denied("lang_pref", ["lang"])
        True
        >>> topic_denied("lang_pref", ["*lang"])
        False
    """

    return any(pat and pat in topic for pat in deny_patterns)


__all__ = ["topic_denied"]
