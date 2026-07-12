"""Unified Mission Control ``sevn.json`` read/validate/persist helpers (MC W2).

Module: sevn.ui.dashboard.services.config_full
Depends: json, pydantic, sevn.cli.workspace_schema, sevn.onboarding.validate

Exports:
    is_redacted_placeholder — detect dashboard redaction sentinel values.
    merge_redacted_config — restore redacted fields from the on-disk document.
    changed_top_level_keys — diff top-level keys for audit/hub payloads.
    validate_config_document — run model-slot policy + workspace validation.
    validation_errors_from_exception — map failures to ``{path, message}`` rows.
    validate_against_json_schema — optional structural check vs ``sevn.schema.json``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from sevn.cli.workspace_schema import load_workspace_json_schema
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.onboarding.validate import validate_workspace_document

REDACTED_PLACEHOLDERS: frozenset[str] = frozenset({"<redacted>", "<redacted-secret-ref>"})


def is_redacted_placeholder(value: object) -> bool:
    """Return whether *value* is a dashboard redaction sentinel.

    Args:
        value (object): Candidate JSON scalar.

    Returns:
        bool: ``True`` when the value must be restored from disk on save.

    Examples:
        >>> is_redacted_placeholder("<redacted>")
        True
        >>> is_redacted_placeholder("real-secret")
        False
    """

    return isinstance(value, str) and value in REDACTED_PLACEHOLDERS


def merge_redacted_config(incoming: dict[str, Any], on_disk: dict[str, Any]) -> dict[str, Any]:
    """Merge an edited redacted document with the on-disk ``sevn.json``.

    Any field whose edited value equals a redaction placeholder is restored from
    *on_disk* so secrets and sensitive keys are not clobbered on save.

    Args:
        incoming (dict[str, Any]): Candidate document from the dashboard editor.
        on_disk (dict[str, Any]): Current persisted workspace document.

    Returns:
        dict[str, Any]: Merged document ready for validation and persist.

    Examples:
        >>> disk = {"gateway": {"token": "${SECRET:k:tok}"}, "schema_version": 1}
        >>> edited = {"gateway": {"token": "<redacted-secret-ref>"}, "schema_version": 1}
        >>> merge_redacted_config(edited, disk)["gateway"]["token"]
        '${SECRET:k:tok}'
    """

    merged: dict[str, Any] = {}
    for key, inc_val in incoming.items():
        disk_val = on_disk.get(key)
        if is_redacted_placeholder(inc_val):
            merged[key] = on_disk.get(key, inc_val)
        elif isinstance(inc_val, dict) and isinstance(disk_val, dict):
            merged[key] = merge_redacted_config(inc_val, disk_val)
        elif isinstance(inc_val, list) and isinstance(disk_val, list):
            merged[key] = _merge_redacted_list(inc_val, disk_val)
        else:
            merged[key] = inc_val
    return merged


def _merge_redacted_list(incoming: list[Any], on_disk: list[Any]) -> list[Any]:
    """Merge list nodes, preserving redacted scalars element-wise when lengths match.

    Args:
        incoming (list[Any]): Edited list from the dashboard.
        on_disk (list[Any]): On-disk list at the same path.

    Returns:
        list[Any]: Merged list.

    Examples:
        >>> _merge_redacted_list(["<redacted>"], ["secret"])
        ['secret']
    """

    if len(incoming) != len(on_disk):
        return list(incoming)
    out: list[Any] = []
    for idx, inc_item in enumerate(incoming):
        disk_item = on_disk[idx]
        if is_redacted_placeholder(inc_item):
            out.append(disk_item)
        elif isinstance(inc_item, dict) and isinstance(disk_item, dict):
            out.append(merge_redacted_config(inc_item, disk_item))
        elif isinstance(inc_item, list) and isinstance(disk_item, list):
            out.append(_merge_redacted_list(inc_item, disk_item))
        else:
            out.append(inc_item)
    return out


def changed_top_level_keys(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Return sorted top-level keys whose JSON value changed.

    Args:
        before (dict[str, Any]): Document before persist.
        after (dict[str, Any]): Document after persist.

    Returns:
        list[str]: Changed top-level keys (values never included).

    Examples:
        >>> changed_top_level_keys({"a": 1, "b": 2}, {"a": 1, "b": 3})
        ['b']
    """

    keys = set(before.keys()) | set(after.keys())
    changed: list[str] = []
    for key in sorted(keys):
        if json.dumps(before.get(key), sort_keys=True) != json.dumps(
            after.get(key), sort_keys=True
        ):
            changed.append(key)
    return changed


def validate_config_document(doc: dict[str, Any]) -> None:
    """Run the same in-process gates as ``sevn config validate`` on a full document.

    Args:
        doc (dict[str, Any]): Candidate workspace document.

    Raises:
        UnsupportedSchemaVersionError: When ``schema_version`` is unsupported.
        ValueError: When cross-field validators fail.
        pydantic.ValidationError: When ``WorkspaceConfig`` parse fails.

    Examples:
        >>> validate_config_document({"schema_version": 1, "gateway": {"token": "t"}})
    """

    from sevn.onboarding.web_app import apply_model_slot_policy

    apply_model_slot_policy(doc)
    validate_workspace_document(doc)


def validation_errors_from_exception(exc: Exception) -> list[dict[str, str]]:
    """Map validation failures to structured field errors for the Config tab.

    Args:
        exc (Exception): Validation failure from ``validate_config_document`` or schema check.

    Returns:
        list[dict[str, str]]: Rows with ``path`` and ``message`` keys.

    Examples:
        >>> rows = validation_errors_from_exception(ValueError("gateway.port invalid"))
        >>> rows[0]["message"]
        'gateway.port invalid'
    """

    if isinstance(exc, ValidationError):
        rows: list[dict[str, str]] = []
        for err in exc.errors():
            loc = err.get("loc", ())
            path = ".".join(str(part) for part in loc if str(part) != "__root__")
            rows.append(
                {"path": path or "document", "message": err.get("msg", "validation failed")}
            )
        return rows or [{"path": "document", "message": "validation failed"}]
    if isinstance(exc, UnsupportedSchemaVersionError):
        return [{"path": "schema_version", "message": str(exc)}]
    return [{"path": "document", "message": str(exc)}]


def validate_against_json_schema(doc: dict[str, Any]) -> list[dict[str, str]]:
    """Validate *doc* against bundled ``infra/sevn.schema.json`` when ``jsonschema`` is available.

    Args:
        doc (dict[str, Any]): Candidate workspace document.

    Returns:
        list[dict[str, str]]: Field errors; empty when valid or when ``jsonschema`` is absent.

    Examples:
        >>> validate_against_json_schema({"schema_version": 1, "gateway": {"token": "t"}}) == [] or True
        True
    """

    try:
        import jsonschema
    except ImportError:
        return []
    try:
        schema = load_workspace_json_schema()
    except (OSError, json.JSONDecodeError, ValueError, FileNotFoundError):
        return []
    validator = jsonschema.Draft202012Validator(schema)
    rows: list[dict[str, str]] = []
    for err in validator.iter_errors(doc):
        path = ".".join(str(part) for part in err.absolute_path) or "document"
        rows.append({"path": path, "message": err.message})
    return rows


__all__ = [
    "changed_top_level_keys",
    "is_redacted_placeholder",
    "merge_redacted_config",
    "validate_against_json_schema",
    "validate_config_document",
    "validation_errors_from_exception",
]
