"""Oversized inbound payloads spill into ``lcm_large_files`` (`specs/15-memory-lcm.md` §3).

v1 stores **full text in SQLite** on the ``content`` column and leaves ``storage_path`` null
until a future slice optionally relocates bytes under workspace-relative paths (never under
``.llmignore/``). ``byte_size`` records UTF-8 length for operator dashboards.

Module: sevn.lcm.large_files
Depends: uuid

Exports:
    LargeFileSpill — descriptor returned when content is spilled.
    maybe_spill_large_payload — insert spill row + stub message body.

Examples:
    >>> from sevn.lcm.large_files import maybe_spill_large_payload
    >>> maybe_spill_large_payload.__name__
    'maybe_spill_large_payload'
"""

from __future__ import annotations

import sqlite3  # noqa: TC003 — public API takes ``sqlite3.Connection``
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final


@dataclass(frozen=True)
class LargeFileSpill:
    """Reference replacing verbatim body when above threshold (`specs/15-memory-lcm.md` §3)."""

    file_id: str
    stub_content: str


_STUB_PREFIX: Final[str] = "[lcm_large_file:"
_STUB_SUFFIX: Final[str] = "]"


def maybe_spill_large_payload(
    *,
    conn: sqlite3.Connection,
    conversation_id: int,
    token_estimate: int,
    threshold: int,
    content: str,
    file_name: str | None,
    mime_type: str | None,
) -> LargeFileSpill | None:
    """Insert ``lcm_large_files`` and return stub text when over threshold.

        Args:
    conn (sqlite3.Connection): Workspace DB connection.
    conversation_id (int): Owning ``lcm_conversations.id``.
    token_estimate (int): Estimated tokens for ``content``.
    threshold (int): ``lcm_large_file_token_threshold`` effective value.
    content (str): Full payload text (stored server-side only).
    file_name (str | None): Optional original filename hint.
    mime_type (str | None): Optional MIME hint.

        Returns:
            LargeFileSpill | None: Spill descriptor or ``None`` when under threshold.

        Examples:
            >>> isinstance(_STUB_PREFIX, str)
            True
    """
    if token_estimate < threshold:
        return None
    file_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat(timespec="seconds")
    encoded = content.encode("utf-8")
    conn.execute(
        """
        INSERT INTO lcm_large_files (
            file_id, conversation_id, file_name, mime_type, content,
            exploration_summary, byte_size, storage_path, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            conversation_id,
            file_name,
            mime_type,
            content,
            None,
            len(encoded),
            None,
            now,
        ),
    )
    stub = f"{_STUB_PREFIX}{file_id}{_STUB_SUFFIX}"
    return LargeFileSpill(file_id=file_id, stub_content=stub)
