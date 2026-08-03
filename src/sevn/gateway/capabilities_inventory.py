"""Machine-readable channel capability inventory (#151).

Module: sevn.gateway.capabilities_inventory
Depends: importlib.metadata, sevn.channels.stub

Exports:
    build_channel_capabilities_inventory — ``implemented`` / ``stub`` / ``unavailable`` rows.
"""

from __future__ import annotations

import importlib.metadata
import time
from typing import Any, Literal

from sevn.channels.stub import StubChannelAdapter

ChannelStatus = Literal["implemented", "stub", "unavailable"]

_BUILTIN_IMPLEMENTED: tuple[tuple[str, str], ...] = (
    ("telegram", "Telegram"),
    ("webchat", "WebChat"),
)


def _classify_entry(ep: importlib.metadata.EntryPoint) -> tuple[ChannelStatus, str]:
    """Load one ``sevn.channels`` entry point and classify adapter maturity.

    Args:
        ep (importlib.metadata.EntryPoint): Distribution entry point.

    Returns:
        tuple[ChannelStatus, str]: Status flag and human label.

    Examples:
        >>> from importlib.metadata import entry_points
        >>> eps = entry_points().select(group="sevn.channels")
        >>> ep = next(e for e in eps if e.name == "signal")
        >>> status, _ = _classify_entry(ep)
        >>> status
        'stub'
    """
    name = ep.name
    try:
        loaded = ep.load()
    except Exception:
        return "unavailable", name.replace("_", " ").title()
    if not isinstance(loaded, type):
        return "unavailable", name.replace("_", " ").title()
    label = str(getattr(loaded, "display_label", None) or name.replace("_", " ").title())
    module = str(getattr(loaded, "__module__", ""))
    if issubclass(loaded, StubChannelAdapter) or module.startswith("sevn.channels.tier_stubs"):
        return "stub", label
    return "implemented", label


def build_channel_capabilities_inventory() -> dict[str, Any]:
    """Return channel rows for ``GET /capabilities`` and ``sevn capabilities``.

    Returns:
        dict[str, Any]: ``channels`` list plus ``generated_at`` epoch seconds.

    Examples:
        >>> body = build_channel_capabilities_inventory()
        >>> any(row["name"] == "telegram" and row["status"] == "implemented" for row in body["channels"])
        True
        >>> any(row["name"] == "signal" and row["status"] == "stub" for row in body["channels"])
        True
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, label in _BUILTIN_IMPLEMENTED:
        seen.add(name)
        rows.append(
            {
                "name": name,
                "label": label,
                "status": "implemented",
                "source": "builtin",
            },
        )

    eps = importlib.metadata.entry_points().select(group="sevn.channels")
    for ep in sorted(eps, key=lambda item: item.name):
        if ep.name in seen:
            continue
        seen.add(ep.name)
        status, label = _classify_entry(ep)
        rows.append(
            {
                "name": ep.name,
                "label": label,
                "status": status,
                "source": "entry_point",
            },
        )

    rows.sort(key=lambda row: str(row["name"]))
    return {"channels": rows, "generated_at": int(time.time())}


__all__ = ["ChannelStatus", "build_channel_capabilities_inventory"]
