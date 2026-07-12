"""Discover and load ``sevn.json`` into typed config + layout.

Module: sevn.config.loader
Depends: json, pathlib, sevn.config.defaults, sevn.config.errors, sevn.config.workspace_config, sevn.workspace.layout

Exports:
    find_sevn_json — walk parents for ``sevn.json``.
    operator_home_dir — resolve ``SEVN_HOME`` (default ``~/.sevn``).
    bound_sevn_json_path — ``{operator_home}/workspace/sevn.json``.
    resolve_sevn_json_path — bound file when present, else walk-up.
    load_workspace — parse file, validate schema, build ``WorkspaceLayout``.
    ensure_schema_supported — guard on ``defaults.SUPPORTED_SCHEMA_VERSIONS``.

Examples:
    >>> from pathlib import Path
    >>> from tempfile import TemporaryDirectory
    >>> from sevn.config.loader import find_sevn_json
    >>> with TemporaryDirectory() as d:
    ...     root = Path(d).resolve()
    ...     cfg = root / "sevn.json"
    ...     _ = cfg.write_text("{}", encoding="utf-8")
    ...     found = find_sevn_json(root)
    ...     found == cfg
    True
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sevn.config.defaults import SUPPORTED_SCHEMA_VERSIONS
from sevn.config.errors import (
    SevnJsonNotFoundError,
    UnsupportedSchemaVersionError,
)
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.workspace.layout import WorkspaceLayout


def find_sevn_json(start: Path | None = None) -> Path | None:
    """Return the first ``sevn.json`` found walking from ``start`` to filesystem root.

        Args:
    start (Path | None): Directory or file to begin from; default ``Path.cwd()``.

        Returns:
            Path | None: Path to config file, or ``None`` when absent.

        Examples:
            >>> from pathlib import Path
            >>> from tempfile import TemporaryDirectory
            >>> with TemporaryDirectory() as d:
            ...     root = Path(d).resolve()
            ...     cfg = root / "sevn.json"
            ...     _ = cfg.write_text("{}", encoding="utf-8")
            ...     found = find_sevn_json(root)
            ...     found == cfg
            True
    """
    base = (start or Path.cwd()).resolve()
    if base.is_file():
        base = base.parent
    for d in [base, *base.parents]:
        candidate = d / "sevn.json"
        if candidate.is_file():
            return candidate
    return None


def operator_home_dir() -> Path:
    """Resolve operator home from ``SEVN_HOME`` or default ``~/.sevn``.

    Returns:
        Path: Absolute operator home directory.

    Examples:
        >>> isinstance(operator_home_dir(), Path)
        True
    """
    ps = ProcessSettings()
    if ps.home is not None:
        return ps.home.expanduser().resolve()
    return (Path.home() / ".sevn").expanduser().resolve()


def bound_sevn_json_path() -> Path:
    """Return ``{operator_home}/workspace/sevn.json`` (no cwd walk-up).

    Returns:
        Path: Canonical bound config path.

    Examples:
        >>> bound_sevn_json_path().name
        'sevn.json'
    """
    return operator_home_dir() / "workspace" / "sevn.json"


def resolve_sevn_json_path(*, start: Path | None = None) -> Path | None:
    """Prefer bound ``sevn.json`` when present, else walk parents from ``start`` or cwd.

    Args:
        start (Path | None): Directory to begin upward search when bound file is absent.

    Returns:
        Path | None: Resolved config path, or ``None`` when not found.

    Examples:
        >>> import os, json, tempfile
        >>> from unittest.mock import patch
        >>> home = Path(tempfile.mkdtemp())
        >>> ws = home / "workspace"
        >>> _ = ws.mkdir()
        >>> _ = (ws / "sevn.json").write_text(
        ...     json.dumps({
        ...         "schema_version": 1,
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     }),
        ...     encoding="utf-8",
        ... )
        >>> with patch.dict(os.environ, {"SEVN_HOME": str(home)}):
        ...     found = resolve_sevn_json_path()
        ...     found is not None and found.resolve() == (ws / "sevn.json").resolve()
        True
    """
    bound = bound_sevn_json_path()
    if bound.is_file():
        return bound
    return find_sevn_json(start)


def ensure_schema_supported(version: int) -> None:
    """Fail fast when the workspace config version is newer than this binary.

        Args:
    version (int): ``schema_version`` from ``sevn.json``.

        Raises:
            UnsupportedSchemaVersionError: When ``version`` is not in the supported set.

        Returns:
            None: When supported.

        Examples:
            >>> ensure_schema_supported(1) is None
            True
            >>> import pytest
            >>> from sevn.config.errors import UnsupportedSchemaVersionError
            >>> with pytest.raises(UnsupportedSchemaVersionError):
            ...     ensure_schema_supported(99999)
    """
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        known = ", ".join(str(v) for v in sorted(SUPPORTED_SCHEMA_VERSIONS))
        msg = f"unsupported schema_version={version}; this binary supports: {known}"
        raise UnsupportedSchemaVersionError(msg)


def load_workspace(
    *,
    sevn_json: Path | None = None,
    start_dir: Path | None = None,
) -> tuple[WorkspaceConfig, WorkspaceLayout]:
    """Load ``sevn.json`` from an explicit path or by walking parents from ``start_dir``.

        Args:
    sevn_json (Path | None): Explicit config file path.
    start_dir (Path | None): Directory to search upward when ``sevn_json`` is ``None``.

        Returns:
            tuple[WorkspaceConfig, WorkspaceLayout]: Parsed config and resolved layout.

        Raises:
            SevnJsonNotFoundError: When no file can be found.
            UnsupportedSchemaVersionError: When schema version is unknown.
            pydantic.ValidationError: When JSON fails model validation.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> from sevn.config.loader import load_workspace
            >>> td = Path(tempfile.mkdtemp())
            >>> _ = (td / "sevn.json").write_text(
            ...     '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
            ...     encoding="utf-8",
            ... )
            >>> cfg, lay = load_workspace(sevn_json=td / "sevn.json")
            >>> cfg.schema_version
            1
            >>> lay.content_root == td.resolve()
            True
    """
    path = sevn_json
    if path is None:
        found = resolve_sevn_json_path(start=start_dir)
        if found is None:
            raise SevnJsonNotFoundError(
                "sevn.json not found (searched parents from "
                f"{(start_dir or Path.cwd()).resolve()!s})",
            )
        path = found
    cfg_path = path.expanduser().resolve()
    if not cfg_path.is_file():
        raise SevnJsonNotFoundError(f"sevn.json is not a file: {cfg_path}")
    raw: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg = parse_workspace_config(raw)
    ensure_schema_supported(cfg.schema_version)
    layout = WorkspaceLayout.from_config(cfg_path, cfg)
    return cfg, layout
