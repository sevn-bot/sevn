"""YAML frontmatter parse/merge for wiki pages (`specs/27-second-brain.md` §3.3).

Module: sevn.second_brain.frontmatter
Depends: re, yaml, sevn.second_brain.paths

Exports:
    split_frontmatter — body + raw YAML text + unknown round-trip.
    dumps_frontmatter — serialise mapping back to YAML block.
    normalise_agent_keys — normalise agent/Obsidian aliases on a frontmatter dict.
    compose_page — build full markdown with ``---`` fenced YAML.
    okf_type_required — whether an OKF page requires a ``type`` frontmatter key.
    missing_okf_type — whether frontmatter is missing required ``type``.
    reserved_basenames_for_layout — index/log basenames for the active vault layout.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import yaml

if TYPE_CHECKING:
    from sevn.second_brain.paths import VaultLayout

OKF_RESERVED_BASENAMES = frozenset({"index.md", "log.md"})

PARA_FRONTMATTER_KEYS: frozenset[str] = frozenset(
    {
        "tags",
        "aliases",
        "created",
        "updated",
        "source",
        "source_hash",
        "captured",
    },
)

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


def _normalise_legacy_agent_keys(fm: dict[str, Any]) -> dict[str, Any]:
    """Map short provenance keys to canonical ``sevn_*`` names (legacy OKF layout).

    Args:
        fm (dict[str, Any]): Incoming frontmatter mapping.

    Returns:
        dict[str, Any]: New dict with canonical ``sevn_*`` keys preferred.

    Examples:
        >>> _normalise_legacy_agent_keys({"source": "x"})["sevn_source"]
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


def _normalise_para_agent_keys(fm: dict[str, Any]) -> dict[str, Any]:
    """Keep Obsidian-native PARA keys; accept ``sevn_*`` aliases for interop.

    Args:
        fm (dict[str, Any]): Incoming frontmatter mapping.

    Returns:
        dict[str, Any]: New dict with native PARA keys preferred over ``sevn_*``.

    Examples:
        >>> _normalise_para_agent_keys({"sevn_source": "x"})["source"]
        'x'
    """
    out = dict(fm)
    interop = (
        ("sevn_source", "source"),
        ("sevn_evidence", "evidence"),
        ("sevn_freshness", "freshness"),
        ("sevn_contradictions", "contradictions"),
    )
    for sevn_key, native_key in interop:
        if sevn_key in out and native_key in out:
            del out[sevn_key]
            continue
        if sevn_key in out and native_key not in out:
            out[native_key] = out.pop(sevn_key)
    return out


def normalise_agent_keys(
    fm: dict[str, Any],
    *,
    layout: Literal["legacy", "para"] = "legacy",
) -> dict[str, Any]:
    """Normalise agent/Obsidian aliases on a frontmatter dict.

    Legacy layout maps ``source``→``sevn_source`` (OKF provenance). PARA layout keeps
    Obsidian-native keys and accepts ``sevn_*`` aliases for interop.

    Args:
        fm (dict[str, Any]): Incoming frontmatter mapping.
        layout (Literal["legacy", "para"]): Active vault layout for alias rules.

    Returns:
        dict[str, Any]: New dict with canonical keys for the active layout.

    Examples:
        >>> normalise_agent_keys({"source": "x"})["sevn_source"]
        'x'
        >>> normalise_agent_keys({"sevn_source": "x"}, layout="para")["source"]
        'x'
    """

    if layout == "para":
        return _normalise_para_agent_keys(fm)
    return _normalise_legacy_agent_keys(fm)


def reserved_basenames_for_layout(layout: VaultLayout) -> frozenset[str]:
    """Return reserved note basenames for the active layout (index/log home notes).

    Args:
        layout (VaultLayout): Active vault layout resolver.

    Returns:
        frozenset[str]: Basenames exempt from mandatory ``type`` and orphan lint.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> from sevn.second_brain.paths import VaultLayout
        >>> ws = Path(tempfile.mkdtemp())
        >>> legacy = VaultLayout(ws, SecondBrainWorkspaceConfig(), "owner")
        >>> "index.md" in reserved_basenames_for_layout(legacy)
        True
    """
    return frozenset({layout.index_note().name, layout.log_note().name})


def okf_type_required(
    rel_path: str,
    *,
    reserved_basenames: frozenset[str] | None = None,
) -> bool:
    """Return whether OKF expects a non-empty ``type`` field on ``rel_path``.

    Reserved files (index/log home notes) are exempt at any directory depth.

    Args:
        rel_path (str): Wiki-relative path (POSIX).
        reserved_basenames (frozenset[str] | None): Override reserved basenames; defaults
            to :data:`OKF_RESERVED_BASENAMES`.

    Returns:
        bool: ``True`` when ``type`` should be present.

    Examples:
        >>> okf_type_required("ingests/note.md")
        True
        >>> okf_type_required("subdir/index.md")
        False
    """
    basenames = OKF_RESERVED_BASENAMES if reserved_basenames is None else reserved_basenames
    return Path(rel_path).name not in basenames


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
    "PARA_FRONTMATTER_KEYS",
    "compose_page",
    "dumps_frontmatter",
    "missing_okf_type",
    "normalise_agent_keys",
    "okf_type_required",
    "reserved_basenames_for_layout",
    "split_frontmatter",
]
