"""Tests for LCM flush validation (`specs/15-memory-lcm.md` §2.2)."""

from __future__ import annotations

import pytest

from sevn.lcm.flush import (
    MemoryWrite,
    MemoryWrites,
    run_flush_decode_with_retry_once,
    validate_memory_writes,
)


def test_allowlist_accepts_memory_and_dated_md() -> None:
    batch = MemoryWrites(
        writes=[
            MemoryWrite(path="MEMORY.md", operation="append", content="a"),
            MemoryWrite(path="memory/2026-05-12.md", operation="replace", content="b"),
        ],
    )
    validate_memory_writes(batch, utc_flush_day=(2026, 5, 12))


def test_allowlist_rejects_unknown_path() -> None:
    batch = MemoryWrites(writes=[MemoryWrite(path="evil.md", operation="append", content="x")])
    with pytest.raises(ValueError, match="not allowlisted"):
        validate_memory_writes(batch, utc_flush_day=(2026, 5, 12))


@pytest.mark.asyncio
async def test_flush_retry_once_applies_second_round() -> None:
    calls: list[str] = []

    async def llm(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return '{"writes":[{"path":"x.md","operation":"append","content":"nope"}]}'
        return '{"writes":[{"path":"MEMORY.md","operation":"append","content":"ok"}]}'

    out = await run_flush_decode_with_retry_once(
        llm_call=llm,
        initial_prompt_suffix="a",
        strict_retry_prompt="b",
        utc_flush_day=(2026, 1, 1),
    )
    assert out.retried is True
    assert out.outcome == "applied"
    assert out.batch is not None
    assert len(out.batch.writes) == 1
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_flush_retry_once_rejects_after_two_failures() -> None:
    async def llm(_: str) -> str:
        return '{"writes":[{"path":"./secrets.env","operation":"append","content":"x"}]}'

    out = await run_flush_decode_with_retry_once(
        llm_call=llm,
        initial_prompt_suffix="a",
        strict_retry_prompt="b",
        utc_flush_day=(2026, 1, 1),
    )
    assert out.outcome == "rejected"
    assert out.batch is None
