"""Deploy host inventory loader (`deploy/inventory.toml`).

Module: sevn.deploy.inventory
Depends: os, pathlib, tomllib, typing

Exports:
    DeployHost — resolved host entry with expanded paths.
    DeployInventory — parsed inventory with host map.
    DeployInventoryError — load or validation failure.
    load_inventory — parse a TOML inventory file.
    resolve_inventory_path — default inventory location.
    get_host — resolve one host id from inventory.

Private:
    _expand_path — expand ``~`` in inventory paths.
    _parse_host — validate and parse one host table.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REQUIRED_HOST_KEYS = ("host", "user", "identity_file", "remote_home")


class DeployInventoryError(ValueError):
    """Inventory file is missing, malformed, or incomplete."""


@dataclass(frozen=True, slots=True)
class DeployHost:
    """One deploy target from inventory."""

    host_id: str
    host: str
    user: str
    identity_file: Path
    remote_home: str
    remote_workspace: str = "workspace"
    gateway_port: int = 3001
    proxy_port: int = 8787


@dataclass(frozen=True, slots=True)
class DeployInventory:
    """Parsed deploy inventory."""

    path: Path
    hosts: dict[str, DeployHost]


def resolve_inventory_path(
    *,
    explicit: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Return the inventory file path to load.

    Args:
        explicit (Path | None): Operator override (``--inventory`` or env).
        repo_root (Path | None): Repository root; defaults to cwd.

    Returns:
        Path: Expected ``deploy/inventory.toml`` location.

    Examples:
        >>> p = resolve_inventory_path(explicit=Path("/tmp/inventory.toml"))
        >>> p == Path("/tmp/inventory.toml")
        True
    """
    if explicit is not None:
        return explicit.expanduser()
    env_path = os.environ.get("SEVN_DEPLOY_INVENTORY", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    root = (repo_root or Path.cwd()).resolve()
    return root / "deploy" / "inventory.toml"


def _expand_path(value: str) -> Path:
    """Expand user home in an inventory path string.

    Args:
        value (str): Path text from inventory TOML.

    Returns:
        Path: Absolute expanded path.

    Examples:
        >>> _expand_path("~/keys/id").name
        'id'
    """
    return Path(value).expanduser().resolve()


def _parse_host(host_id: str, raw: dict[str, Any]) -> DeployHost:
    """Parse one ``[hosts.<id>]`` table into :class:`DeployHost`.

    Args:
        host_id (str): Inventory host key.
        raw (dict[str, Any]): Host table mapping.

    Returns:
        DeployHost: Validated host entry.

    Examples:
        >>> host = _parse_host(
        ...     "staging",
        ...     {
        ...         "host": "203.0.113.10",
        ...         "user": "sevn",
        ...         "identity_file": "/tmp/id",
        ...         "remote_home": "/home/sevn/.sevn",
        ...     },
        ... )
        >>> host.host_id
        'staging'
    """
    missing = [key for key in _REQUIRED_HOST_KEYS if not str(raw.get(key, "")).strip()]
    if missing:
        msg = f"host {host_id!r} missing required field(s): {', '.join(missing)}"
        raise DeployInventoryError(msg)
    gateway_port = int(raw.get("gateway_port", 3001))
    proxy_port = int(raw.get("proxy_port", 8787))
    workspace = str(raw.get("remote_workspace", "workspace")).strip() or "workspace"
    return DeployHost(
        host_id=host_id,
        host=str(raw["host"]).strip(),
        user=str(raw["user"]).strip(),
        identity_file=_expand_path(str(raw["identity_file"])),
        remote_home=str(raw["remote_home"]).strip(),
        remote_workspace=workspace,
        gateway_port=gateway_port,
        proxy_port=proxy_port,
    )


def load_inventory(path: Path) -> DeployInventory:
    """Load and validate a deploy inventory TOML file.

    Args:
        path (Path): Inventory file path.

    Returns:
        DeployInventory: Parsed host map.

    Raises:
        DeployInventoryError: When the file is missing or invalid.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> text = (
        ...     '[hosts.staging]\\n'
        ...     'host = "203.0.113.10"\\n'
        ...     'user = "sevn"\\n'
        ...     'identity_file = "/tmp/id"\\n'
        ...     'remote_home = "/home/sevn/.sevn"\\n'
        ... )
        >>> with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
        ...     _ = handle.write(text)
        ...     inv_path = Path(handle.name)
        >>> inv = load_inventory(inv_path)
        >>> inv.hosts["staging"].host
        '203.0.113.10'
    """
    resolved = path.expanduser()
    if not resolved.is_file():
        msg = f"deploy inventory not found: {resolved} (copy deploy/inventory.example.toml)"
        raise DeployInventoryError(msg)
    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DeployInventoryError(f"invalid inventory TOML: {exc}") from exc
    raw_hosts = data.get("hosts")
    if not isinstance(raw_hosts, dict) or not raw_hosts:
        raise DeployInventoryError("inventory must define [hosts.<id>] entries")
    hosts: dict[str, DeployHost] = {}
    for host_id, entry in raw_hosts.items():
        if not isinstance(entry, dict):
            raise DeployInventoryError(f"host {host_id!r} must be a table")
        hosts[str(host_id)] = _parse_host(str(host_id), entry)
    return DeployInventory(path=resolved, hosts=hosts)


def get_host(inventory: DeployInventory, host_id: str) -> DeployHost:
    """Resolve a host id from inventory.

    Args:
        inventory (DeployInventory): Loaded inventory.
        host_id (str): Host key under ``[hosts.<id>]``.

    Returns:
        DeployHost: Resolved host entry.

    Raises:
        DeployInventoryError: When the host id is unknown.

    Examples:
        >>> inv = DeployInventory(path=Path("x.toml"), hosts={})
        >>> try:
        ...     get_host(inv, "missing")
        ... except DeployInventoryError:
        ...     True
        ... else:
        ...     False
        True
    """
    try:
        return inventory.hosts[host_id]
    except KeyError as exc:
        known = ", ".join(sorted(inventory.hosts))
        msg = f"unknown deploy host {host_id!r} (known: {known or 'none'})"
        raise DeployInventoryError(msg) from exc
