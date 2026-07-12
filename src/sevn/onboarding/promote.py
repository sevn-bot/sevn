"""Atomic ``draft → sevn.json`` promotion (`specs/22-onboarding.md` §2.1, §4.3).

Module: sevn.onboarding.promote
Depends: json, os, pathlib, typing

Exports:
    promote_draft — validate draft, optional backup, atomic rename.

Examples:
    >>> from pathlib import Path
    >>> from sevn.onboarding.merge import merge_layers
    >>> from sevn.onboarding.draft_store import write_draft, discard_draft
    >>> from sevn.onboarding.promote import promote_draft
    >>> # (exercise left to integration tests with tmp_path)
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from sevn.onboarding.draft_store import discard_draft, draft_path, read_draft
from sevn.onboarding.seed import seed_tracing_defaults
from sevn.onboarding.validate import validate_workspace_document

if TYPE_CHECKING:
    from pathlib import Path


def promote_draft(
    sevn_json_path: Path,
    *,
    backup_previous: bool = True,
    check_provider_credentials: bool = True,
) -> Path:
    """Promote ``.sevn.json.draft`` beside ``sevn.json`` to canonical ``sevn.json``.

    Args:
        sevn_json_path (Path): Target ``sevn.json`` path (file).
        backup_previous (bool): When ``sevn.json`` exists, write ``sevn.json.v{schema}`` first.
        check_provider_credentials (bool): When True (default), block promotion on an
            assigned model slot whose provider has no statically-resolvable credential
            (D7). Runtime in-place edits (gateway menu toggles) pass ``False`` so an
            unrelated, pre-existing credential gap does not abort the write.

    Returns:
        Path: Final ``sevn_json_path`` after promotion.

    Raises:
        FileNotFoundError: When no draft exists.
        sevn.config.errors.UnsupportedSchemaVersionError: Schema gate failure.
    Raises:
        pydantic.ValidationError: Pydantic validation failure.
        OSError: Disk errors during atomic write.

    Examples:
        >>> import tempfile
        >>> import json
        >>> from pathlib import Path
        >>> from sevn.onboarding.draft_store import write_draft
        >>> from sevn.onboarding.promote import promote_draft
        >>> td = Path(tempfile.mkdtemp())
        >>> sj = td / "sevn.json"
        >>> draft = {
        ...     "schema_version": 1,
        ...     "workspace_root": ".",
        ...     "gateway": {
        ...         "host": "127.0.0.1",
        ...         "port": 3001,
        ...         "queue_mode": "cancel",
        ...         "token": "${SECRET:keychain:sevn.gateway.token}",
        ...     },
        ... }
        >>> write_draft(sj, draft)
        >>> promote_draft(sj, backup_previous=False) == sj
        True
    """
    draft_file = draft_path(sevn_json_path)
    if not draft_file.is_file():
        msg = f"missing draft at {draft_file}"
        raise FileNotFoundError(msg)
    doc = read_draft(sevn_json_path)
    if doc is None:
        msg = "draft could not be read"
        raise FileNotFoundError(msg)
    seed_tracing_defaults(doc)
    validate_workspace_document(doc, check_provider_credentials=check_provider_credentials)

    sevn_json_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sevn_json_path.with_suffix(".json.tmp")
    payload = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp_fd = os.open(str(tmp), os.O_RDWR)
    try:
        os.fsync(tmp_fd)
    finally:
        os.close(tmp_fd)

    if sevn_json_path.is_file() and backup_previous:
        try:
            old_doc = json.loads(sevn_json_path.read_text(encoding="utf-8"))
            old_schema = int(old_doc.get("schema_version", 1))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            old_schema = 1
        backup = sevn_json_path.parent / f"sevn.json.v{old_schema}"
        target_backup = backup
        suffix = 0
        while target_backup.is_file():
            suffix += 1
            target_backup = sevn_json_path.parent / f"sevn.json.v{old_schema}.{suffix}"
        os.replace(sevn_json_path, target_backup)

    os.replace(tmp, sevn_json_path)
    discard_draft(sevn_json_path)
    return sevn_json_path
