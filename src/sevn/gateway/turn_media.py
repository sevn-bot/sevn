"""Turn-bound channel media for multimodal input (`specs/17-gateway.md` §3.3).

Module: sevn.gateway.turn_media
Depends: json, pathlib, sqlite3, mimetypes

Exports:
    TurnMediaItem — hydrated attachment bytes/URL + media_type at turn boundary.
    build_turn_media_summaries — serializable refs from inbound attachment descriptors.
    load_turn_media_summaries — read stored summaries from a user message row.
    hydrate_turn_media — load bytes from ``channel_files/<session_id>/``.
    attachment_hints_for_triager — kind + media_type hints (no bytes).
    infer_modality_flags — derive ``requires_vision`` / ``requires_document``.
"""

from __future__ import annotations

import json
import mimetypes
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PHOTO_KINDS = frozenset({"photo", "image"})
_DOCUMENT_KINDS = frozenset({"document"})
_SKIP_MULTIMODAL_KINDS = frozenset({"voice", "audio"})


@dataclass(frozen=True)
class TurnMediaItem:
    """One inbound attachment surfaced at the turn boundary for Tier B (W10).

    Attributes:
        kind (str): Channel attachment kind (``photo``, ``document``, …).
        media_type (str): MIME type for provider multimodal input.
        filename (str): Basename under ``channel_files/<session_id>/``.
        rel_path (str): Path relative to the session ``channel_files`` dir.
        data (bytes): Raw file bytes when materialised on disk.
        url (str | None): Optional fetchable URL when the channel supplied one.
    """

    kind: str
    media_type: str
    filename: str
    rel_path: str
    data: bytes
    url: str | None = None


def _resolve_media_type(att: dict[str, Any], filename: str) -> str:
    """Infer MIME type from attachment metadata and filename.

    Args:
        att (dict[str, Any]): Inbound attachment descriptor.
        filename (str): Materialised filename on disk.

    Returns:
        str: Best-effort MIME type string.

    Examples:
        >>> _resolve_media_type({"type": "photo"}, "x.jpg")
        'image/jpeg'
        >>> _resolve_media_type({"mime_type": "application/pdf"}, "doc.bin")
        'application/pdf'
    """
    for key in ("mime_type", "mime", "media_type"):
        raw = att.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().split(";", 1)[0].strip().casefold()
    kind = str(att.get("type") or att.get("kind") or "").strip().casefold()
    if kind in _PHOTO_KINDS:
        guessed, _ = mimetypes.guess_type(filename)
        return (guessed or "image/jpeg").casefold()
    guessed, _ = mimetypes.guess_type(filename)
    return (guessed or "application/octet-stream").casefold()


def build_turn_media_summaries(
    attachments: list[dict[str, Any]],
    *,
    media_dir: Path,
) -> list[dict[str, str]]:
    """Build JSON-safe turn media refs from inbound attachment descriptors.

    Voice/audio rows are omitted — those stay on the STT text path. Entries
    without ``data_base64`` still receive summaries when a matching file exists
    under ``media_dir`` (Telegram lazy download is out of scope for W9 tests).

    Args:
        attachments (list[dict[str, Any]]): ``IncomingMessage.attachments`` rows.
        media_dir (Path): Session ``channel_files`` directory.

    Returns:
        list[dict[str, str]]: Serializable summaries (``kind``, ``media_type``,
        ``filename``, ``rel_path``, optional ``url``).

    Examples:
        >>> import base64
        >>> from pathlib import Path
        >>> tmp = Path("/tmp/turn-media-example")
        >>> tmp.mkdir(parents=True, exist_ok=True)
        >>> att = [{"filename": "pic.png", "type": "photo", "data_base64": base64.b64encode(b"x").decode()}]
        >>> sums = build_turn_media_summaries(att, media_dir=tmp)
        >>> sums[0]["kind"]
        'photo'
    """
    out: list[dict[str, str]] = []
    for idx, att in enumerate(attachments):
        if not isinstance(att, dict):
            continue
        kind = str(att.get("type") or att.get("kind") or "").strip().casefold()
        if kind in _SKIP_MULTIMODAL_KINDS:
            continue
        filename = str(att.get("filename") or att.get("file_name") or f"attachment-{idx}.bin")
        rel_path = filename
        path = (media_dir / filename).resolve()
        if not path.is_file() and not att.get("data_base64") and not att.get("url"):
            continue
        media_type = _resolve_media_type(att, filename)
        row: dict[str, str] = {
            "kind": kind or "document",
            "media_type": media_type,
            "filename": filename,
            "rel_path": rel_path,
        }
        url_raw = att.get("url")
        if isinstance(url_raw, str) and url_raw.strip():
            row["url"] = url_raw.strip()
        out.append(row)
    return out


