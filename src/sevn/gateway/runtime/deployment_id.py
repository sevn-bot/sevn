"""Persistent gateway deployment identifier (`specs/17-gateway.md` §10.14 TE-1).

Module: sevn.gateway.runtime.deployment_id
Depends: pathlib (stdlib), socket (stdlib), secrets (stdlib), datetime (stdlib),
    json (stdlib)

Exports:
    load_or_create_deployment_id — return persisted gateway deployment id, creating one on first call.

Examples:
    >>> import tempfile
    >>> from pathlib import Path
    >>> from sevn.gateway.runtime.deployment_id import load_or_create_deployment_id
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     did = load_or_create_deployment_id(Path(tmp))
    ...     isinstance(did, str) and bool(did)
    True
"""

from __future__ import annotations

import json
import re
import secrets
import socket
from datetime import UTC, datetime
from pathlib import Path

_DEPLOYMENT_ID_FILENAME = "deployment_id.json"
_DOT_SEVN_DIRNAME = ".sevn"
_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"
# Conservative hostname sanitiser: keep alnum/hyphen/dot/underscore; replace the rest with '-'.
_HOSTNAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitised_hostname() -> str:
    """Return a filesystem-safe hostname segment for the deployment id.

    Returns:
        str: ``socket.gethostname()`` with unsafe characters folded to ``-``;
            falls back to ``"unknown"`` when the hostname resolves to an empty
            string.

    Examples:
        >>> isinstance(_sanitised_hostname(), str)
        True
        >>> _sanitised_hostname() != ""
        True
    """
    raw = (socket.gethostname() or "").strip()
    if not raw:
        return "unknown"
    cleaned = _HOSTNAME_SAFE_RE.sub("-", raw).strip("-")
    return cleaned or "unknown"


def _generate_deployment_id() -> str:
    """Build a fresh ``{hostname}-{YYYYMMDDHHMMSS}-{6-char-hex}`` identifier.

    Returns:
        str: Newly minted deployment id using the current UTC timestamp and
            ``secrets.token_hex`` for the trailing entropy.

    Examples:
        >>> did = _generate_deployment_id()
        >>> len(did.rsplit("-", 1)[-1])
        6
        >>> did.count("-") >= 2
        True
    """
    host = _sanitised_hostname()
    stamp = datetime.now(tz=UTC).strftime(_TIMESTAMP_FORMAT)
    suffix = secrets.token_hex(3)  # six hex characters
    return f"{host}-{stamp}-{suffix}"


def load_or_create_deployment_id(content_root: Path) -> str:
    """Return the persisted gateway deployment id, creating it on first call.

    The identifier lives at ``<content_root>/.sevn/deployment_id.json`` and is
    rewritten only when the file is missing or unreadable. Subsequent calls
    return the same value, so the id remains stable across restarts and only
    changes when the JSON is deleted (which forces a fresh mint on the next
    call).

    Args:
        content_root (Path): Workspace content root resolved by
            :class:`sevn.workspace.layout.WorkspaceLayout`.

    Returns:
        str: Deployment id of the form ``{hostname}-{YYYYMMDDHHMMSS}-{hex6}``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     root = Path(tmp)
        ...     first = load_or_create_deployment_id(root)
        ...     second = load_or_create_deployment_id(root)
        ...     first == second
        True
    """
    root = Path(content_root).expanduser().resolve()
    dot_sevn = root / _DOT_SEVN_DIRNAME
    target = dot_sevn / _DEPLOYMENT_ID_FILENAME
    if target.is_file():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict):
            existing = payload.get("deployment_id")
            if isinstance(existing, str) and existing.strip():
                return existing
    dot_sevn.mkdir(parents=True, exist_ok=True)
    new_id = _generate_deployment_id()
    body = {
        "deployment_id": new_id,
        "created_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(target)
    return new_id
