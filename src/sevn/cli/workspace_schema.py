"""``infra/sevn.schema.json`` dot-path helpers for ``sevn config set``.

Module: sevn.cli.workspace_schema
Depends: importlib.resources, json, pathlib, sevn.cli.repo_sync

Exports:
    load_workspace_json_schema — load repo ``infra/sevn.schema.json``.
    dotted_path_in_schema — whether a dot path is declared in the schema tree.
    parse_config_set_value — coerce argv value strings to JSON/Python values.
    config_set_reload_hint — stderr reload hint for unknown writable paths.
"""

from __future__ import annotations

import contextlib
import json
import os
from importlib import resources
from pathlib import Path
from typing import Any

from sevn.cli.repo_sync import RepoSyncError, resolve_sevn_repo_root

_CONFIG_SET_RELOAD_MATRIX: dict[str, str] = {
    "tracing.sinks": "automatic",
    "gateway.queue_mode": "signal",
    "gateway.steer": "signal",
    "providers.tier_default": "signal",
}


def _parse_schema_file(path: Path) -> dict[str, Any]:
    """Read and validate one ``sevn.schema.json`` path.

    Args:
        path (Path): Filesystem path to the schema file.

    Returns:
        dict[str, Any]: Parsed JSON Schema root object.

    Raises:
        OSError: When the file cannot be read.
        json.JSONDecodeError: When the file is not valid JSON.
        ValueError: When the root is not a JSON object.

    Examples:
        >>> from pathlib import Path
        >>> p = next(iter(_iter_workspace_schema_paths()))
        >>> doc = _parse_schema_file(p)
        >>> "properties" in doc
        True
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "infra/sevn.schema.json root must be a JSON object"
        raise ValueError(msg)
    return raw


def _iter_workspace_schema_paths() -> tuple[Path, ...]:
    """Yield candidate ``sevn.schema.json`` locations (checkout, then wheel bundle).

    Returns:
        tuple[Path, ...]: Existing paths in resolution order.

    Examples:
        >>> paths = _iter_workspace_schema_paths()
        >>> len(paths) >= 1
        True
    """
    seen: set[Path] = set()
    ordered: list[Path] = []

    def _add(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved in seen or not candidate.is_file():
            return
        seen.add(resolved)
        ordered.append(candidate)

    env_root = os.environ.get("SEVN_REPO_ROOT", "").strip()
    if env_root:
        _add(Path(env_root) / "infra" / "sevn.schema.json")

    with contextlib.suppress(RepoSyncError):
        _add(resolve_sevn_repo_root() / "infra" / "sevn.schema.json")

    here = Path(__file__).resolve()
    for parent in here.parents:
        _add(parent / "infra" / "sevn.schema.json")
        if (parent / "pyproject.toml").is_file():
            break

    return tuple(ordered)


def _load_bundled_workspace_schema() -> dict[str, Any] | None:
    """Load schema from ``sevn.data`` when no checkout path exists.

    Returns:
        dict[str, Any] | None: Parsed schema, or ``None`` when the bundle is absent.

    Examples:
        >>> doc = _load_bundled_workspace_schema()
        >>> doc is None or isinstance(doc.get("properties"), dict)
        True
    """
    try:
        ref = resources.files("sevn.data") / "sevn.schema.json"
        if not ref.is_file():
            return None
        raw = json.loads(ref.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, TypeError, ValueError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def load_workspace_json_schema() -> dict[str, Any]:
    """Load ``infra/sevn.schema.json`` from checkout or bundled package data.

    Returns:
        dict[str, Any]: Parsed JSON Schema document.

    Raises:
        FileNotFoundError: When no schema file can be resolved.
        OSError: When the schema file cannot be read.
        json.JSONDecodeError: When the schema file is not valid JSON.

    Examples:
        >>> doc = load_workspace_json_schema()
        >>> "properties" in doc
        True
    """
    for path in _iter_workspace_schema_paths():
        return _parse_schema_file(path)
    bundled = _load_bundled_workspace_schema()
    if bundled is not None:
        return bundled
    msg = (
        "could not locate sevn.schema.json "
        "(set SEVN_REPO_ROOT, run from checkout, or reinstall sevn with bundled schema)"
    )
    raise FileNotFoundError(msg)


def _resolve_schema_ref(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Follow a local ``#/$defs/...`` JSON Schema ``$ref`` within ``schema``.

    Args:
        schema (dict[str, Any]): Parsed workspace JSON Schema root.
        node (dict[str, Any]): Current schema sub-node (may be a ``$ref`` wrapper).

    Returns:
        dict[str, Any]: Resolved target object, or ``node`` when not a local ref.

    Examples:
        >>> root = load_workspace_json_schema()
        >>> openai = root["properties"]["providers"]["properties"]["openai"]
        >>> resolved = _resolve_schema_ref(root, openai)
        >>> "auth_mode" in resolved.get("properties", {})
        True
    """
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return node
    target: Any = schema
    for part in ref[2:].split("/"):
        if not isinstance(target, dict) or part not in target:
            return node
        target = target[part]
    return target if isinstance(target, dict) else node


