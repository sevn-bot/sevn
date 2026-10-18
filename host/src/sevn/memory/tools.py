"""Memory tools registered for every bot (D9, D12)."""

from __future__ import annotations

from sevn.domain.errors import DomainError
from sevn.memory.store import MemoryStore
from sevn.tools.registry import TurnDeps, register_toolset


def memory_toolset(deps: TurnDeps) -> dict[str, object]:
    """Tools bound to one turn. Writes stay staged until that turn commits."""
    store = MemoryStore()

    async def save(text: str, tier: str = "recall") -> str:
        """Save a memory for this bot. ``tier`` is pinned or recall."""
        record = await store.save(
            deps.bot_id,
            text,
            tier=tier,
            origin="bot",
            turn_id=deps.turn_id,
        )
        return record.id

    async def search(query: str, limit: int = 5) -> str:
        """Find committed memories. ``limit`` caps the number of hits."""
        found = await store.search(deps.bot_id, query, limit=limit)
        return "\n".join(item.text for item in found)

    async def forget(id: str) -> str:
        """Forget a memory at the end of this turn."""
        await store.stage_delete(deps.bot_id, id, turn_id=deps.turn_id)
        return id

    async def pin(id: str, revision: int) -> str:
        """Pin a memory the bot itself saved. User memories stay locked."""
        try:
            await store.stage_tier(
                id,
                "pinned",
                actor="bot",
                revision=revision,
                turn_id=deps.turn_id,
            )
        except DomainError as exc:
            return exc.code
        return id

    return {
        "memory.save": save,
        "memory.search": search,
        "memory.forget": forget,
        "memory.pin": pin,
    }


register_toolset(
    "memory",
    memory_toolset,
    {"memory.save", "memory.search"},
    deferred={"memory.forget", "memory.pin"},
)