def load_turn_media_summaries(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: str,
) -> list[dict[str, str]]:
    """Load serialised turn media from the user message row for one dispatch.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Owning session id.
        turn_id (str): Turn / correlation id.

    Returns:
        list[dict[str, str]]: Stored summaries or empty when absent.

    Examples:
        >>> import sqlite3
        >>> load_turn_media_summaries(sqlite3.connect(":memory:"), "s", "t")
        []
    """
    try:
        row = conn.execute(
            """
            SELECT extras_json FROM gateway_messages
            WHERE session_id = ? AND turn_id = ? AND role = 'user'
            ORDER BY id DESC LIMIT 1
            """,
            (session_id, turn_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return []
    if row is None or not row[0]:
        return []
    try:
        parsed = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    raw = parsed.get("turn_media")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        media_type = str(item.get("media_type") or "")
        filename = str(item.get("filename") or "")
        rel_path = str(item.get("rel_path") or filename)
        if not filename:
            continue
        row_out: dict[str, str] = {
            "kind": kind,
            "media_type": media_type,
            "filename": filename,
            "rel_path": rel_path,
        }
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            row_out["url"] = url.strip()
        out.append(row_out)
    return out


def hydrate_turn_media(
    session_id: str,
    summaries: list[dict[str, str]],
    content_root: Path,
) -> tuple[TurnMediaItem, ...]:
    """Load raw bytes for serialised turn media summaries.

    Args:
        session_id (str): Gateway session id.
        summaries (list[dict[str, str]]): Output of :func:`build_turn_media_summaries`
            or :func:`load_turn_media_summaries`.
        content_root (Path): Workspace content root.

    Returns:
        tuple[TurnMediaItem, ...]: Hydrated items with ``data`` bytes when on disk.

    Examples:
        >>> from pathlib import Path
        >>> hydrate_turn_media("s", [], Path("/tmp"))
        ()
    """
    media_dir = content_root.expanduser().resolve() / "channel_files" / session_id
    items: list[TurnMediaItem] = []
    for raw in summaries:
        filename = str(raw.get("filename") or "")
        rel_path = str(raw.get("rel_path") or filename)
        path = (media_dir / rel_path).resolve()
        data = b""
        if path.is_file():
            data = path.read_bytes()
        url_raw = raw.get("url")
        url = url_raw.strip() if isinstance(url_raw, str) and url_raw.strip() else None
        items.append(
            TurnMediaItem(
                kind=str(raw.get("kind") or "document"),
                media_type=str(raw.get("media_type") or "application/octet-stream"),
                filename=filename,
                rel_path=rel_path,
                data=data,
                url=url,
            ),
        )
    return tuple(items)


def attachment_hints_for_triager(
    summaries: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Build Triager attachment hints (kind + media_type, no bytes).

    Args:
        summaries (list[dict[str, str]]): Turn media summaries.

    Returns:
        list[dict[str, str]]: Rows for ``ApprovedUserTurn.attachment_descriptors``.

    Examples:
        >>> attachment_hints_for_triager(
        ...     [{"kind": "photo", "media_type": "image/png", "filename": "a.png", "rel_path": "a.png"}]
        ... )
        [{'kind': 'photo', 'media_type': 'image/png', 'name': 'a.png'}]
    """
    hints: list[dict[str, str]] = []
    for raw in summaries:
        hints.append(
            {
                "kind": str(raw.get("kind") or "document"),
                "media_type": str(raw.get("media_type") or "application/octet-stream"),
                "name": str(raw.get("filename") or ""),
            },
        )
    return hints


def infer_modality_flags(
    hints: list[dict[str, str]],
) -> tuple[bool, bool]:
    """Derive ``requires_vision`` / ``requires_document`` from attachment hints.

    Args:
        hints (list[dict[str, str]]): Triager attachment presence hints.

    Returns:
        tuple[bool, bool]: ``(requires_vision, requires_document)``.

    Examples:
        >>> infer_modality_flags([{"kind": "photo", "media_type": "image/png", "name": "a.png"}])
        (True, False)
        >>> infer_modality_flags(
        ...     [{"kind": "document", "media_type": "application/pdf", "name": "r.pdf"}]
        ... )
        (False, True)
    """
    requires_vision = False
    requires_document = False
    for hint in hints:
        kind = str(hint.get("kind") or "").casefold()
        media_type = str(hint.get("media_type") or "").casefold()
        name = str(hint.get("name") or "").casefold()
        if kind in _PHOTO_KINDS or media_type.startswith("image/"):
            requires_vision = True
        if kind in _DOCUMENT_KINDS and (media_type == "application/pdf" or name.endswith(".pdf")):
            requires_document = True
    return requires_vision, requires_document
