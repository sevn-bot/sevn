"""Domain failures the API maps onto protocol errors."""

from __future__ import annotations

from typing import Literal

type DomainCode = Literal[
    "not_found",
    "invalid_params",
    "pending_resolved",
    "pinned_budget",
    "memory_locked",
    "revision_conflict",
]


class DomainError(Exception):
    """A refused bot or agent operation with a stable code."""

    code: DomainCode
    message: str
    data: dict[str, object] | None

    def __init__(
        self,
        code: DomainCode,
        message: str,
        data: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)
