"""Signed media paths + DB index (`specs/17-gateway.md` §3.3).

Module: sevn.gateway.media_store
Depends: sqlite3, pathlib

Exports:
    MediaStore — persist attachment descriptors, resolve download tokens.
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path


class MediaStore:
    """Disk layout ``channel_files/<session_id>/`` with token metadata rows."""

    def __init__(self, conn: sqlite3.Connection, content_root: Path) -> None:
        """Bind the media store to its SQLite handle and content root.

        Args:
            conn (sqlite3.Connection): Open ``sevn.db`` connection.
            content_root (Path): Workspace content root for sandboxed writes.

        Examples:
            >>> import inspect
            >>> "conn" in inspect.signature(MediaStore).parameters
            True
        """
        self._conn = conn
        self._root = content_root.expanduser().resolve()
        self._io_lock = asyncio.Lock()

    def channel_files_dir(self, session_id: str) -> Path:
        """Return the on-disk directory for a session scope.

        Args:
            session_id (str): Gateway session id.

        Returns:
            Path: ``<content_root>/channel_files/<session_id>`` path object.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MediaStore.channel_files_dir)
            True
        """

        return self._root / "channel_files" / session_id

    async def persist_attachment_descriptors(
        self,
        session_id: str,
        descriptors: list[dict[str, Any]],
    ) -> None:
        """Write optional inline bytes (``data_base64``) for tests / dev harness.

        Args:
            session_id (str): Target session id.
            descriptors (list[dict[str, Any]]): Attachment descriptors as
                produced by the adapter; only entries with ``data_base64``
                are materialised.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MediaStore.persist_attachment_descriptors)
            True
        """

        if not descriptors:
            return
        async with self._io_lock:
            await asyncio.to_thread(self._persist_sync, session_id, descriptors)

    def _persist_sync(self, session_id: str, descriptors: list[dict[str, Any]]) -> None:
        """Decode base64 attachment descriptors and write them to disk.

        Args:
            session_id (str): Target session id.
            descriptors (list[dict[str, Any]]): Attachment descriptors with
                ``data_base64`` and optional ``filename`` keys.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MediaStore._persist_sync)
            True
        """
        target = self.channel_files_dir(session_id)
        target.mkdir(parents=True, exist_ok=True)
        for idx, desc in enumerate(descriptors):
            name = str(desc.get("filename") or f"attachment-{idx}.bin")
            path = target / name
            if path.is_file():
                continue
            raw_b64 = desc.get("data_base64")
            if not isinstance(raw_b64, str):
                continue
            data = base64.b64decode(raw_b64.encode("ascii"), validate=True)
            path.write_bytes(data)

    async def register_token(self, session_id: str, rel_path: str, *, ttl_s: int = 600) -> str:
        """Insert a short-lived download token returning the opaque string.

        Args:
            session_id (str): Owning gateway session id.
            rel_path (str): Path relative to :meth:`channel_files_dir`.
            ttl_s (int, optional): Token lifetime in seconds. Defaults to 600.

        Returns:
            str: URL-safe opaque token for use in signed URLs.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(MediaStore.register_token)
            True
        """

        token = secrets.token_urlsafe(18)
        expires_at_ns = time.time_ns() + int(ttl_s * 1_000_000_000)

        def _ins() -> None:
            self._conn.execute(
                """INSERT OR REPLACE INTO gateway_media_tokens(token, session_id, rel_path, expires_at_ns)
                VALUES (?,?,?,?)""",
                (token, session_id, rel_path, expires_at_ns),
            )
            self._conn.commit()

        async with self._io_lock:
            await asyncio.to_thread(_ins)
        return token

    def resolve_path(self, token: str) -> Path | None:
        """Map token to absolute path or ``None`` when missing/expired.

        Args:
            token (str): Opaque token produced by :meth:`register_token`.

        Returns:
            Path | None: Absolute path under ``content_root`` or ``None`` when
            the token is unknown, expired, or escapes the sandbox.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(MediaStore.resolve_path)
            True
        """

        row = self._conn.execute(
            "SELECT session_id, rel_path, expires_at_ns FROM gateway_media_tokens WHERE token = ?",
            (token,),
        ).fetchone()
        if row is None:
            return None
        session_id, rel_path, expires_at_ns = str(row[0]), str(row[1]), int(row[2])
        if time.time_ns() > expires_at_ns:
            return None
        base = self.channel_files_dir(session_id)
        candidate = (base / rel_path).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        return candidate
