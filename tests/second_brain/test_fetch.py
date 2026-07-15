"""Tests for URL→raw fetch policy."""

from __future__ import annotations

import httpx
import pytest

from sevn.config.workspace_config import SecondBrainFetchConfig
from sevn.second_brain.fetch import SecondBrainFetchError, fetch_url_to_raw


@pytest.mark.asyncio
async def test_fetch_rejects_non_https(tmp_path) -> None:
    cfg = SecondBrainFetchConfig(allow_domains=["example.com"])
    with pytest.raises(SecondBrainFetchError, match="HTTPS"):
        await fetch_url_to_raw(
            url="http://example.com/x",
            scope_root=tmp_path,
            fetch_cfg=cfg,
        )


@pytest.mark.asyncio
async def test_fetch_rejects_disallowed_host(tmp_path) -> None:
    cfg = SecondBrainFetchConfig(allow_domains=["allow.ed"])
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok"),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(SecondBrainFetchError, match="allow_domains"):
            await fetch_url_to_raw(
                url="https://evil.test/",
                scope_root=tmp_path,
                fetch_cfg=cfg,
                client=client,
            )


@pytest.mark.asyncio
async def test_fetch_writes_raw(tmp_path) -> None:
    cfg = SecondBrainFetchConfig(
        allow_domains=["example.com"], max_response_mib=1, timeout_seconds=5
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=b"hello"
        ),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        out = await fetch_url_to_raw(
            url="https://example.com/page",
            scope_root=tmp_path,
            fetch_cfg=cfg,
            client=client,
        )
    assert out["bytes_written"] == 5
    raw = tmp_path / "raw"
    assert raw.is_dir()
    assert any(raw.iterdir())


@pytest.mark.asyncio
async def test_fetch_writes_pdf_raw(tmp_path) -> None:
    cfg = SecondBrainFetchConfig(allow_domains=["example.com"], max_response_mib=1)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.4 minimal",
        ),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        out = await fetch_url_to_raw(
            url="https://example.com/paper.pdf",
            scope_root=tmp_path,
            fetch_cfg=cfg,
            client=client,
        )
    assert out["raw_relpath"].endswith(".pdf")
    assert (tmp_path / "raw" / str(out["raw_relpath"])).read_bytes().startswith(b"%PDF")


@pytest.mark.asyncio
async def test_fetch_writes_para_sources(tmp_path) -> None:
    from sevn.config.workspace_config import SecondBrainWorkspaceConfig

    vault = tmp_path / "obsidian" / "alex_AI"
    vault.mkdir(parents=True)
    cfg = SecondBrainFetchConfig(allow_domains=["example.com"], max_response_mib=1)
    sb_cfg = SecondBrainWorkspaceConfig(
        layout="para",
        paths={"vault": "obsidian/alex_AI"},
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=b"hello"
        ),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        out = await fetch_url_to_raw(
            url="https://example.com/page",
            scope_root=vault,
            fetch_cfg=cfg,
            client=client,
            workspace_root=tmp_path,
            sb_cfg=sb_cfg,
            scope="owner",
        )
    sources = vault / "30_Resources" / "_sources"
    assert sources.is_dir()
    assert (sources / str(out["raw_relpath"])).is_file()
