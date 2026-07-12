"""Session scope + quarantine filters (`specs/31-memory-dreaming.md` §5, §8).

Module: sevn.memory.dreaming.filters
Depends: json, re

Exports:
    session_allows_dreaming — DM-owner scope heuristic.
    content_has_llmignore_provenance — drop candidates touching quarantine paths.
    lcm_channel_allows_dreaming — exclude group-like LCM channels.
"""

from __future__ import annotations

import json
import re
from re import Pattern

_LLMIGNORE_PATH: Pattern[str] = re.compile(r"(?i)\.llmignore(?:[\\/]|$)")


def session_allows_dreaming(session_id: str, metadata: str | None) -> bool:
    """Return False for obvious group / multi-user keys (DM-only v1).

    Args:
        session_id (str): Short-term memory ``session_id`` or LCM ``session_key``-like id.
        metadata (str | None): Optional JSON metadata blob from ``memory.metadata``.

    Returns:
        bool: True when the row is treated as DM-owner scope for Dreaming v1.

    Examples:
        >>> session_allows_dreaming("dm:owner", None)
        True
        >>> session_allows_dreaming("grp:room", None)
        False
    """
    sid = session_id.strip().lower()
    if sid.startswith(("grp:", "group:")) or ":group:" in sid:
        return False
    if "group" in sid and sid.count(":") >= 2:
        return False
    if metadata:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            return True
        if not isinstance(meta, dict):
            return True
        scope = meta.get("scope")
        if scope in ("group", "supergroup", "channel"):
            return False
        ch = meta.get("channel")
        if isinstance(ch, str) and ch.lower() in ("group", "supergroup", "channel"):
            return False
    return True


def content_has_llmignore_provenance(content: str, metadata: str | None) -> bool:
    """Return True when provenance references quarantined paths (candidate must drop).

    Args:
        content (str): Candidate text.
        metadata (str | None): Optional JSON metadata.

    Returns:
        bool: True when ``.llmignore`` appears in payload strings.

    Examples:
        >>> content_has_llmignore_provenance("safe", None)
        False
        >>> content_has_llmignore_provenance('see workspace/.llmignore/x', None)
        True
    """
    if _LLMIGNORE_PATH.search(content):
        return True
    if metadata and _LLMIGNORE_PATH.search(metadata):
        return True
    if metadata:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError:
            return False
        if isinstance(meta, dict):
            for val in meta.values():
                if isinstance(val, str) and _LLMIGNORE_PATH.search(val):
                    return True
    return False


def lcm_channel_allows_dreaming(channel: str | None) -> bool:
    """Return False for group-like LCM channels.

    Args:
        channel (str | None): ``lcm_conversations.channel``.

    Returns:
        bool: True when summaries from this conversation may feed Dreaming.

    Examples:
        >>> lcm_channel_allows_dreaming("private")
        True
        >>> lcm_channel_allows_dreaming("supergroup")
        False
    """
    if channel is None:
        return True
    ch = channel.strip().lower()
    return ch not in ("group", "supergroup", "channel", "guild")
