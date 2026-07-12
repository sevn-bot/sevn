"""POSIX-locked JSONL writers for lesson stores (`specs/33-self-improvement.md` §3.7).

Module: sevn.self_improve.lessons.io
Depends: fcntl, json, pathlib, typing

Exports:
    append_jsonl_locked — append one JSON object with ``flock`` on POSIX hosts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def append_jsonl_locked(path: Path, row: dict[str, Any]) -> None:
    """Append a single JSON line using an exclusive advisory lock.

    Args:
    path (Path): Destination JSONL path (parent directories are created).
    row (dict[str, Any]): Serializable record.

    Returns:
        None: Writes and flushes before releasing the lock.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "rows.jsonl"
        >>> append_jsonl_locked(p, {"a": 1})
        >>> p.read_text(encoding="utf-8").strip() == '{"a": 1}'
        True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    import fcntl

    line = json.dumps(row, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line)
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
