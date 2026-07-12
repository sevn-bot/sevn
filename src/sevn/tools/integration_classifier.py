"""Heuristics for ``integration_call`` abortability toggles (`specs/11-tools-registry.md` §8).

Classifies dotted ``service`` + ``method`` pairs using Glob-style matchers so Tier B/C plans
mirror default non-abortable surfaces for obviously mutating calls.

Module: sevn.tools.integration_classifier
Depends: fnmatch

Exports:
    is_integration_mutator — ``True`` for mutators like ``*.create*``.

Examples:
    >>> is_integration_mutator("github", "repos.create_fork")
    True
    >>> is_integration_mutator("github", "repos.get")
    False
"""

from __future__ import annotations

from fnmatch import fnmatchcase

_PATTERNS: tuple[str, ...] = (
    "*create*",
    "*update*",
    "*delete*",
    "*dispatch*",
    "*merge*",
    "*post*",
    "*send*",
)


def is_integration_mutator(service: str, method: str) -> bool:
    """Return ``True`` when pairing should prefer ``abortable=False`` defaults.

    Args:
        service (str): Dotted integration name (``github``, ``slack``, ...).
        method (str): Method identifier under the service; empty strings fall
            back to the bare service token.

    Returns:
        bool: ``True`` when the combined ``service.method`` token matches a
            mutator glob (``*create*``, ``*update*``, ``*delete*``, ...).

    Examples:
        >>> is_integration_mutator("github", "repos.create_fork")
        True
        >>> is_integration_mutator("github", "repos.get")
        False
        >>> is_integration_mutator("slack", "messages.send")
        True
    """
    combo = f"{service}.{method}" if method else service
    haystack = combo.lower()
    return any(fnmatchcase(haystack, pat.lower()) for pat in _PATTERNS)


__all__ = ["is_integration_mutator"]
