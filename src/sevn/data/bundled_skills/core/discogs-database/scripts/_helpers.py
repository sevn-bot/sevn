"""Shared serialization and CLI helpers for discogs-database scripts."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from _discogs_common import build_client, emit_json, map_discogs_error, write_err


def serialize_object(obj: object) -> dict[str, Any]:
    """Serialize a Discogs model or mapping to a JSON-safe dict."""
    if isinstance(obj, dict):
        return {str(key): _json_value(value) for key, value in obj.items()}
    data: dict[str, Any] = {}
    for key in (
        "id",
        "name",
        "title",
        "username",
        "uri",
        "resource_url",
        "num_for_sale",
        "lowest_price",
        "blocked_from_sale",
    ):
        if not hasattr(obj, key):
            continue
        value = getattr(obj, key)
        if value is None or callable(value):
            continue
        data[key] = _json_value(value)
    return data


def _json_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    for attr in ("value", "currency", "amount"):
        if hasattr(value, attr) and not callable(getattr(value, attr)):
            nested = getattr(value, attr)
            if isinstance(nested, (str, int, float, bool)):
                return nested
    text = str(value)
    return text if text and not text.startswith("<") else repr(value)


def run_script(
    parser: argparse.ArgumentParser,
    argv: list[str] | None,
    worker: Callable[[argparse.Namespace, Any], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    """Parse argv, build client, run worker, map errors to envelopes."""
    args = parser.parse_args(argv)
    client = build_client()
    if isinstance(client, dict):
        return 1, client
    try:
        return worker(args, client)
    except Exception as exc:  # noqa: BLE001 — mapped to stable envelope codes
        mapped = map_discogs_error(exc)
        return 1, write_err(code=mapped["code"], message=mapped["message"])


def finish(code: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Emit JSON envelope and return exit metadata for tests."""
    emit_json(payload)
    return code, payload
