"""Context assembly: fresh tail plus newest-first summaries (`specs/15-memory-lcm.md` §4).

Module: sevn.lcm.assembler
Depends: sqlite3

Exports:
    AssembledContext — model-facing transcript envelope.
    LcmAssembler — §2.4 builder.

Examples:
    >>> from sevn.lcm.assembler import LcmAssembler
    >>> LcmAssembler.__name__
    'LcmAssembler'
"""

from __future__ import annotations

import sqlite3  # noqa: TC003 — doctests call ``sqlite3.connect``
from dataclasses import dataclass

_SUMMARY_WRAP_FMT = "<summary><content>{body}</content></summary>"


def _token_units(text: str, explicit: int | None) -> int:
    """Return token estimate using persisted count or rough char heuristic.

        Args:
    text (str): UTF-8 text.
    explicit (int | None): Optional ``lcm_*`` persisted ``token_count``.

        Returns:
            int: At least ``1``.

        Examples:
            >>> _token_units("abcd", None)
            1
    """
    if explicit is not None and explicit > 0:
        return int(explicit)
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class AssembledContext:
    """Messages assembled for the active model within a budget (`specs/15-memory-lcm.md` §2)."""

    messages: list[dict[str, str]]
    token_budget: int
    tokens_used: int
    fresh_tail_n: int
    summary_nodes: int


class LcmAssembler:
    """Build chat-shaped messages: system + summaries + fresh tail."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Bind SQLite connection used for reads.

                Args:
        conn (sqlite3.Connection): Workspace DB (``sevn.db``).

                Examples:
                    >>> True
                    True
        """
        self._conn = conn

    async def assemble(
        self,
        *,
        conversation_id: int,
        token_budget: int,
        fresh_tail_count: int,
        system_prompt: str | None,
    ) -> AssembledContext:
        """Always include ``system_prompt`` + fresh tail; fill remainder newest-first summaries.

                Args:
        conversation_id (int): ``lcm_conversations.id``.
        token_budget (int): Maximum approximate tokens for assembled body (excluding optional system).
        fresh_tail_count (int): Count of trailing visible ``sent`` messages to force verbatim.
        system_prompt (str | None): Optional system instruction prepended when non-empty.

                Returns:
                    AssembledContext: Ordered chat messages plus telemetry integers.

                Examples:
                    >>> import asyncio, sqlite3
                    >>> asyncio.run(LcmAssembler(sqlite3.connect(":memory:")).assemble(
                    ...     conversation_id=1, token_budget=100, fresh_tail_count=1,
                    ...     system_prompt=None))
                    Traceback (most recent call last):
                    ...
                    sqlite3.OperationalError: ...
        """
        messages: list[dict[str, str]] = []
        used = 0

        system_cost = 0
        if system_prompt:
            system_cost = _token_units(system_prompt, None)

        tail_rows = self._conn.execute(
            """
            SELECT role, content, token_count
            FROM lcm_messages
            WHERE conversation_id = ?
              AND kind = 'message'
              AND visible_to_llm = 1
              AND status = 'sent'
            ORDER BY seq DESC
            LIMIT ?
            """,
            (conversation_id, fresh_tail_count),
        ).fetchall()
        tail_rows = list(reversed(tail_rows))
        tail_parts: list[tuple[str, str, int | None]] = [(r[0], r[1], r[2]) for r in tail_rows]

        avail_after_system = max(0, token_budget - system_cost)
        full_tail_entries = self._tail_slice_entries(tail_parts)
        tail_costs = sum(t[2] for t in full_tail_entries)
        if tail_costs > avail_after_system:
            tail_entries = self._shrink_tail_to_budget(tail_parts, avail_after_system)
            tail_costs = sum(t[2] for t in tail_entries)
        else:
            tail_entries = full_tail_entries

        summary_budget = max(0, avail_after_system - tail_costs)

        summary_rows = self._conn.execute(
            """
            SELECT summary_id, content, token_count
            FROM lcm_summaries
            WHERE conversation_id = ?
              AND summary_kind = 'compaction'
              AND subsumed_by IS NULL
            ORDER BY created_at DESC
            """,
            (conversation_id,),
        ).fetchall()

        planned_summaries: list[tuple[str, str, int]] = []
        summary_nodes = 0
        run_sum = 0
        for sid, body, tok in summary_rows:
            wrapped = _SUMMARY_WRAP_FMT.format(body=body)
            cost = _token_units(wrapped, int(tok) if tok else None)
            if run_sum + cost > summary_budget:
                continue
            planned_summaries.append((sid, wrapped, cost))
            run_sum += cost
            summary_nodes += 1

        if system_prompt and system_cost <= token_budget:
            messages.append({"role": "system", "content": system_prompt})
            used += system_cost

        for _, wrapped, cost in planned_summaries:
            messages.append({"role": "system", "content": wrapped})
            used += cost

        fresh_tail_n = 0
        for role, content, c in tail_entries:
            messages.append({"role": role, "content": content})
            used += c
            fresh_tail_n += 1

        return AssembledContext(
            messages=messages,
            token_budget=token_budget,
            tokens_used=used,
            fresh_tail_n=fresh_tail_n,
            summary_nodes=summary_nodes,
        )

    def _tail_slice_entries(
        self,
        tail_parts: list[tuple[str, str, int | None]],
    ) -> list[tuple[str, str, int]]:
        """Materialise tail rows with computed costs.

        Args:
            tail_parts (list[tuple[str, str, int | None]]): Tail rows as
                ``(role, content, persisted_token_count_or_None)``.

        Returns:
            list[tuple[str, str, int]]: Same rows with the third element replaced by
                the effective token cost (persisted value or char-based fallback).

        Examples:
            >>> import sqlite3
            >>> LcmAssembler(sqlite3.connect(":memory:"))._tail_slice_entries([])
            []
        """
        return [(r, c, _token_units(c, int(tc) if tc else None)) for r, c, tc in tail_parts]

    def _shrink_tail_to_budget(
        self,
        tail_parts: list[tuple[str, str, int | None]],
        budget: int,
    ) -> list[tuple[str, str, int]]:
        """Prefer dropping oldest tail rows until the tail fits ``budget``.

                Args:
        tail_parts (list): Ordered tail rows (oldest first).
        budget (int): Token budget for the tail slice only.

                Returns:
                    list[tuple[str, str, int]]: Possibly shortened tail with costs.

                Examples:
                    >>> import sqlite3
                    >>> LcmAssembler(sqlite3.connect(":memory:"))._shrink_tail_to_budget([], 0)
                    []
        """
        if budget <= 0 or not tail_parts:
            return []
        for drop in range(len(tail_parts)):
            slice_rows = tail_parts[drop:]
            total = sum(_token_units(c, int(tc) if tc else None) for _, c, tc in slice_rows)
            if total <= budget:
                return [(r, c, _token_units(c, int(tc) if tc else None)) for r, c, tc in slice_rows]
        return []
