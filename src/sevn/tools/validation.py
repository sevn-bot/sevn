"""Minimal JSON Schema object validation for adapter-bound arguments (`specs/11-tools-registry.md` §6).

Supports the common OpenAI-style subset: ``type: object`` with ``properties`` /
``required`` and primitive property types. Enough for registry unit tests; expand when
``jsonschema`` ships as a blessed dependency.

Module: sevn.tools.validation
Depends: (none)

Exports:
    ValidationIssue — human-readable failure.
    validate_json_schema_subset — raise ``ValueError`` grouped as ``VALIDATION_ERROR``.
    coerce_string_scalars_to_schema — coerce CodeMode string kwargs to declared primitives.

Examples:
    >>> validate_json_schema_subset({"type": "object", "properties": {"a": {"type": "string"}}}, {"a": "x"})
    >>> import pytest
    >>> with pytest.raises(ValueError, match="VALIDATION_ERROR"):
    ...     validate_json_schema_subset({"type": "object", "required": ["a"], "properties": {}}, {})
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from sevn.tools.codes import ToolResultCode

_BOOL_TRUE_STRINGS: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE_STRINGS: Final[frozenset[str]] = frozenset({"false", "0", "no", "off", ""})

_UNCHANGED: Final[object] = object()


@dataclass(frozen=True)
class ValidationIssue:
    """One failed constraint from the lightweight validator."""

    message: str


def _coerce_scalar(value: str, expect: Any) -> Any:
    """Coerce a single CodeMode string ``value`` to the primitive ``expect`` declares.

    Args:
        value (str): Raw string argument the sandbox passed for a typed param.
        expect (Any): The property's declared ``type`` (only single primitive strings act).

    Returns:
        Any: The coerced value, or the ``_UNCHANGED`` sentinel when no safe coercion applies
            (the caller then leaves the value as-is so the validator raises VALIDATION_ERROR).

    Examples:
        >>> _coerce_scalar("100", "integer")
        100
        >>> _coerce_scalar("false", "boolean")
        False
        >>> _coerce_scalar('["a", "b"]', "array")
        ['a', 'b']
        >>> _coerce_scalar("abc", "integer") is _UNCHANGED
        True
    """
    text = value.strip()
    if expect == "integer":
        return int(text) if text.lstrip("+-").isdigit() else _UNCHANGED
    if expect == "number":
        try:
            return float(text)
        except ValueError:
            return _UNCHANGED
    if expect == "boolean":
        low = text.lower()
        if low in _BOOL_TRUE_STRINGS:
            return True
        if low in _BOOL_FALSE_STRINGS:
            return False
        return _UNCHANGED
    if expect == "array" and text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            return _UNCHANGED
        return parsed if isinstance(parsed, list) else _UNCHANGED
    if expect == "object" and text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return _UNCHANGED
        return parsed if isinstance(parsed, dict) else _UNCHANGED
    return _UNCHANGED


def coerce_string_scalars_to_schema(schema: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Best-effort coerce string-valued args to the single primitive type the schema declares.

    Tier-B models under CodeMode (``run_code``) re-enter ``ToolExecutor.dispatch`` with the
    kwargs exactly as written in the sandbox — typed values arrive as strings (``lines='100'``,
    ``summarize='false'``, ``argv='["x"]'``). The shared validator rejects string-for-integer
    (etc.) before the tool runs, so the call errors and is silently dropped in the sandbox,
    burning the ``run_code`` retry budget. Coerce those strings up front so every CodeMode-bound
    tool runs instead of vanishing. Only single-type primitive schemas are touched; list-typed
    (e.g. ``["integer", "string"]``) and already-correct values pass through untouched, and
    un-coercible strings are left as-is so :func:`validate_json_schema_subset` still raises the
    proper VALIDATION_ERROR. Native pydantic-ai calls already arrive typed, so this is a no-op
    for them.

    Args:
        schema (dict[str, Any]): Tool parameter schema (``parameters`` field).
        data (dict[str, Any]): Parsed tool arguments from the LLM / sandbox.

    Returns:
        dict[str, Any]: ``data`` with coercible string scalars converted (a copy when changed).

    Examples:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {"lines": {"type": "integer"}, "summarize": {"type": "boolean"}},
        ... }
        >>> coerce_string_scalars_to_schema(schema, {"lines": "100", "summarize": "false"})
        {'lines': 100, 'summarize': False}
        >>> coerce_string_scalars_to_schema(schema, {"lines": "abc"})
        {'lines': 'abc'}
        >>> coerce_string_scalars_to_schema({"type": "object"}, {"x": "1"})
        {'x': '1'}
    """
    if schema.get("type") != "object":
        return data
    props = schema.get("properties")
    if not isinstance(props, dict):
        return data
    coerced = dict(data)
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        sub = props.get(key)
        if not isinstance(sub, dict):
            continue
        new = _coerce_scalar(value, sub.get("type"))
        if new is not _UNCHANGED:
            coerced[key] = new
    return coerced


