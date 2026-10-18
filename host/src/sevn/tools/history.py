"""Search and read UI messages that stay in the store after compaction (D16)."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from sevn.domain.errors import DomainError
from sevn.domain.session import open_session
from sevn.store.models import Message
from sevn.tools.registry import TurnDeps, register_toolset

_LIMIT = 20
_SEARCH = text(
    "SELECT messages.id AS message_id, messages_fts.text AS body "
    "FROM messages_fts "
    "JOIN messages ON messages.id = messages_fts.id "
    "JOIN threads ON threads.id = messages.thread_id "
    "WHERE threads.bot_id = :bot_id AND messages_fts MATCH :query "
    "ORDER BY messages.created_at, messages.id "
    "LIMIT :limit"
)


class HistoryHit(BaseModel):
    """One UI message matched by ``history.search``."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    text: str


class HistoryPage(BaseModel):
    """One UI message and the cursor of the next message in its thread."""

    model_config = ConfigDict(extra="forbid")

    text: str
    cursor: str


async def search(bot_id: str, query: str, *, limit: int = _LIMIT) -> list[HistoryHit]:
    """Committed UI messages for ``bot_id`` whose text matches ``query``."""
    match = _match_query(query)
    if match is None:
        return []
    try:
        async with open_session() as session:
            result = await session.execute(
                _SEARCH,
                {"bot_id": bot_id, "query": match, "limit": limit},
            )
            hits: list[HistoryHit] = []
            for row in result.mappings():
                hits.append(
                    HistoryHit(
                        message_id=_text_cell(row["message_id"]),
                        text=_text_cell(row["body"]),
                    )
                )
            return hits
    except OperationalError:
        return []


async def read(
    *,
    message_id: str | None = None,
    cursor: str | None = None,
) -> HistoryPage:
    """Read one UI message by id, or the message a previous cursor names."""
    target = message_id if message_id else cursor
    if target is None or target == "":
        raise DomainError("invalid_params", "message id or cursor is required")
    async with open_session() as session:
        row = await session.get(Message, target)
        if row is None:
            raise DomainError("not_found", "message not found")
        nxt = await _next_message(session, row)
        page_cursor = "" if nxt is None else nxt.id
        return HistoryPage(text=_parts_text(row.parts), cursor=page_cursor)


def history_toolset(deps: TurnDeps) -> dict[str, object]:
    """Deferred history tools bound to one bot."""

    async def search_history(query: str, limit: int = _LIMIT) -> str:
        """Search this bot's stored UI messages."""
        found = await search(deps.bot_id, query, limit=limit)
        return "\n".join(f"{hit.message_id}\t{hit.text}" for hit in found)

    async def read_history(message_id: str = "", cursor: str = "") -> str:
        """Read one stored UI message, then the next one when ``cursor`` is set."""
        page = await read(
            message_id=None if message_id == "" else message_id,
            cursor=None if cursor == "" else cursor,
        )
        if page.cursor == "":
            return page.text
        return f"{page.text}\ncursor={page.cursor}"

    return {"history.search": search_history, "history.read": read_history}


def _match_query(query: str) -> str | None:
    stripped = query.strip()
    if stripped == "":
        return None
    return '"' + stripped.replace('"', '""') + '"'


def _parts_text(parts: list[object]) -> str:
    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text_value = cast("dict[object, object]", part).get("text")
        if isinstance(text_value, str):
            chunks.append(text_value)
    return "\n".join(chunks)


async def _next_message(session: AsyncSession, row: Message) -> Message | None:
    rows = list(await session.scalars(select(Message).where(Message.thread_id == row.thread_id)))
    rows.sort(key=lambda item: (item.created_at, item.id))
    for index, item in enumerate(rows):
        if item.id != row.id:
            continue
        if index + 1 < len(rows):
            return rows[index + 1]
        return None
    return None


def _text_cell(value: object) -> str:
    if isinstance(value, str):
        return value
    raise DomainError("invalid_params", "message row is incomplete")


register_toolset(
    "history",
    history_toolset,
    set(),
    deferred={"history.search", "history.read"},
)
