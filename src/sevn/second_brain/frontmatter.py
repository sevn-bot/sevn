"""YAML frontmatter parse/merge for wiki pages (`specs/27-second-brain.md` §3.3).

Module: sevn.second_brain.frontmatter
Depends: re, yaml

Exports:
    split_frontmatter — body + raw YAML text + unknown round-trip.
    dumps_frontmatter — serialise mapping back to YAML block.
    normalise_agent_keys — normalise ``sevn_*`` aliases on a frontmatter dict.
    compose_page — build full markdown with ``---`` fenced YAML.
    okf_type_required — whether an OKF page requires a ``type`` frontmatter key.
    missing_okf_type — whether frontmatter is missing required ``type``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

OKF_RESERVED_BASENAMES = frozenset({"index.md", "log.md"})

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL | re.MULTILINE,
)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """Split file into frontmatter dict, body, and raw YAML string (if present).

    Unknown keys remain in the returned dict. When no frontmatter, returns ``({}, text, None)``.

    Args:
        text (str): Full markdown file contents.

    Returns:
        tuple[dict[str, Any], str, str | None]: Parsed mapping, body text, raw YAML or ``None``.

    Examples:
        >>> split_frontmatter("# hi\\n")[0]
        {}
    """

    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text, None
    raw_yaml = m.group(1)
    body = m.group(2)
    try:
        loaded = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        return {}, text, raw_yaml
    if not isinstance(loaded, dict):
        return {}, text, raw_yaml
    data: dict[str, Any] = dict(loaded)
    return data, body, raw_yaml


def dumps_frontmatter(fm: dict[str, Any]) -> str:
    """Serialise frontmatter to a YAML block (no outer document markers).

    Args:
        fm (dict[str, Any]): Frontmatter keys and values.

    Returns:
        str: YAML text suitable for fencing inside ``---``.

    Examples:
        >>> dumps_frontmatter({"title": "T"}).strip().startswith("title:")
        True
    """

    return (
        yaml.safe_dump(
            fm,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        + "\n"
    )


def normalise_agent_keys(fm: dict[str, Any]) -> dict[str, Any]:
    """Copy ``source``→``sevn_source``, etc., then prefer ``sevn_*`` when both exist.

    Args:
        fm (dict[str, Any]): Incoming frontmatter mapping.

    Returns:
        dict[str, Any]: New dict with canonical ``sevn_*`` keys preferred.

    Examples:
        >>> normalise_agent_keys({"source": "x"})["sevn_source"]
        'x'
    """

    out = dict(fm)
    aliases = (
        ("source", "sevn_source"),
        ("evidence", "sevn_evidence"),
        ("freshness", "sevn_freshness"),
        ("contradictions", "sevn_contradictions"),
    )
    for short, long in aliases:
        if long in out and short in out:
            del out[short]
            continue
        if short in out and long not in out:
            out[long] = out.pop(short)
    return out


def okf_type_required(rel_path: str) -> bool:
    """Return whether OKF expects a non-empty ``type`` field on ``rel_path``.

    Reserved files ``index.md`` and ``log.md`` are exempt at any directory depth.

    Args:
        rel_path (str): Wiki-relative path (POSIX).

    Returns:
        bool: ``True`` when ``type`` should be present.

    Examples:
        >>> okf_type_required("ingests/note.md")
        True
        >>> okf_type_required("subdir/index.md")
        False
    """
    return Path(rel_path).name not in OKF_RESERVED_BASENAMES


def missing_okf_type(fm: dict[str, Any]) -> bool:
    """Return whether frontmatter lacks a non-empty OKF ``type`` value.

    Args:
        fm (dict[str, Any]): Parsed frontmatter mapping.

    Returns:
        bool: ``True`` when ``type`` is absent or blank.

    Examples:
        >>> missing_okf_type({"type": "Note"})
        False
        >>> missing_okf_type({"title": "x"})
        True
    """
    type_val = fm.get("type")
    return not isinstance(type_val, str) or not type_val.strip()


def compose_page(fm: dict[str, Any], body: str) -> str:
    """Build full markdown with ``---`` fenced YAML.

    Args:
        fm (dict[str, Any]): Frontmatter mapping to serialise.
        body (str): Markdown body after the closing fence.

    Returns:
        str: Full page text with YAML frontmatter block.

    Examples:
        >>> compose_page({"title": "T"}, "# b\\n").startswith("---\\n")
        True
    """

    block = dumps_frontmatter(fm)
    return f"---\n{block}---\n{body.lstrip('\n')}"


__all__ = [
    "OKF_RESERVED_BASENAMES",
    "compose_page",
    "dumps_frontmatter",
    "missing_okf_type",
    "normalise_agent_keys",
    "okf_type_required",
    "split_frontmatter",
]
