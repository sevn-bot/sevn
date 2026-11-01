"""Method registry types (D10, D13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sevn.contracts.kinds import AccessName, ApprovalPolicy, NetworkFlag, RuntimeName
from sevn.domain.agents import AgentRecord
from sevn.domain.bots import BotRecord
from sevn.domain.fleet import FleetOverview
from sevn.domain.jobs import MessageRecord
from sevn.domain.pending import PendingRecord
from sevn.memory.store import MemoryRecord


class SystemInfoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemCaps(BaseModel):
    """Capabilities ``system.info`` reports to every client (D14)."""

    model_config = ConfigDict(extra="forbid")

    allow_all: bool


class SystemInfoResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_id: str
    version: str
    proto: int
    caps: SystemCaps
    host_pubkey_fp: str


class SystemPingParams(BaseModel):
    """`op_id` is optional here; dispatch requires it when `mutating` is set (D11)."""

    model_config = ConfigDict(extra="forbid")

    note: str
    op_id: str | None = None


class SystemPingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int


_SEQ_MAX = 2**63 - 1
_SYNC_PAGE_DEFAULT = 200
_SYNC_PAGE_MAX = 500


class SyncSinceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0, le=_SEQ_MAX)
    limit: int = Field(default=_SYNC_PAGE_DEFAULT, ge=1, le=_SYNC_PAGE_MAX)


class SyncSinceResult(BaseModel):
    """Head of the log, plus the cursor for the next page of `evt` frames."""

    model_config = ConfigDict(extra="forbid")

    host_seq: int
    next_seq: int
    more: bool


class SandboxModeParams(BaseModel):
    """Owner confirm phrase for ``host.set_sandbox_mode`` (D14)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["allow_all", "enforced"]
    confirm: str
    op_id: str | None = None


class SandboxModeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["allow_all", "enforced"]


class BotsCreateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    title: str | None = None
    scope: str | None = None
    instructions: str | None = None
    avatar: str | None = None
    runtime: RuntimeName | None = None
    model: str | None = None
    effort: str | None = None
    access: AccessName | None = None
    approval_policy: ApprovalPolicy | None = None
    folder_id: str | None = None
    op_id: str | None = None


class BotsListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BotsListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bots: list[BotRecord]


class BotsGetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str


class BotsUpdateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    name: str | None = None
    title: str | None = None
    scope: str | None = None
    instructions: str | None = None
    avatar: str | None = None
    runtime: RuntimeName | None = None
    model: str | None = None
    effort: str | None = None
    access: AccessName | None = None
    approval_policy: ApprovalPolicy | None = None
    network: NetworkFlag | None = None
    folder_id: str | None = None
    paused: bool | None = None
    can_create_bots: bool | None = None
    op_id: str | None = None


class BotsDeleteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    purge: bool = False
    op_id: str | None = None


class BotsDeleteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str


class AgentsListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str


class AgentsListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentRecord]


class AgentsGetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    name: str


class ModelsListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelsListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[ModelInfo]


class MessagesSendParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    text: str
    agent_id: str | None = None
    new_agent: bool = False
    op_id: str | None = None


class MessagesSendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    agent_id: str


class MessagesRerouteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str
    agent_id: str | None = None
    new: bool = False
    op_id: str | None = None


class MessagesRerouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    agent_id: str


class MessagesListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str
    cursor: str | None = None


class MessagesListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[MessageRecord]
    next_cursor: str | None


class PendingListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PendingListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending: list[PendingRecord]


class PendingAnswerParams(BaseModel):
    """An approval takes ``answer``. A question takes ``option_id`` or ``text``."""

    model_config = ConfigDict(extra="forbid")

    pending_id: str
    answer: Literal["approve", "deny"] | None = None
    option_id: str | None = None
    text: str | None = None
    op_id: str | None = None


class PendingAnswerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    job_id: str | None = None


class TurnsSnapshotParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str


class TurnsSnapshotResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    status: str


class TurnsCancelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    op_id: str | None = None


class TurnsCancelResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    status: str


class FleetOverviewParams(BaseModel):
    """``bot_id`` narrows only the finished list."""

    model_config = ConfigDict(extra="forbid")

    bot_id: str | None = None


class MemoriesListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_id: str


class MemoriesListResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[MemoryRecord]


class MemoriesUpdateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    revision: int | None = None
    op_id: str | None = None


class MemoriesDeleteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    op_id: str | None = None


class MemoriesDeleteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str


class MemoriesPinParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tier: Literal["pinned", "recall"] | None = None
    revision: int | None = None
    op_id: str | None = None


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
        _spec("host.set_sandbox_mode", SandboxModeParams, SandboxModeResult, mutating=True),
        _spec("sync.since", SyncSinceParams, SyncSinceResult, mutating=False),
        _spec("bots.create", BotsCreateParams, BotRecord, mutating=True),
        _spec("bots.list", BotsListParams, BotsListResult, mutating=False),
        _spec("bots.get", BotsGetParams, BotRecord, mutating=False),
        _spec("bots.update", BotsUpdateParams, BotRecord, mutating=True),
        _spec("bots.delete", BotsDeleteParams, BotsDeleteResult, mutating=True),
        _spec("agents.list", AgentsListParams, AgentsListResult, mutating=False),
        _spec("agents.get", AgentsGetParams, AgentRecord, mutating=False),
        _spec("models.list", ModelsListParams, ModelsListResult, mutating=False),
        _spec("messages.send", MessagesSendParams, MessagesSendResult, mutating=True),
        _spec("messages.reroute", MessagesRerouteParams, MessagesRerouteResult, mutating=True),
        _spec("messages.list", MessagesListParams, MessagesListResult, mutating=False),
        _spec("pending.list", PendingListParams, PendingListResult, mutating=False),
        _spec("pending.answer", PendingAnswerParams, PendingAnswerResult, mutating=True),
        _spec("turns.snapshot", TurnsSnapshotParams, TurnsSnapshotResult, mutating=False),
        _spec("turns.cancel", TurnsCancelParams, TurnsCancelResult, mutating=True),
        _spec("memories.list", MemoriesListParams, MemoriesListResult, mutating=False),
        _spec("memories.update", MemoriesUpdateParams, MemoryRecord, mutating=True),
        _spec("memories.delete", MemoriesDeleteParams, MemoriesDeleteResult, mutating=True),
        _spec("memories.pin", MemoriesPinParams, MemoryRecord, mutating=True),
        _spec("fleet.overview", FleetOverviewParams, FleetOverview, mutating=False),
    )
}