def validate_json_schema_subset(schema: dict[str, Any], data: dict[str, Any]) -> None:
    """Validate ``data`` against a shallow JSON Schema fragment.

    Args:
        schema (dict[str, Any]): Tool parameter schema (``parameters`` field).
        data (dict[str, Any]): Parsed tool arguments from the LLM / adapter.

    Returns:
        None: When validation passes.

    Raises:
        ValueError: When validation fails; prefix ``str(ToolResultCode.VALIDATION_ERROR)``.

    Examples:
        >>> validate_json_schema_subset(
        ...     {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
        ...     {"name": "load_tool"},
        ... )
    """
    if schema.get("type") != "object":
        msg = f"{ToolResultCode.VALIDATION_ERROR}: root schema must declare type object"
        raise ValueError(msg)
    required = list(schema.get("required", []))
    props: dict[str, Any] = schema.get("properties", {})
    for key in required:
        if key not in data:
            msg = f"{ToolResultCode.VALIDATION_ERROR}: missing required field {key!r}"
            raise ValueError(msg)
    for key, raw in data.items():
        if key not in props:
            continue
        _check_type(key, raw, props[key])


def _check_type(key: str, value: Any, subschema: Any) -> None:
    """Ensure ``value`` matches primitive ``subschema``.

    Args:
        key (str): Property name (used only for error messages).
        value (Any): Concrete argument value to validate.
        subschema (Any): JSON Schema fragment for the property; ``dict``-typed
            schemas with a ``type`` key are checked, anything else is ignored.

    Raises:
        ValueError: When ``value`` does not match the declared primitive type;
            the message is prefixed with ``str(ToolResultCode.VALIDATION_ERROR)``.

    Examples:
        >>> _check_type("k", "x", {"type": "string"}) is None
        True
        >>> import pytest
        >>> with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        ...     _check_type("k", 1, {"type": "string"})
    """
    if not isinstance(subschema, dict):
        return
    expect = subschema.get("type")
    if expect == "string" and not isinstance(value, str):
        msg = f"{ToolResultCode.VALIDATION_ERROR}: field {key!r} expects string"
        raise ValueError(msg)
    if expect == "integer" and not isinstance(value, int):
        msg = f"{ToolResultCode.VALIDATION_ERROR}: field {key!r} expects integer"
        raise ValueError(msg)
    if expect == "number" and not isinstance(value, (int, float)):
        msg = f"{ToolResultCode.VALIDATION_ERROR}: field {key!r} expects number"
        raise ValueError(msg)
    if expect == "boolean" and not isinstance(value, bool):
        msg = f"{ToolResultCode.VALIDATION_ERROR}: field {key!r} expects boolean"
        raise ValueError(msg)
    if expect == "object" and value is not None and not isinstance(value, dict):
        msg = f"{ToolResultCode.VALIDATION_ERROR}: field {key!r} expects object"
        raise ValueError(msg)
    if expect == "array" and not isinstance(value, list):
        msg = f"{ToolResultCode.VALIDATION_ERROR}: field {key!r} expects array"
        raise ValueError(msg)


__all__ = [
    "ValidationIssue",
    "coerce_string_scalars_to_schema",
    "validate_json_schema_subset",
]
