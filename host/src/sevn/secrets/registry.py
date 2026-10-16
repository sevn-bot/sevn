"""Thread-safe map from secret values to redaction names."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_by_value: dict[str, str] = {}


def register(name: str, value: str) -> None:
    if not value:
        return
    with _lock:
        _by_value[value] = name


def registered_secrets() -> tuple[tuple[str, str], ...]:
    """Return ``(value, name)`` pairs, longest value first."""
    with _lock:
        pairs = tuple(_by_value.items())
    return tuple(sorted(pairs, key=lambda item: len(item[0]), reverse=True))
