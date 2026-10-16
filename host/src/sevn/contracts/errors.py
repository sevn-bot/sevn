"""Protocol error codes and the wire error body (D14)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

type ErrorCode = Literal[
    "protocol_error",
    "unauthorized",
    "method_not_found",
    "invalid_params",
    "op_id_required",
    "resync_required",
    "internal",
]

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]


class ProtocolError(Exception):
    """A protocol failure with a stable code, message, and optional data."""

    def __init__(self, code: ErrorCode, message: str, data: JsonObject | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)

    def dump(self) -> dict[str, object]:
        body: dict[str, object] = {"code": self.code, "message": self.message}
        if self.data is not None:
            body["data"] = self.data
        return body


class ErrorBody(BaseModel):
    """`res.e` object: code, message, and optional data."""

    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    data: JsonObject | None = None
