"""Trace ``attrs`` normalization (`specs/04-tracing.md` §7).

Module: sevn.agent.tracing.attrs
Depends: json, pathlib
Exports:
    json_safe_trace_value — coerce one value for JSON persistence.
    json_safe_trace_attrs — shallow attrs dict safe for trace sinks.
    trace_tool_result_value — parse tool envelope JSON when possible.
Examples:
    >>> json_safe_trace_attrs({"n": 1, "p": __import__("pathlib").Path("/x")})
    {'n': 1, 'p': '/x'}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def json_safe_trace_value(value: object) -> object:
    """Coerce one trace attribute value for JSON persistence.

    Args:
        value (object): Scalar or collection from a trace emit site.

    Returns:
        object: JSON-friendly value (non-primitives stringified).

    Examples:
        >>> json_safe_trace_value(Path("/tmp/x"))
        '/tmp/x'
        >>> json_safe_trace_value({"a": 1})["a"]
        1
    """
    if isinstance(value, dict):
        return json_safe_trace_attrs(value)
    if isinstance(value, list):
        return [json_safe_trace_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    return str(value)


def json_safe_trace_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serialisable shallow copy of trace ``attrs``.

    Args:
        attrs (dict[str, Any]): Raw attribute payload from a trace site.

    Returns:
        dict[str, Any]: Copy with ``Path`` and other non-primitives coerced.

    Examples:
        >>> json_safe_trace_attrs({"a": 1, "p": Path("/tmp/x")})
        {'a': 1, 'p': '/tmp/x'}
    """
    return {str(key): json_safe_trace_value(val) for key, val in attrs.items()}


def trace_tool_result_value(raw: str) -> object:
    """Parse a tool envelope string for trace attrs when JSON is valid.

    Args:
        raw (str): Tool return string (usually JSON envelope).

    Returns:
        object: Parsed JSON value, or ``raw`` when not valid JSON.

    Examples:
        >>> trace_tool_result_value('{"ok": true, "data": "x"}')
        {'ok': True, 'data': 'x'}
        >>> trace_tool_result_value("plain")
        'plain'
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


__all__ = ["json_safe_trace_attrs", "json_safe_trace_value", "trace_tool_result_value"]
