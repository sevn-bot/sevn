"""Map domain errors onto protocol errors."""

from __future__ import annotations

from typing import NoReturn, assert_never

from sevn.contracts.errors import JsonObject, ProtocolError
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
        or code == "path_outside_workspace"
        or code == "path_locked"
    ):
        raise ProtocolError(code, exc.message, _json_data(exc.data)) from exc
    assert_never(code)


def _json_data(raw: dict[str, object] | None) -> JsonObject | None:
    if raw is None:
        return None
    body: JsonObject = {}
    for key, value in raw.items():
        if isinstance(value, str):
            body[key] = value
        elif isinstance(value, bool):
            body[key] = value
        elif isinstance(value, int):
            body[key] = value
        elif isinstance(value, float):
            body[key] = value
        elif value is None:
            body[key] = None
        else:
            body[key] = str(value)
    return body
