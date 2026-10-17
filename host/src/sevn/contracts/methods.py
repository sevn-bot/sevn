"""Method registry types for the first host methods (D13)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict


class SystemInfoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemInfoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: str
    version: str
    proto: int
    caps: list[str]
    host_pubkey_fp: str


class SystemPingParams(BaseModel):
    """`op_id` is optional here; dispatch requires it when `mutating` is set (D11)."""

    model_config = ConfigDict(extra="forbid")

    note: str
    op_id: str | None = None


class SystemPingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int


class SyncSinceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int


class SyncSinceResult(BaseModel):
    """Cursor after durable events have been replayed as `evt` frames."""

    model_config = ConfigDict(extra="forbid")

    host_seq: int


@dataclass(frozen=True, slots=True)
class MethodSpec:
    name: str
    params: type[BaseModel]
    result: type[BaseModel]
    mutating: bool


def _spec(
    name: str,
    params: type[BaseModel],
    result: type[BaseModel],
    *,
    mutating: bool,
) -> MethodSpec:
    return MethodSpec(name=name, params=params, result=result, mutating=mutating)


METHODS: dict[str, MethodSpec] = {
    spec.name: spec
    for spec in (
        _spec("system.info", SystemInfoParams, SystemInfoResult, mutating=False),
        _spec("system.ping", SystemPingParams, SystemPingResult, mutating=True),
        _spec("sync.since", SyncSinceParams, SyncSinceResult, mutating=False),
    )
}
