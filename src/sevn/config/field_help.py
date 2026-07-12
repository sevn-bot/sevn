"""Packaged sevn.json field help (long descriptions and collection hints).

Module: sevn.config.field_help
Depends: importlib.resources, json, pathlib

Exports:
    load_config_field_help — dotted config path → help text map.
    field_help_for — look up one path with wildcard fallbacks.
    urls_in_help_text — extract HTTP(S) URLs from help prose.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

_URL_PATTERN = re.compile(r"https?://[^\s→]+")


@lru_cache(maxsize=1)
def load_config_field_help() -> dict[str, dict[str, str]]:
    """Load wizard/CLI field help from packaged or infra JSON.

    Returns:
        dict[str, dict[str, str]]: ``field_path`` → ``long_description`` / ``how_to_collect``.

    Examples:
        >>> help_map = load_config_field_help()
        >>> isinstance(help_map, dict)
        True
    """
    raw: dict[str, Any] | None = None
    try:
        pkg = resources.files("sevn.data") / "sevn_config_long_description.json"
        if pkg.is_file():
            raw = json.loads(pkg.read_text(encoding="utf-8"))
    except (OSError, TypeError, json.JSONDecodeError):
        raw = None
    if raw is None:
        infra = Path(__file__).resolve().parents[3] / "infra" / "sevn_config_long_description.json"
        if infra.is_file():
            try:
                raw = json.loads(infra.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = None
    paths = raw.get("paths") if isinstance(raw, dict) else None
    if not isinstance(paths, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, val in paths.items():
        if not isinstance(val, dict):
            continue
        entry: dict[str, str] = {}
        for field in ("long_description", "how_to_collect"):
            text = val.get(field)
            if isinstance(text, str) and text.strip():
                entry[field] = text.strip()
        if entry:
            out[str(key)] = entry
    channels_enabled = out.get("channels.*.enabled")
    if channels_enabled:
        for ch in ("telegram", "webchat"):
            out.setdefault(f"channels.{ch}.enabled", dict(channels_enabled))
    triager_wild = out.get("providers.tier_default.*")
    if triager_wild:
        out.setdefault("providers.tier_default.triager", dict(triager_wild))
    return out


def field_help_for(path: str) -> dict[str, str] | None:
    """Return help text for one dotted config path.

    Args:
        path (str): Dotted sevn.json path (for example ``infrastructure.tunnel.local_port``).

    Returns:
        dict[str, str] | None: Help entry, or ``None`` when unknown.

    Examples:
        >>> entry = field_help_for("infrastructure.tunnel.ngrok.authtoken")
        >>> entry is None or "how_to_collect" in entry
        True
    """
    help_map = load_config_field_help()
    direct = help_map.get(path)
    if direct is not None:
        return direct
    parts = path.split(".")
    for idx in range(len(parts) - 1, 0, -1):
        wildcard = ".".join([*parts[:idx], "*", *parts[idx + 1 :]])
        entry = help_map.get(wildcard)
        if entry is not None:
            return entry
    return None


def urls_in_help_text(text: str) -> tuple[str, ...]:
    """Extract HTTP(S) URLs from help prose.

    Args:
        text (str): Help or how-to-collect string.

    Returns:
        tuple[str, ...]: De-duplicated URLs in source order.

    Examples:
        >>> urls_in_help_text("See https://example.com/a and https://example.com/a")
        ('https://example.com/a',)
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _URL_PATTERN.findall(text):
        if match not in seen:
            seen.add(match)
            ordered.append(match)
    return tuple(ordered)


__all__ = ["field_help_for", "load_config_field_help", "urls_in_help_text"]
