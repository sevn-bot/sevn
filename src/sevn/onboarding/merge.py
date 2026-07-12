"""Deep-merge layers for onboarding draft composition (`specs/22-onboarding.md` §2.1, §4.2).

Module: sevn.onboarding.merge
Depends: (none)

Exports:
    merge_layers — deterministic deep merge of ``dict`` layers.

**List replacement (v1):** When a later layer sets a key to a ``list``, the merged
document uses that list in full for that path — later layers **replace** earlier lists
(left-to-right merge order: shipped defaults → profile fragment → ``--config`` → operator).

**``tracing.sinks`` (fragment vs operator):** Preset fragments and operator answers both
use the same rule: the winning layer's ``tracing.sinks`` array **replaces** the prior
array at that path (no element-wise merge). Opt-in append is reserved for a future
``tracing.sinks_append`` key (or ``_append`` suffix convention) — **not** implemented in v1.

**Key deletion:** Not supported in v1; keys absent from an overlay are left unchanged
from deeper layers (no tombstone convention yet).

Examples:
    >>> merge_layers({"a": 1}, {"b": 2})
    {'a': 1, 'b': 2}
    >>> merge_layers({"x": {"y": 1}}, {"x": {"z": 2}})
    {'x': {'y': 1, 'z': 2}}
    >>> merge_layers({"tracing": {"sinks": [1]}}, {"tracing": {"sinks": [2, 3]}})
    {'tracing': {'sinks': [2, 3]}}
"""

from __future__ import annotations

import copy
from typing import Any


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge ``overlay`` into a copy of ``base`` (recursive dict merge).

    Args:
        base (dict[str, Any]): Left-hand document.
        overlay (dict[str, Any]): Right-hand document; wins on conflicts.

    Returns:
        dict[str, Any]: New merged mapping.

    Examples:
        >>> _deep_merge({"a": {"b": 1}}, {"a": {"c": 2}})
        {'a': {'b': 1, 'c': 2}}
    """
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def merge_layers(base: dict[str, Any], *layers: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``dict`` layers left-to-right.

    Args:
        base (dict[str, Any]): Deepest defaults (often ``{"schema_version": 1}``).
        layers (tuple[dict[str, Any], ...]): Profile fragment, CLI ``--config``, env-derived maps, …

    Returns:
        dict[str, Any]: Merged preview suitable for ``validate_workspace_document``.

    Examples:
        >>> merge_layers({"schema_version": 1}, {"gateway": {"voice_trigger_keywords": ["hi"]}})
        {'schema_version': 1, 'gateway': {'voice_trigger_keywords': ['hi']}}
    """
    merged = copy.deepcopy(base)
    for layer in layers:
        merged = _deep_merge(merged, layer)
    return merged
