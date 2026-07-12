"""Atomic ``sevn.json`` read/write for gateway menu toggles.

Module: sevn.gateway.workspace_config_io
Depends: copy, json, pathlib, sevn.onboarding.draft_store, sevn.onboarding.promote,
    sevn.onboarding.validate, sevn.onboarding.web_app

Exports:
    set_nested — assign a dotted-path value, creating intermediate dicts.
    del_nested — delete a dotted-path key when present.
    load_raw_sevn_json — read workspace document from disk.
    mutate_sevn_json — apply a mutator and atomically promote.
Examples:
    >>> from pathlib import Path
    >>> isinstance(Path("."), Path)
    True
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sevn.onboarding.draft_store import write_draft
from sevn.onboarding.promote import promote_draft
from sevn.onboarding.validate import validate_workspace_document


def set_nested(doc: dict[str, Any], dotted: str, value: Any) -> None:
    """Assign ``value`` at a dot-separated path, creating intermediate dicts.

    Args:
        doc (dict[str, Any]): Target document (mutated in place).
        dotted (str): Field id such as ``gateway.token``.
        value (Any): Leaf value to store.

    Examples:
        >>> d: dict[str, Any] = {}
        >>> set_nested(d, "gateway.port", 3001)
        >>> d["gateway"]["port"]
        3001
    """
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return
    cur: dict[str, Any] = doc
    for key in parts[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[parts[-1]] = value


def del_nested(doc: dict[str, Any], dotted: str) -> None:
    """Delete a dotted-path key from ``doc`` if it exists (no-op otherwise).

    Args:
        doc (dict[str, Any]): Target document (mutated in place).
        dotted (str): Field id such as ``infrastructure.tunnel.token``.

    Examples:
        >>> d: dict[str, Any] = {"infrastructure": {"tunnel": {"token": "x", "mode": "ngrok"}}}
        >>> del_nested(d, "infrastructure.tunnel.token")
        >>> d["infrastructure"]["tunnel"]
        {'mode': 'ngrok'}
    """
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return
    cur: Any = doc
    for key in parts[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return
        cur = cur[key]
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def load_raw_sevn_json(sevn_json_path: Path) -> dict[str, Any]:
    """Load the workspace document from *sevn_json_path*.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.

    Returns:
        dict[str, Any]: Parsed workspace document.

    Raises:
        FileNotFoundError: When the file does not exist.
        json.JSONDecodeError: When the file is not valid JSON.

    Examples:
        >>> import tempfile, json
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> doc = {"schema_version": 1, "workspace_root": "."}
        >>> _ = (td / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
        >>> load_raw_sevn_json(td / "sevn.json")["schema_version"]
        1
    """
    raw = sevn_json_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        msg = "sevn.json root must be an object"
        raise ValueError(msg)
    return parsed


def mutate_sevn_json(
    sevn_json_path: Path,
    mutator: Callable[[dict[str, Any]], None],
    *,
    check_provider_credentials: bool = False,
) -> dict[str, Any]:
    """Apply *mutator* to a copy of ``sevn.json`` and atomically promote.

    In-place runtime edits (gateway menu toggles, model swaps, evolution
    mutators) validate the document *structurally* — schema version, gateway
    token, ``WorkspaceConfig`` parse, MiniMax transport — but do **not** block on
    provider-credential resolution (D7) by default. The credential posture is a
    pre-existing operator choice, unrelated to the edit being applied, and the
    key is often resolved at request time via the egress proxy/keychain where the
    static check cannot see it. Blocking an unrelated toggle on it left every
    ``/config`` button silently failing. Authoritative full validation still runs
    at onboarding promote and ``sevn config validate``; pass
    ``check_provider_credentials=True`` to opt back in.

    Args:
        sevn_json_path (Path): Path to ``sevn.json``.
        mutator (Callable[[dict[str, Any]], None]): In-place edit on a deep copy.
        check_provider_credentials (bool): When True, also flag assigned model
            slots whose provider has no statically-resolvable credential (D7).
            Defaults to False so runtime toggles never fail on a pre-existing,
            unrelated credential gap.

    Returns:
        dict[str, Any]: Promoted document after validation.

    Examples:
        >>> import tempfile, json
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> doc = {
        ...     "schema_version": 1,
        ...     "workspace_root": ".",
        ...     "gateway": {
        ...         "host": "127.0.0.1",
        ...         "port": 3001,
        ...         "queue_mode": "cancel",
        ...         "token": "${SECRET:keychain:sevn.gateway.token}",
        ...     },
        ... }
        >>> sj = td / "sevn.json"
        >>> _ = sj.write_text(json.dumps(doc), encoding="utf-8")
        >>> out = mutate_sevn_json(sj, lambda d: set_nested(d, "gateway.port", 3002))
        >>> out["gateway"]["port"]
        3002
    """
    updated = copy.deepcopy(load_raw_sevn_json(sevn_json_path))
    mutator(updated)
    validate_workspace_document(
        updated,
        check_provider_credentials=check_provider_credentials,
    )
    write_draft(sevn_json_path, updated)
    promote_draft(
        sevn_json_path,
        backup_previous=sevn_json_path.is_file(),
        check_provider_credentials=check_provider_credentials,
    )
    return updated


__all__ = ["del_nested", "load_raw_sevn_json", "mutate_sevn_json", "set_nested"]
