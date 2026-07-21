"""PR #48 MiniMax download-cap + persist-fallback RED (green after W14)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sevn.agent.subagents.media_minimax import _MAX_DOWNLOAD_BYTES, MiniMaxMediaError, _download_url
from sevn.agent.subagents.media_worker import _persist_bytes
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W14: download size cap", strict=False)
async def test_download_url_rejects_oversized_content_length() -> None:
    http = MagicMock()
    resp = MagicMock()
    resp.headers = {"Content-Length": str(_MAX_DOWNLOAD_BYTES + 1)}
    resp.content = b"x"
    resp.raise_for_status = MagicMock()
    http.get = AsyncMock(return_value=resp)
    with pytest.raises(MiniMaxMediaError, match="size cap"):
        await _download_url(http, "https://example.com/big.bin")


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W14: download size cap body", strict=False)
async def test_download_url_rejects_oversized_body() -> None:
    http = MagicMock()
    resp = MagicMock()
    resp.headers = {}
    resp.content = b"x" * (_MAX_DOWNLOAD_BYTES + 1)
    resp.raise_for_status = MagicMock()
    http.get = AsyncMock(return_value=resp)
    with pytest.raises(MiniMaxMediaError, match="size cap"):
        await _download_url(http, "https://example.com/big.bin")


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W14: persist_bytes size mismatch fallback", strict=False)
async def test_persist_bytes_falls_back_on_size_mismatch(tmp_path: Path) -> None:
    dot = tmp_path / ".sevn"
    dot.mkdir()
    conn = sqlite3.connect(str(sevn_db_path(dot)))
    apply_migrations(conn)
    data = b"artifact-bytes"
    # Force MediaStore path to leave a wrong-sized file so fallback write_bytes runs.
    with patch(
        "sevn.gateway.media.media_store.MediaStore.persist_attachment_descriptors",
        new=AsyncMock(return_value=None),
    ):
        # Pre-create a wrong-sized file at the expected path.
        target = tmp_path / "channel_files" / "sess-p" / "out.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"short")
        rel = await _persist_bytes(
            conn=conn,
            content_root=tmp_path,
            session_id="sess-p",
            filename="out.bin",
            data=data,
        )
    written = tmp_path / rel
    assert written.read_bytes() == data
