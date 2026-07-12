"""Operator home discovery for onboarding reuse (`specs/22-onboarding.md` §4.1).

Module: sevn.cli.install_discovery
Depends: json, pathlib, sevn.cli.service_manager, sevn.security.secrets.backends.encrypted_file

Exports:
    InstallCandidate — installed ``~/.sevn*`` home with probe metadata.
    discover_operator_homes — glob homes with ``workspace/sevn.json``.
    resolve_keystore_path — keystore path from promoted config when present.
    resolve_workspace_keystore_path — default store path under a workspace dir.
    workspace_has_artifacts — True when a workspace dir has prior onboarding data.
    candidate_to_dict — JSON-safe serialization for wizard APIs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sevn.cli.service_manager import unit_is_active
from sevn.onboarding.draft_store import draft_path
from sevn.security.secrets.backends.encrypted_file import default_encrypted_store_path


@dataclass(frozen=True, slots=True)
class InstallCandidate:
    """One installed operator home under ``Path.home() / ".sevn*"``."""

    home: Path
    sevn_json: Path
    has_keystore: bool
    keystore_path: Path | None
    gateway_unit_active: bool
    proxy_unit_active: bool


def resolve_keystore_path(*, sevn_json: Path) -> Path | None:
    """Return the encrypted keystore path when configured and readable from disk.

    Args:
        sevn_json (Path): Promoted ``workspace/sevn.json``.

    Returns:
        Path | None: Absolute keystore path when the file exists, else ``None``.

    Examples:
        >>> resolve_keystore_path(sevn_json=Path("/nonexistent/sevn.json")) is None
        True
    """
    if not sevn_json.is_file():
        return None
    try:
        raw = json.loads(sevn_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    sb = raw.get("secrets_backend")
    if not isinstance(sb, dict):
        return None
    rel: str | None = None
    enc = sb.get("encrypted_file")
    if isinstance(enc, dict):
        path_val = enc.get("path")
        if isinstance(path_val, str) and path_val.strip():
            rel = path_val.strip()
    if rel is None:
        chain = sb.get("chain")
        if isinstance(chain, list):
            for entry in chain:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") == "encrypted_file":
                    path_val = entry.get("path")
                    if isinstance(path_val, str) and path_val.strip():
                        rel = path_val.strip()
                    break
    workspace_root = raw.get("workspace_root")
    wr = workspace_root if isinstance(workspace_root, str) and workspace_root.strip() else "."
    content_root = (sevn_json.parent / wr).resolve()
    store = Path(rel).expanduser() if rel else default_encrypted_store_path(content_root)
    if not store.is_absolute():
        store = (content_root / store).resolve()
    return store if store.is_file() else None


def resolve_workspace_keystore_path(workspace: Path) -> Path | None:
    """Return the default encrypted store path when it exists under *workspace*.

    Args:
        workspace (Path): Operator workspace directory (parent of ``sevn.json``).

    Returns:
        Path | None: Absolute ``store.enc`` path when present, else ``None``.

    Examples:
        >>> resolve_workspace_keystore_path(Path("/nonexistent")) is None
        True
    """
    if not workspace.is_dir():
        return None
    store = default_encrypted_store_path(workspace.resolve())
    return store if store.is_file() else None


def workspace_has_artifacts(workspace: Path) -> bool:
    """Return True when *workspace* contains data from a prior onboarding run.

    Detects promoted config, wizard draft, encrypted secrets, or other residue
    so a fresh ``sevn onboard`` can prompt reuse vs wipe before prefilling.

    Args:
        workspace (Path): Operator workspace directory.

    Returns:
        bool: Whether prior onboarding artifacts are present.

    Examples:
        >>> workspace_has_artifacts(Path("/nonexistent"))
        False
    """
    if not workspace.is_dir():
        return False
    sevn_json = workspace / "sevn.json"
    if sevn_json.is_file():
        return True
    if draft_path(sevn_json).is_file():
        return True
    if resolve_workspace_keystore_path(workspace) is not None:
        return True
    for child in workspace.iterdir():
        if child.name in {".DS_Store"}:
            continue
        if child.name == ".sevn" and child.is_dir():
            if any(child.rglob("*")):
                return True
            continue
        return True
    return False


def _candidate_from_home(home: Path) -> InstallCandidate | None:
    """Build an :class:`InstallCandidate` when ``home`` is installed.

    Args:
        home (Path): Candidate directory under the operator's home folder.

    Returns:
        InstallCandidate | None: Populated row or ``None`` when not installed.

    Examples:
        >>> from pathlib import Path
        >>> _candidate_from_home(Path("/nonexistent/.sevn")) is None
        True
    """
    sevn_json = home / "workspace" / "sevn.json"
    if not sevn_json.is_file():
        return None
    keystore = resolve_keystore_path(sevn_json=sevn_json)
    unit_home = Path.home()
    return InstallCandidate(
        home=home.resolve(),
        sevn_json=sevn_json.resolve(),
        has_keystore=keystore is not None,
        keystore_path=keystore,
        gateway_unit_active=unit_is_active(home=unit_home, service="gateway"),
        proxy_unit_active=unit_is_active(home=unit_home, service="proxy"),
    )


def discover_operator_homes() -> list[InstallCandidate]:
    """Glob ``Path.home()`` for ``.sevn*`` directories with promoted config.

    Returns:
        list[InstallCandidate]: Sorted installed homes.

    Examples:
        >>> isinstance(discover_operator_homes(), list)
        True
    """
    found: list[InstallCandidate] = []
    for path in sorted(Path.home().glob(".sevn*")):
        if not path.is_dir():
            continue
        row = _candidate_from_home(path)
        if row is not None:
            found.append(row)
    return found


def candidate_to_dict(candidate: InstallCandidate) -> dict[str, object]:
    """Serialize an :class:`InstallCandidate` for JSON APIs.

    Args:
        candidate (InstallCandidate): Discovery row.

    Returns:
        dict[str, object]: JSON-safe mapping.

    Examples:
        >>> from pathlib import Path
        >>> row = InstallCandidate(
        ...     home=Path("/h"),
        ...     sevn_json=Path("/h/workspace/sevn.json"),
        ...     has_keystore=False,
        ...     keystore_path=None,
        ...     gateway_unit_active=False,
        ...     proxy_unit_active=False,
        ... )
        >>> candidate_to_dict(row)["home"]
        '/h'
    """
    return {
        "home": str(candidate.home),
        "sevn_json": str(candidate.sevn_json),
        "has_keystore": candidate.has_keystore,
        "keystore_path": str(candidate.keystore_path) if candidate.keystore_path else None,
        "gateway_unit_active": candidate.gateway_unit_active,
        "proxy_unit_active": candidate.proxy_unit_active,
    }


__all__ = [
    "InstallCandidate",
    "candidate_to_dict",
    "discover_operator_homes",
    "resolve_keystore_path",
    "resolve_workspace_keystore_path",
    "workspace_has_artifacts",
]
