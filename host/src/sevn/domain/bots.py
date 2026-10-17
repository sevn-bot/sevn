"""Bot profile, workspace, and CRUD (D2, D9)."""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select

from sevn.config import Settings
from sevn.contracts.kinds import AccessName, ApprovalPolicy, RuntimeName
from sevn.domain.errors import DomainError
from sevn.domain.ids import new_id
from sevn.domain.session import open_session
from sevn.paths import Paths
from sevn.secrets.backends import open_backend
from sevn.secrets.errors import SecretNotFound
from sevn.store.db import utcnow
from sevn.store.models import Bot as BotRow

_PROVIDERS = ("anthropic", "openai", "google", "openrouter")


class BotRecord(BaseModel):
    """One persisted bot, returned by the service and the protocol."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    title: str
    scope: str
    instructions: str
    avatar: str
    runtime: RuntimeName
    model: str
    effort: str | None
    access: AccessName
    approval_policy: ApprovalPolicy
    workspace_path: str
    folder_id: str | None
    paused: bool
    can_create_bots: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class BotService:
    """Create, read, update, and delete bots. No bot is created at startup."""

    async def create(
        self,
        name: str,
        *,
        title: str = "",
        scope: str = "",
        instructions: str = "",
        avatar: str = "",
        runtime: RuntimeName = "pydantic_ai",
        model: str | None = None,
        effort: str | None = None,
        access: AccessName = "workspace",
        approval_policy: ApprovalPolicy = "ask",
        folder_id: str | None = None,
        paused: bool = False,
        can_create_bots: bool = True,
        created_by: str = "user",
    ) -> BotRecord:
        bot_id = new_id("bot_")
        workspace = _workspace(bot_id)
        chosen_model = model if model is not None else await asyncio.to_thread(_default_model)
        now = utcnow()
        row = BotRow(
            id=bot_id,
            name=name,
            title=title,
            scope=scope,
            instructions=instructions,
            avatar=avatar,
            runtime=runtime,
            model=chosen_model,
            effort=effort,
            access=access,
            approval_policy=approval_policy,
            workspace_path=str(workspace),
            folder_id=folder_id,
            paused=paused,
            can_create_bots=can_create_bots,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        await asyncio.to_thread(_make_workspace, workspace)
        try:
            async with open_session() as session:
                session.add(row)
                await session.commit()
        except Exception:
            await asyncio.to_thread(_remove_workspace, workspace)
            raise
        return _record(row)

    async def get(self, bot_id: str) -> BotRecord:
        async with open_session() as session:
            row = await session.get(BotRow, bot_id)
            if row is None:
                raise DomainError("not_found", "bot not found")
            return _record(row)

    async def list(self) -> list[BotRecord]:
        async with open_session() as session:
            rows = list(await session.scalars(select(BotRow).order_by(BotRow.updated_at.desc())))
            return [_record(row) for row in rows]

    async def update(
        self,
        bot_id: str,
        *,
        name: str | None = None,
        title: str | None = None,
        scope: str | None = None,
        instructions: str | None = None,
        avatar: str | None = None,
        runtime: RuntimeName | None = None,
        model: str | None = None,
        effort: str | None = None,
        access: AccessName | None = None,
        approval_policy: ApprovalPolicy | None = None,
        folder_id: str | None = None,
        paused: bool | None = None,
        can_create_bots: bool | None = None,
        fields: set[str],
    ) -> tuple[BotRecord, dict[str, object]]:
        async with open_session() as session:
            row = await session.get(BotRow, bot_id)
            if row is None:
                raise DomainError("not_found", "bot not found")
            applied = _apply(
                row,
                fields,
                name=name,
                title=title,
                scope=scope,
                instructions=instructions,
                avatar=avatar,
                runtime=runtime,
                model=model,
                effort=effort,
                access=access,
                approval_policy=approval_policy,
                folder_id=folder_id,
                paused=paused,
                can_create_bots=can_create_bots,
            )
            if applied:
                row.updated_at = utcnow()
                await session.commit()
            return _record(row), applied

    async def delete(self, bot_id: str, *, purge: bool) -> str:
        async with open_session() as session:
            row = await session.get(BotRow, bot_id)
            if row is None:
                raise DomainError("not_found", "bot not found")
            workspace = Path(row.workspace_path)
            await session.execute(delete(BotRow).where(BotRow.id == bot_id))
            await session.commit()
        if purge:
            await asyncio.to_thread(_remove_workspace, workspace)
        return bot_id


def _apply(
    row: BotRow,
    fields: set[str],
    *,
    name: str | None,
    title: str | None,
    scope: str | None,
    instructions: str | None,
    avatar: str | None,
    runtime: RuntimeName | None,
    model: str | None,
    effort: str | None,
    access: AccessName | None,
    approval_policy: ApprovalPolicy | None,
    folder_id: str | None,
    paused: bool | None,
    can_create_bots: bool | None,
) -> dict[str, object]:
    applied: dict[str, object] = {}
    if "name" in fields and name is not None:
        row.name = name
        applied["name"] = name
    if "title" in fields and title is not None:
        row.title = title
        applied["title"] = title
    if "scope" in fields and scope is not None:
        row.scope = scope
        applied["scope"] = scope
    if "instructions" in fields and instructions is not None:
        row.instructions = instructions
        applied["instructions"] = instructions
    if "avatar" in fields and avatar is not None:
        row.avatar = avatar
        applied["avatar"] = avatar
    if "runtime" in fields and runtime is not None:
        row.runtime = runtime
        applied["runtime"] = runtime
    if "model" in fields and model is not None:
        row.model = model
        applied["model"] = model
    if "effort" in fields and effort is not None:
        row.effort = effort
        applied["effort"] = effort
    if "access" in fields and access is not None:
        row.access = access
        applied["access"] = access
    if "approval_policy" in fields and approval_policy is not None:
        row.approval_policy = approval_policy
        applied["approval_policy"] = approval_policy
    if "folder_id" in fields and folder_id is not None:
        row.folder_id = folder_id
        applied["folder_id"] = folder_id
    if "paused" in fields and paused is not None:
        row.paused = paused
        applied["paused"] = paused
    if "can_create_bots" in fields and can_create_bots is not None:
        row.can_create_bots = can_create_bots
        applied["can_create_bots"] = can_create_bots
    return applied


def _record(row: BotRow) -> BotRecord:
    return BotRecord(
        id=row.id,
        name=row.name,
        title=row.title,
        scope=row.scope,
        instructions=row.instructions,
        avatar=row.avatar,
        runtime=_runtime(row.runtime),
        model=row.model,
        effort=row.effort,
        access=_access(row.access),
        approval_policy=_policy(row.approval_policy),
        workspace_path=row.workspace_path,
        folder_id=row.folder_id,
        paused=row.paused,
        can_create_bots=row.can_create_bots,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _runtime(value: str) -> RuntimeName:
    if value == "pydantic_ai" or value == "claude":
        return value
    raise DomainError("invalid_params", "unknown runtime")


def _access(value: str) -> AccessName:
    if value == "workspace" or value == "full" or value == "isolated":
        return value
    raise DomainError("invalid_params", "unknown access")


def _policy(value: str) -> ApprovalPolicy:
    if value == "ask" or value == "auto" or value == "allow_all":
        return value
    raise DomainError("invalid_params", "unknown approval policy")


def _workspace(bot_id: str) -> Path:
    return (Paths.from_env().workspaces / bot_id).resolve()


def _make_workspace(path: Path) -> None:
    (path / "tasks").mkdir(parents=True, exist_ok=True)


def _remove_workspace(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)


def _default_model() -> str:
    from sevn.runtime.models import ECHO_ID, echo_enabled, first_catalog_id

    backend = open_backend(Settings.load(), Paths.from_env())
    for name in _PROVIDERS:
        try:
            backend.get(f"provider/{name}")
        except SecretNotFound:
            continue
        return first_catalog_id(name)
    # The e2e host has no provider key. Echo is the only model when both dev flags are on.
    if echo_enabled():
        return ECHO_ID
    return ""
