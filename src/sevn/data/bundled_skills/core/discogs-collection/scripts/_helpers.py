"""Shared serialization and CLI helpers for discogs-collection scripts."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from _discogs_common import build_client, emit_json, map_discogs_error, require_confirm, write_err


def serialize_object(obj: object) -> dict[str, Any]:
    """Serialize a Discogs model or mapping to a JSON-safe dict."""
    if isinstance(obj, dict):
        return {str(key): _json_value(value) for key, value in obj.items()}
    data: dict[str, Any] = {}
    for key in (
        "id",
        "instance_id",
        "name",
        "title",
        "username",
        "uri",
        "resource_url",
        "count",
        "folder_id",
        "rating",
        "notes",
        "date_added",
        "minimum",
        "median",
        "maximum",
    ):
        if not hasattr(obj, key):
            continue
        value = getattr(obj, key)
        if value is None or callable(value):
            continue
        data[key] = _json_value(value)
    release = getattr(obj, "release", None)
    if release is not None and not callable(release):
        data["release"] = serialize_object(release)
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


def get_collection_folders(user: Any) -> list[Any]:
    """Return collection folders from a User (method or test list)."""
    folders_ref = user.collection_folders
    return folders_ref() if callable(folders_ref) else list(folders_ref)


def get_collection_folder(user: Any, folder_id: int) -> Any:
    """Resolve one collection folder by id."""
    folder_ref = getattr(user, "collection_folder", None)
    if callable(folder_ref):
        return folder_ref(folder_id)
    for folder in get_collection_folders(user):
        if folder.id == folder_id:
            return folder
    raise ValueError(f"collection folder {folder_id} not found")


def collection_instance(client: Any, *, instance_id: int, release_id: int | None = None) -> Any:
    """Build a collection instance stub for write operations."""
    import sys
    import types

    payload: dict[str, Any] = {
        "instance_id": instance_id,
        "id": release_id if release_id is not None else 0,
    }
    module = sys.modules.get("discogs_client")
    if isinstance(module, types.ModuleType) and hasattr(module, "models"):
        from discogs_client.models import CollectionItemInstance

        return CollectionItemInstance(client, payload)

    class _Stub:
        def __init__(self) -> None:
            self.instance_id = instance_id
            self.id = payload["id"]
            self.rating: int | None = None
            self.notes: str | None = None

        def save(self) -> None:
            return None

    return _Stub()


def run_script(
    parser: argparse.ArgumentParser,
    argv: list[str] | None,
    worker: Callable[[argparse.Namespace, Any], tuple[int, dict[str, Any]]],
    *,
    args: argparse.Namespace | None = None,
) -> tuple[int, dict[str, Any]]:
    """Parse argv, build client, run worker, map errors to envelopes."""
    parsed = args if args is not None else parser.parse_args(argv)
    client = build_client()
    if isinstance(client, dict):
        return 1, client
    try:
        return worker(parsed, client)
    except Exception as exc:  # noqa: BLE001 — mapped to stable envelope codes
        mapped = map_discogs_error(exc)
        return 1, write_err(code=mapped["code"], message=mapped["message"])


def run_write_script(
    parser: argparse.ArgumentParser,
    argv: list[str] | None,
    worker: Callable[[argparse.Namespace, Any], tuple[int, dict[str, Any]]],
    *,
    would_do: Callable[[argparse.Namespace], dict[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Gate writes behind ``--confirm`` before building a client."""
    args = parser.parse_args(argv)
    preview = require_confirm(args, would_do(args))
    if preview is not None:
        return 1, preview
    return run_script(parser, argv, worker, args=args)


def finish(code: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Emit JSON envelope and return exit metadata for tests."""
    emit_json(payload)
    return code, payload
