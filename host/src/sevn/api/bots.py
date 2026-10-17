"""Bot protocol methods (D9, D10)."""

from __future__ import annotations

from sevn.api.errors import raise_protocol
from sevn.contracts.errors import JsonObject, JsonValue, ProtocolError
from sevn.contracts.kinds import AccessName, ApprovalPolicy, RuntimeName
from sevn.contracts.methods import (
    BotsCreateParams,
    BotsDeleteParams,
    BotsDeleteResult,
    BotsGetParams,
    BotsListParams,
    BotsListResult,
    BotsUpdateParams,
)
from sevn.domain.bots import BotRecord, BotService
from sevn.domain.errors import DomainError
from sevn.protocol.registry import Ctx, method
from sevn.runtime.models import model_allowed


@method("bots.create", params=BotsCreateParams, result=BotRecord, mutating=True, scope="owner")
async def bots_create(ctx: Ctx, params: BotsCreateParams) -> BotRecord:
    _reject_unknown_model(params.model)
    try:
        bot = await BotService().create(
            params.name,
            title=_text(params.title),
            scope=_text(params.scope),
            instructions=_text(params.instructions),
            avatar=_text(params.avatar),
            runtime=_runtime(params.runtime),
            model=params.model,
            effort=params.effort,
            access=_access(params.access),
            approval_policy=_policy(params.approval_policy),
            folder_id=params.folder_id,
        )
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit("bot.updated", bot.id, _created_payload(bot))
    return bot


@method("bots.list", params=BotsListParams, result=BotsListResult, mutating=False)
async def bots_list(_ctx: Ctx, _params: BotsListParams) -> BotsListResult:
    return BotsListResult(bots=await BotService().list())


@method("bots.get", params=BotsGetParams, result=BotRecord, mutating=False)
async def bots_get(_ctx: Ctx, params: BotsGetParams) -> BotRecord:
    try:
        return await BotService().get(params.bot_id)
    except DomainError as exc:
        raise_protocol(exc)


@method("bots.update", params=BotsUpdateParams, result=BotRecord, mutating=True, scope="owner")
async def bots_update(ctx: Ctx, params: BotsUpdateParams) -> BotRecord:
    _reject_unknown_model(params.model)
    try:
        bot, changed = await BotService().update(
            params.bot_id,
            name=params.name,
            title=params.title,
            scope=params.scope,
            instructions=params.instructions,
            avatar=params.avatar,
            runtime=params.runtime,
            model=params.model,
            effort=params.effort,
            access=params.access,
            approval_policy=params.approval_policy,
            folder_id=params.folder_id,
            paused=params.paused,
            can_create_bots=params.can_create_bots,
            fields=params.model_fields_set,
        )
    except DomainError as exc:
        raise_protocol(exc)
    if changed:
        payload: dict[str, object] = {"bot_id": bot.id, **changed}
        await ctx.hub.emit("bot.updated", bot.id, payload)
    return bot


@method(
    "bots.delete",
    params=BotsDeleteParams,
    result=BotsDeleteResult,
    mutating=True,
    scope="owner",
)
async def bots_delete(ctx: Ctx, params: BotsDeleteParams) -> BotsDeleteResult:
    try:
        bot_id = await BotService().delete(params.bot_id, purge=params.purge)
    except DomainError as exc:
        raise_protocol(exc)
    await ctx.hub.emit("bot.deleted", bot_id, {"bot_id": bot_id})
    return BotsDeleteResult(id=bot_id)


def _reject_unknown_model(model: str | None) -> None:
    if model is None or model_allowed(model):
        return
    loc: list[JsonValue] = ["model"]
    error: dict[str, JsonValue] = {"loc": loc, "msg": "unknown model"}
    errors: list[JsonValue] = [error]
    data: JsonObject = {"errors": errors}
    raise ProtocolError("invalid_params", "invalid params", data)


def _text(value: str | None) -> str:
    return "" if value is None else value


def _runtime(value: RuntimeName | None) -> RuntimeName:
    return "pydantic_ai" if value is None else value


def _access(value: AccessName | None) -> AccessName:
    return "workspace" if value is None else value


def _policy(value: ApprovalPolicy | None) -> ApprovalPolicy:
    return "ask" if value is None else value


def _created_payload(bot: BotRecord) -> JsonObject:
    return {
        "bot_id": bot.id,
        "name": bot.name,
        "title": bot.title,
        "runtime": bot.runtime,
        "model": bot.model,
        "access": bot.access,
        "approval_policy": bot.approval_policy,
    }
