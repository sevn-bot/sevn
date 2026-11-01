"""Method registry and dispatch (D11, D14, D7)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

from pydantic import BaseModel, ValidationError

from sevn.contracts.errors import ErrorBody, JsonObject, JsonValue, ProtocolError
from sevn.contracts.frames import Req, Res
from sevn.contracts.methods import MethodSpec
from sevn.log import logger
from sevn.protocol.errors import Scope, scope_allows
from sevn.protocol.hub import Hub

type Handler = Callable[["Ctx", BaseModel], Awaitable[BaseModel]]


class Ctx(Protocol):
    scope: Scope
    hub: Hub

    def deliver(self, frame: str) -> None: ...

    def hold_live(self) -> None: ...

    def replay(self, frame: str) -> None: ...

    def release_live(self, high_water: int) -> None: ...


type StoredResult = Callable[[dict[str, object]], dict[str, object]]


class BoundMethod:
    spec: MethodSpec
    handler: Handler
    scope: Scope | None
    stored: StoredResult | None

    def __init__(
        self,
        spec: MethodSpec,
        handler: Handler,
        scope: Scope | None,
        stored: StoredResult | None = None,
    ) -> None:
        self.spec = spec
        self.handler = handler
        self.scope = scope
        self.stored = stored


_registry: dict[str, BoundMethod] = {}


def method[P: BaseModel, R: BaseModel](
    name: str,
    *,
    params: type[P],
    result: type[R],
    mutating: bool,
    scope: Scope | None = None,
    stored: StoredResult | None = None,
) -> Callable[[Callable[[Ctx, P], Awaitable[R]]], Callable[[Ctx, P], Awaitable[R]]]:
    """Register ``fn`` as the handler for ``name``.

    ``stored`` maps a mutating method's result to what the op log keeps for
    a replay. Use it for a value that must be shown once and never stored.
    """

    def decorate(fn: Callable[[Ctx, P], Awaitable[R]]) -> Callable[[Ctx, P], Awaitable[R]]:
        _registry[name] = BoundMethod(
            MethodSpec(name=name, params=params, result=result, mutating=mutating),
            cast(Handler, fn),
            scope,
            stored,
        )
        return fn

    return decorate


async def dispatch(ctx: Ctx, req: Req) -> Res:
    bound = _registry.get(req.m)
    if bound is None:
        return error_res(req.id, ProtocolError("method_not_found", f"method not found: {req.m}"))
    if not scope_allows(ctx.scope, bound.scope):
        return error_res(req.id, ProtocolError("forbidden", "forbidden"))
    try:
        params = bound.spec.params.model_validate(req.p)
    except ValidationError as exc:
        return error_res(
            req.id,
            ProtocolError("invalid_params", "invalid params", _invalid_params(exc)),
        )
    try:
        if bound.spec.mutating:
            op_id = _op_id(params)
            if op_id is None:
                return error_res(req.id, ProtocolError("op_id_required", "op_id required"))
            body = await ctx.hub.claim_op(
                op_id,
                bound.spec.name,
                _params_hash(params),
                lambda: _invoke(bound, ctx, params),
                stored=bound.stored,
            )
            return Res(t="res", id=req.id, r=_object(body))
        return Res(t="res", id=req.id, r=await _invoke(bound, ctx, params))
    except ProtocolError as exc:
        return error_res(req.id, exc)
    except Exception:  # noqa: BLE001 — unknown failures become `internal` on the wire
        logger.exception("method dispatch failed: {}", bound.spec.name)
        return error_res(req.id, ProtocolError("internal", "internal error"))


def error_res(req_id: str, exc: ProtocolError) -> Res:
    return Res(
        t="res",
        id=req_id,
        e=ErrorBody(code=exc.code, message=exc.message, data=exc.data),
    )


async def _invoke(bound: BoundMethod, ctx: Ctx, params: BaseModel) -> JsonObject:
    produced = await bound.handler(ctx, params)
    dumped = produced.model_dump(mode="json")
    return _object(dumped)


def _params_hash(params: BaseModel) -> str:
    raw = params.model_dump(mode="json")
    blob = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _op_id(params: BaseModel) -> str | None:
    value = getattr(params, "op_id", None)
    if isinstance(value, str) and value != "":
        return value
    return None


def _invalid_params(exc: ValidationError) -> JsonObject:
    errors: list[JsonValue] = []
    for err in exc.errors():
        loc: list[JsonValue] = list(err["loc"])
        errors.append({"loc": loc, "msg": str(err["msg"])})
    return {"errors": errors}


def _object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise ProtocolError("internal", "method result must be an object")
    return cast(JsonObject, value)
