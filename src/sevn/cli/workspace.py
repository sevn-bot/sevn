"""Bind operator workspace root and load ``sevn.json`` (`specs/23-cli.md` §2.2, §2.1).

Module: sevn.cli.workspace
Depends: json, pathlib, pydantic, sevn.config.errors, sevn.config.settings, sevn.config.workspace_config, sevn.workspace.layout

Exports:
    sevn_home_dir — resolve ``SEVN_HOME`` defaulting to ``~/.sevn``.
    bound_workspace_dir — ``<SEVN_HOME>/workspace``.
    bound_sevn_json_path — expected ``sevn.json`` location (no cwd walk-up).
    operator_home_from_sevn_json — derive ``SEVN_HOME`` from a promoted ``sevn.json`` path.
    BoundWorkspace — loaded config + layout + raw JSON.
    load_bound_workspace — parse bound file; failures as ``CliPreconditionError``.
    load_doctor_workspace — like ``load_bound_workspace`` but tolerates missing ``gateway.token``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sevn.cli.errors import CliPreconditionError
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.config.loader import ensure_schema_supported
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.workspace.layout import WorkspaceLayout


def sevn_home_dir() -> Path:
    """Resolve operator home from ``SEVN_HOME`` or default ``~/.sevn``.

    Returns:
        Path: Absolute operator home directory.

    Examples:
        >>> isinstance(sevn_home_dir(), Path)
        True
    """
    ps = ProcessSettings()
    if ps.home is not None:
        return ps.home.expanduser().resolve()
    return (Path.home() / ".sevn").expanduser().resolve()


def bound_workspace_dir() -> Path:
    """Return the default workspace directory under operator home.

    Returns:
        Path: ``<SEVN_HOME>/workspace``.

    Examples:
        >>> isinstance(bound_workspace_dir(), Path)
        True
    """
    return sevn_home_dir() / "workspace"


def bound_sevn_json_path() -> Path:
    """Return the canonical ``sevn.json`` path (no cwd walk-up).

    Returns:
        Path: ``<SEVN_HOME>/workspace/sevn.json``.

    Examples:
        >>> bound_sevn_json_path().name
        'sevn.json'
    """
    return bound_workspace_dir() / "sevn.json"


def operator_home_from_sevn_json(sevn_json: Path) -> Path:
    """Derive ``SEVN_HOME`` from a promoted ``sevn.json`` path.

    Standard layout is ``<SEVN_HOME>/workspace/sevn.json``. When the parent
    directory is named ``workspace``, operator home is two levels up; otherwise
    the parent of ``sevn.json`` is treated as the workspace directory.

    Args:
        sevn_json (Path): Absolute or user path to ``sevn.json``.

    Returns:
        Path: Operator home for ``SEVN_HOME`` in spawned gateway/proxy children.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> home = Path(tempfile.mkdtemp())
        >>> ws = home / "workspace"
        >>> _ = ws.mkdir()
        >>> sj = ws / "sevn.json"
        >>> operator_home_from_sevn_json(sj) == home.resolve()
        True
    """
    resolved = sevn_json.expanduser().resolve()
    if resolved.parent.name == "workspace":
        return resolved.parent.parent
    return resolved.parent


@dataclass(frozen=True)
class BoundWorkspace:
    """Loaded workspace anchored at ``{SEVN_HOME}/workspace/sevn.json``.

    Examples:
        >>> BoundWorkspace.__name__ == "BoundWorkspace"
        True
    """

    sevn_json_path: Path
    config: WorkspaceConfig
    layout: WorkspaceLayout
    raw: dict[str, Any]


def load_bound_workspace() -> BoundWorkspace:
    """Load ``sevn.json`` from the bound workspace root only.

    Returns:
        BoundWorkspace: Parsed config, layout, and raw JSON.

    Raises:
        CliPreconditionError: Missing file, I/O, or validation failure (exit ``4``).

    Examples:
        >>> import json, os, tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> home = Path(tempfile.mkdtemp())
        >>> _ = (home / "workspace").mkdir()
        >>> _ = (home / "workspace" / "sevn.json").write_text(
        ...     json.dumps({
        ...         "schema_version": 1,
        ...         "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     }),
        ...     encoding="utf-8",
        ... )
        >>> with patch.dict(os.environ, {"SEVN_HOME": str(home)}):
        ...     load_bound_workspace().config.schema_version
        1
    """
    path = bound_sevn_json_path()
    if not path.is_file():
        raise CliPreconditionError(
            f"workspace not bound: missing sevn.json at {path} "
            "(complete onboarding or set SEVN_HOME; the CLI does not search upward from cwd)",
            exit_code=4,
        )
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliPreconditionError(
            f"cannot read sevn.json: {path} ({exc})",
            exit_code=4,
        ) from exc
    if not isinstance(raw, dict):
        raise CliPreconditionError("sevn.json must be a JSON object", exit_code=4)
    try:
        cfg = parse_workspace_config(raw)
        ensure_schema_supported(cfg.schema_version)
    except (ValidationError, UnsupportedSchemaVersionError, ValueError) as exc:
        raise CliPreconditionError(
            f"invalid sevn.json: {exc}",
            exit_code=4,
        ) from exc
    layout = WorkspaceLayout.from_config(path, cfg)
    return BoundWorkspace(sevn_json_path=path, config=cfg, layout=layout, raw=raw)


def load_doctor_workspace() -> BoundWorkspace:
    """Load ``sevn.json`` for ``sevn doctor`` (lenient when ``gateway.token`` is absent).

    ``sevn doctor`` must always run and report failures; it cannot require a fully valid
    config before the operator can see what is wrong. When ``gateway.token`` is missing
    from the on-disk document, a parse-time placeholder ref is injected so the rest of
    the probes can run; :attr:`BoundWorkspace.raw` still reflects the file as written.

    Returns:
        BoundWorkspace: Parsed config, layout, and unmodified raw JSON.

    Raises:
        CliPreconditionError: Missing file, I/O, or non-gateway validation failure.

    Examples:
        >>> import json, os, tempfile
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> home = Path(tempfile.mkdtemp())
        >>> _ = (home / "workspace").mkdir()
        >>> _ = (home / "workspace" / "sevn.json").write_text(
        ...     json.dumps({"schema_version": 1}),
        ...     encoding="utf-8",
        ... )
        >>> with patch.dict(os.environ, {"SEVN_HOME": str(home)}):
        ...     load_doctor_workspace().config.schema_version
        1
    """
    try:
        return load_bound_workspace()
    except CliPreconditionError as exc:
        if "gateway.token is required" not in str(exc):
            raise
    path = bound_sevn_json_path()
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliPreconditionError(
            f"cannot read sevn.json: {path} ({exc})",
            exit_code=4,
        ) from exc
    if not isinstance(raw, dict):
        raise CliPreconditionError("sevn.json must be a JSON object", exit_code=4)
    from sevn.gateway.gateway_token import GATEWAY_TOKEN_CONFIG_REF

    parse_doc: dict[str, Any] = dict(raw)
    gateway_section = parse_doc.get("gateway")
    if not isinstance(gateway_section, dict):
        parse_doc["gateway"] = {"token": GATEWAY_TOKEN_CONFIG_REF}
    elif not str(gateway_section.get("token") or "").strip():
        parse_doc["gateway"] = {**gateway_section, "token": GATEWAY_TOKEN_CONFIG_REF}
    try:
        cfg = parse_workspace_config(parse_doc)
        ensure_schema_supported(cfg.schema_version)
    except (ValidationError, UnsupportedSchemaVersionError, ValueError) as exc:
        raise CliPreconditionError(
            f"invalid sevn.json: {exc}",
            exit_code=4,
        ) from exc
    layout = WorkspaceLayout.from_config(path, cfg)
    return BoundWorkspace(sevn_json_path=path, config=cfg, layout=layout, raw=raw)
