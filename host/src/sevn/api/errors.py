"""Map domain errors onto protocol errors."""

from __future__ import annotations

from typing import NoReturn, assert_never

from sevn.contracts.errors import ProtocolError
from sevn.domain.errors import DomainError


def raise_protocol(exc: DomainError) -> NoReturn:
    code = exc.code
    if (
        code == "not_found"
        or code == "invalid_params"
        or code == "pending_resolved"
        or code == "pinned_budget"
        or code == "memory_locked"
        or code == "revision_conflict"
    ):
        raise ProtocolError(code, exc.message) from exc
    assert_never(code)
