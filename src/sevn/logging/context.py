"""Per-inbound-message correlation id propagated through every log record.

Module: sevn.logging.context
Depends: contextvars

Exports:
    set_message_id — bind the unique message id to the current async context.
    get_message_id — read the bound id (returns ``"-"`` when unset).
    inject_message_id — loguru patcher that copies the id into ``record["extra"]``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from loguru import Record

_MESSAGE_ID_CV: ContextVar[str] = ContextVar("sevn_message_id", default="-")


def set_message_id(unique_message_id: str) -> None:
    """Bind ``unique_message_id`` to the current async context.

    ContextVars are per-task in asyncio, so the value is visible only inside
    the same task tree. The token returned by ``ContextVar.set`` is intentionally
    discarded: gateway inbound handlers are the entrypoint for a fresh task and
    rely on the task ending to clear the value.

    Args:
        unique_message_id (str): Labelled per-inbound id built at the gateway.

    Examples:
        >>> set_message_id("telegram:user=1:session=ab:msg=cd")
        >>> get_message_id().startswith("telegram:")
        True
    """
    _MESSAGE_ID_CV.set(unique_message_id)


def get_message_id() -> str:
    """Return the message id bound to the current async context.

    Returns:
        str: The bound id, or ``"-"`` when nothing is bound in this task.

    Examples:
        >>> isinstance(get_message_id(), str)
        True
    """
    return _MESSAGE_ID_CV.get()


def inject_message_id(record: Record) -> None:
    """Fold the bound ``message_id`` into ``record["extra"]`` for formatting.

    Loguru calls this patcher on every log record (registered via
    ``logger.configure(patcher=...)`` in ``sevn.logging.setup``). It pulls
    the per-task contextvar so downstream code does not need to thread an
    id through function signatures.

    Args:
        record (Record): Loguru record being formatted (mutated in-place).

    Examples:
        >>> rec: dict[str, Any] = {"extra": {}}
        >>> inject_message_id(cast("Record", rec))
        >>> "message_id" in rec["extra"]
        True
    """
    extra = cast("dict[str, Any]", record.setdefault("extra", {}))
    if not extra.get("message_id") or extra.get("message_id") == "-":
        extra["message_id"] = _MESSAGE_ID_CV.get()


__all__ = [
    "get_message_id",
    "inject_message_id",
    "set_message_id",
]
