"""Pre-compaction flush: ``MemoryWrites`` validation and retry-once policy.

Module: sevn.lcm.flush
Depends: pydantic

Exports:
    Classes:
        MemoryWrite — single structured workspace write.
        MemoryWrites — batch envelope (`specs/15-memory-lcm.md` §2.2).
        FlushDecodeOutcome — decode + retry-once outcome envelope.
    Functions:
        is_allowlisted_relative_path — normative path gate (§6).
        validate_memory_writes — reject batches with any bad path.
        run_flush_decode_with_retry_once — parse LLM JSON + strict retry (§2.2 batch policy).

Examples:
    >>> from sevn.lcm.flush import MemoryWrites, validate_memory_writes
    >>> m = MemoryWrites.model_validate({"writes": [
    ...     {"path": "MEMORY.md", "operation": "append", "content": "x"}
    ... ]})
    >>> validate_memory_writes(m, utc_flush_day=(2026, 5, 12)) is None
    True
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable  # noqa: TC003
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

_MemoryDayMdRe: Final[re.Pattern[str]] = re.compile(r"^memory/\d{4}-\d{2}-\d{2}\.md$")


MemoryOperation = Literal["append", "replace"]


class MemoryWrite(BaseModel):
    """One structured write to an allowlisted workspace-relative path."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    operation: MemoryOperation
    content: str


class MemoryWrites(BaseModel):
    """Structured flush batch (`specs/15-memory-lcm.md` §2.2)."""

    model_config = ConfigDict(extra="forbid")

    writes: list[MemoryWrite] = Field(default_factory=list)


def _normalize_rel_posix(path: str) -> str:
    """Strip ``./`` and coerce separators to POSIX-style forward slashes.

        Args:
    path (str): Relative path string from model output.

        Returns:
            str: Normalized key for comparison.

        Examples:
            >>> _normalize_rel_posix("./MEMORY.md")
            'MEMORY.md'
    """
    s = path.strip().replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def is_allowlisted_relative_path(
    path: str,
    *,
    utc_flush_day: tuple[int, int, int],
) -> bool:
    """Return True when ``path`` matches §2.2 allowlist for ``utc_flush_day``.

        Args:
    path (str): Workspace-relative path (normalized internally).
    utc_flush_day (tuple[int, int, int]): ``(year, month, day)`` UTC calendar day.

        Returns:
            bool: Allowlisted relative path only — ``MEMORY.md``, ``USER.md``,
                or ``memory/YYYY-MM-DD.md`` matching ``utc_flush_day``.

        Examples:
            >>> is_allowlisted_relative_path(
            ...     "memory/2026-05-12.md", utc_flush_day=(2026, 5, 12))
            True
            >>> is_allowlisted_relative_path("secrets.env", utc_flush_day=(1,1,1))
            False
    """
    norm = _normalize_rel_posix(path)
    if norm in ("MEMORY.md", "USER.md"):
        return True
    y, m, d = utc_flush_day
    expected = f"memory/{y:04d}-{m:02d}-{d:02d}.md"
    return norm == expected and bool(_MemoryDayMdRe.match(norm))


def validate_memory_writes(batch: MemoryWrites, *, utc_flush_day: tuple[int, int, int]) -> None:
    """Raise ``ValueError`` when any write path is outside §2.2 allowlist.

        Args:
    batch (MemoryWrites): Parsed structured batch.
    utc_flush_day (tuple[int, int, int]): Expected UTC calendar day for dated paths.

        Raises:
            ValueError: When any path fails allowlist.

        Examples:
            >>> validate_memory_writes(MemoryWrites(writes=[]), utc_flush_day=(1,1,1))
    """
    for w in batch.writes:
        if not is_allowlisted_relative_path(w.path, utc_flush_day=utc_flush_day):
            msg = f"LCM flush path not allowlisted: {w.path!r}"
            raise ValueError(msg)


@dataclass(frozen=True)
class FlushDecodeOutcome:
    """Result of decode + optional strict retry (`specs/15-memory-lcm.md` §2.2)."""

    batch: MemoryWrites | None
    outcome: Literal["applied", "rejected"]
    retried: bool
    writes_n: int


async def run_flush_decode_with_retry_once(
    *,
    llm_call: Callable[[str], Awaitable[str]],
    initial_prompt_suffix: str,
    strict_retry_prompt: str,
    utc_flush_day: tuple[int, int, int],
) -> FlushDecodeOutcome:
    """Decode JSON into ``MemoryWrites``; retry once with stricter preamble on failure.

        Args:
    llm_call (Callable): Async function returning raw JSON text from the small model.
    initial_prompt_suffix (str): First-turn user/system adjunct text.
    strict_retry_prompt (str): Second-turn text listing allowed paths only.
    utc_flush_day (tuple[int, int, int]): Calendar gate for ``memory/YYYY-MM-DD.md``.

        Returns:
            FlushDecodeOutcome: Parsed batch or rejection after retry; ``writes_n`` counts rows.

        Examples:
            >>> import asyncio
            >>> async def _demo():
            ...     async def ok(_: str) -> str:
            ...         return '{"writes":[]}'
            ...     return await run_flush_decode_with_retry_once(
            ...         llm_call=ok,
            ...         initial_prompt_suffix="",
            ...         strict_retry_prompt="",
            ...         utc_flush_day=(1, 1, 1),
            ...     )
            >>> asyncio.run(_demo()).outcome
            'applied'
    """
    raw1 = await llm_call(initial_prompt_suffix)
    batch1 = _try_parse_and_validate(raw1, utc_flush_day=utc_flush_day)
    if batch1 is not None:
        return FlushDecodeOutcome(
            batch=batch1,
            outcome="applied",
            retried=False,
            writes_n=len(batch1.writes),
        )
    raw2 = await llm_call(strict_retry_prompt)
    batch2 = _try_parse_and_validate(raw2, utc_flush_day=utc_flush_day)
    if batch2 is not None:
        return FlushDecodeOutcome(
            batch=batch2,
            outcome="applied",
            retried=True,
            writes_n=len(batch2.writes),
        )
    return FlushDecodeOutcome(batch=None, outcome="rejected", retried=True, writes_n=0)


def _try_parse_and_validate(
    raw: str, *, utc_flush_day: tuple[int, int, int]
) -> MemoryWrites | None:
    """Parse JSON object and validate allowlist; return ``None`` on any failure.

        Args:
    raw (str): Model output (must be a single JSON object).
    utc_flush_day (tuple[int, int, int]): Allowlist calendar gate.

        Returns:
            MemoryWrites | None: Valid batch or ``None``.

        Examples:
            >>> _try_parse_and_validate('{"writes":[]}', utc_flush_day=(1,1,1)).writes
            []
    """
    try:
        obj = json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    try:
        batch = MemoryWrites.model_validate(obj)
        validate_memory_writes(batch, utc_flush_day=utc_flush_day)
    except ValueError:
        return None
    return batch
