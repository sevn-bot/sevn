"""Per-session lazy payload cache keyed by registry generation (`specs/11-tools-registry.md` §3.2).

Uses a bounded ``OrderedDict`` eviction policy (FIFO) with configurable capacity.

Module: sevn.tools.cache
Depends: sevn.config.defaults

Exports:
    LoadedBodyCache — LRU-ish store for serialized ``load_tool`` / ``load_skill`` payloads.

Examples:
    >>> c = LoadedBodyCache(capacity=1)
    >>> c.set("tool", "x", 1, "{}")
    >>> c.get("tool", "x", 1)
    '{}'
"""

from __future__ import annotations

from collections import OrderedDict

from sevn.config.defaults import LOADED_BODY_CACHE_DEFAULT_CAP


class LoadedBodyCache:
    """Remember ``entry_kind/name/registry_version → JSON string`` for hot turns."""

    def __init__(self, *, capacity: int = LOADED_BODY_CACHE_DEFAULT_CAP) -> None:
        """Create cache with LRU capacity defaulting from ``defaults.py``.

                Args:
        capacity (int): Combined entry cap for **tool + skill** keys.

                Returns:
                    None

                Raises:
                    (none)

                Examples:
                    >>> LoadedBodyCache(capacity=2)._capacity == 2
                    True
        """

        self._capacity = capacity
        self._entries: OrderedDict[tuple[str, str, int], str] = OrderedDict()

    def get(self, entry_kind: str, name: str, registry_version: int) -> str | None:
        """Return cached JSON string, refreshing LRU recency.

        Args:
            entry_kind (str): Namespace discriminator (``"tool"`` / ``"skill"``).
            name (str): Tool or skill canonical name.
            registry_version (int): Registry bump from workspace/session scope.

        Returns:
            str | None: Cached payload, or ``None`` on miss.

        Examples:
            >>> c = LoadedBodyCache(capacity=2)
            >>> c.get("tool", "missing", 1) is None
            True
            >>> c.set("tool", "x", 1, "{}")
            >>> c.get("tool", "x", 1)
            '{}'
        """
        key = (entry_kind, name, registry_version)
        val = self._entries.get(key)
        if val is not None:
            self._entries.move_to_end(key)
        return val

    def set(self, entry_kind: str, name: str, registry_version: int, payload: str) -> None:
        """Insert/replace cached JSON string enforcing ``capacity``.

        Args:
            entry_kind (str): Namespace discriminator.
            name (str): Tool or skill canonical name.
            registry_version (int): Registry bump from workspace/session scope.
            payload (str): Serialized JSON (**UTF-8** string).

        Returns:
            None

        Examples:
                    >>> c = LoadedBodyCache(capacity=2)
                    >>> c.set("tool", "x", 1, "same")
                    >>> c.get("tool", "x", 1)
                    'same'
        """

        key = (entry_kind, name, registry_version)
        self._entries.pop(key, None)
        self._entries[key] = payload
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Remove every cached payload (call after ``registry_version`` bumps).

        Args:
            (none)

        Returns:
            None

        Examples:
            >>> c = LoadedBodyCache(capacity=2)
            >>> c.set("tool", "a", 1, "{}")
            >>> c.clear()
            >>> c.get("tool", "a", 1) is None
            True
        """

        self._entries.clear()


__all__ = ["LoadedBodyCache"]
