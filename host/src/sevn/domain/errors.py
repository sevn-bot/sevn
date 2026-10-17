"""Domain failures the API maps onto protocol errors."""

from __future__ import annotations

from typing import Literal

type DomainCode = Literal["not_found", "invalid_params"]


class DomainError(Exception):
    """A refused bot or agent operation with a stable code."""

    code: DomainCode
    message: str

    def __init__(self, code: DomainCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