def _schema_defines_value(node: dict[str, Any]) -> bool:
    """Return whether a schema node can hold a config value (leaf or object branch).

    Args:
        node (dict[str, Any]): Resolved JSON Schema sub-node.

    Returns:
        bool: ``True`` when the node declares a type, ``$ref``, or ``oneOf``/``anyOf``.

    Examples:
        >>> _schema_defines_value({"type": "string"})
        True
        >>> _schema_defines_value({})
        False
    """
    if node.get("$ref") or node.get("type"):
        return True
    return bool(node.get("oneOf") or node.get("anyOf"))


def dotted_path_in_schema(schema: dict[str, Any], dotted: str) -> bool:
    """Return whether ``dotted`` is allowed by the schema property tree.

    Each segment must appear under a parent object's ``properties`` table, or
    as a dynamic key when the parent declares ``additionalProperties`` with a
    schema (e.g. ``providers.tier_default.B``). Local ``#/$defs/...`` ``$ref``
    nodes (e.g. ``providers.openai`` → ``provider_registry_entry``) are
    followed so nested keys like ``providers.openai.auth_mode`` resolve correctly.

    Args:
        schema (dict[str, Any]): Parsed workspace JSON Schema root.
        dotted (str): Dot-separated path (e.g. ``gateway.port``).

    Returns:
        bool: ``True`` when every segment is declared in ``properties``.

    Examples:
        >>> s = load_workspace_json_schema()
        >>> dotted_path_in_schema(s, "gateway.port")
        True
        >>> dotted_path_in_schema(s, "providers.openai.auth_mode")
        True
        >>> dotted_path_in_schema(s, "providers.tier_default.B")
        True
        >>> dotted_path_in_schema(s, "not.in.schema.at.all")
        False
    """
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return False
    node: Any = schema
    for index, key in enumerate(parts):
        if not isinstance(node, dict):
            return False
        node = _resolve_schema_ref(schema, node)
        props = node.get("properties")
        if isinstance(props, dict) and key in props:
            node = props[key]
            continue
        addl = node.get("additionalProperties")
        if isinstance(addl, dict):
            resolved_addl = _resolve_schema_ref(schema, addl)
            if _schema_defines_value(resolved_addl):
                if index == len(parts) - 1:
                    return True
                node = resolved_addl
                continue
        return False
    return True


def parse_config_set_value(raw: str) -> Any:
    """Parse ``sevn config set`` argv value text.

    Args:
        raw (str): Raw argument text (JSON literal or plain string).

    Returns:
        Any: Parsed JSON value when ``raw`` is valid JSON; otherwise ``raw``.

    Examples:
        >>> parse_config_set_value("3002")
        3002
        >>> parse_config_set_value("hello")
        'hello'
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def config_set_reload_hint(dotted: str) -> str | None:
    """Return a reload hint when ``dotted`` is absent from the reload matrix.

    Args:
        dotted (str): Dot path written by ``sevn config set``.

    Returns:
        str | None: Human hint text, or ``None`` when the path is known.

    Examples:
        >>> config_set_reload_hint("gateway.queue_mode") is None
        True
        >>> config_set_reload_hint("gateway.port") == "restart recommended"
        True
    """
    for prefix in _CONFIG_SET_RELOAD_MATRIX:
        if dotted == prefix or dotted.startswith(f"{prefix}."):
            return None
    return "restart recommended"
