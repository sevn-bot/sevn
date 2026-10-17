"""Protocol frames (spec §3.0.1, D5)."""

from __future__ import annotations

import json
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from sevn.contracts.errors import ErrorBody, JsonObject, ProtocolError

# `auth` is two frames that share `t`. A callable tag keeps both in one union.
_Proto = Annotated[list[int], Field(min_length=2, max_length=2)]


class FrameError(ProtocolError):
    """A text frame is not a known, valid frame."""

    def __init__(self, message: str) -> None:
        super().__init__("protocol_error", message)


class _Frame(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Hello(_Frame):
    t: Literal["hello"]
    proto: _Proto
    client: str
    device: str
    last_seq: int
    caps: list[str]


class Challenge(_Frame):
    t: Literal["challenge"]
    nonce: str
    host: str
    host_sig: str


class AuthToken(_Frame):
    t: Literal["auth"]
    token: str


class AuthDevice(_Frame):
    t: Literal["auth"]
    device_sig: str


class Welcome(_Frame):
    t: Literal["welcome"]
    proto: int
    host_seq: int
    caps: list[str]


class Req(_Frame):
    t: Literal["req"]
    id: str
    m: str
    p: JsonObject


class Res(_Frame):
    t: Literal["res"]
    id: str
    r: JsonObject | None = None
    e: ErrorBody | None = None

    @model_validator(mode="after")
    def _exactly_one_body(self) -> Res:
        if (self.r is None) == (self.e is None):
            raise ValueError("res requires exactly one of r or e")
        return self


class Evt(_Frame):
    t: Literal["evt"]
    s: int
    k: str
    d: JsonObject


class Tick(_Frame):
    t: Literal["tick"]
    k: str
    d: JsonObject


def _frame_tag(value: object) -> str:
    if isinstance(value, AuthToken):
        return "auth_token"
    if isinstance(value, AuthDevice):
        return "auth_device"
    if isinstance(value, BaseModel):
        tag = getattr(value, "t", None)
        return tag if isinstance(tag, str) else ""
    fields = _object_dict(value)
    if fields is None:
        return ""
    raw = fields.get("t")
    tag = raw if isinstance(raw, str) else ""
    if tag != "auth":
        return tag
    if "device_sig" in fields and "token" not in fields:
        return "auth_device"
    return "auth_token"


def _object_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast("dict[str, object]", value)


Frame = Annotated[
    Annotated[Hello, Tag("hello")]
    | Annotated[Challenge, Tag("challenge")]
    | Annotated[AuthToken, Tag("auth_token")]
    | Annotated[AuthDevice, Tag("auth_device")]
    | Annotated[Welcome, Tag("welcome")]
    | Annotated[Req, Tag("req")]
    | Annotated[Res, Tag("res")]
    | Annotated[Evt, Tag("evt")]
    | Annotated[Tick, Tag("tick")],
    Discriminator(_frame_tag),
]

FRAME_MODELS: tuple[type[BaseModel], ...] = (
    Hello,
    Challenge,
    AuthToken,
    AuthDevice,
    Welcome,
    Req,
    Res,
    Evt,
    Tick,
)

_ADAPTER: TypeAdapter[Frame] = TypeAdapter(Frame)


def parse(text: str) -> Frame:
    try:
        return _ADAPTER.validate_json(text)
    except ValidationError as exc:
        raise FrameError(_validation_message(exc)) from exc


def dump(frame: Frame) -> str:
    data = frame.model_dump(mode="json", exclude_none=True)
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(item) for item in err["loc"])
        msg = str(err["msg"])
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "invalid frame: " + "; ".join(parts)
