"""SQLAlchemy models for the host store (D2, D10, D11)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    TypeDecorator,
)
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import NullType


class Base(DeclarativeBase):
    pass


class _IsoDateTime(TypeDecorator[datetime]):
    """DateTime column whose SQLite text keeps the UTC offset."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def bind_processor(self, dialect: Dialect) -> Any:
        _ = dialect

        def process(value: datetime | None) -> Any:
            if value is None:
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.isoformat()

        return process

    def result_processor(self, dialect: Dialect, coltype: Any) -> Any:
        _ = (dialect, coltype)

        def process(value: Any) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    return value.replace(tzinfo=UTC)
                return value
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed

        return process


class Event(Base):
    __tablename__ = "events"
    __table_args__ = ({"sqlite_autoincrement": True},)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    entity: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OpLogEntry(Base):
    __tablename__ = "op_log"

    op_id: Mapped[str] = mapped_column(String, primary_key=True)
    method: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    instructions: Mapped[str] = mapped_column(String, nullable=False)
    avatar: Mapped[str] = mapped_column(String, nullable=False)
    runtime: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    effort: Mapped[str | None] = mapped_column(String, nullable=True)
    access: Mapped[str] = mapped_column(String, nullable=False)
    approval_policy: Mapped[str] = mapped_column(String, nullable=False)
    workspace_path: Mapped[str] = mapped_column(String, nullable=False)
    folder_id: Mapped[str | None] = mapped_column(String, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    can_create_bots: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    network: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="off",
        server_default="off",
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
    )
    # threads.agent_id is the foreign key. This column is plain text so the pair
    # can be inserted together; deleting the agent still cascades the thread.
    thread_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    runtime: Mapped[str] = mapped_column(String, nullable=False)
    runtime_session_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    origin_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
    isolation: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    summary_upto: Mapped[str | None] = mapped_column(String, nullable=True)


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    usage: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    model_messages: Mapped[list[object] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    parts: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Orders a flush so a new turn row exists before its messages.
    turn: Mapped[Turn] = relationship(foreign_keys=[turn_id])


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    to_bot_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
    )
    route_decision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    attachments: Mapped[list[object]] = mapped_column(JSON, nullable=False)
    reply_to: Mapped[str | None] = mapped_column(String, nullable=True)
    expects_reply: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hop: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(_IsoDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(_IsoDateTime, nullable=True)


class PendingRequest(Base):
    __tablename__ = "pending_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    answer: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DecisionLog(Base):
    """One step of a decision, with the redacted state that was scored (D6)."""

    __tablename__ = "decision_log"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    point: Mapped[str] = mapped_column(String, nullable=False)
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    state_redacted: Mapped[str] = mapped_column(String, nullable=False)
    answers: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    confidences: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    corrected_to: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RouteDecisionRow(Base):
    """Links a stored message to the decision log (D6)."""

    __tablename__ = "route_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Memory(Base):
    """One bot memory. Later waves of this plan fill the table (D9)."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("bots.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryFts(Base):
    """Columns of the FTS5 ``memories_fts`` virtual table. The migration creates it."""

    __tablename__ = "memories_fts"

    id: Mapped[str | None] = mapped_column(String, primary_key=True, nullable=True)
    text: Mapped[str | None] = mapped_column(String, nullable=True)


class MemoryFtsConfig(Base):
    """FTS5 shadow table created with ``memories_fts``."""

    __tablename__ = "memories_fts_config"
    __table_args__ = ({"sqlite_with_rowid": False},)

    k: Mapped[str] = mapped_column(NullType, primary_key=True)
    v: Mapped[str | None] = mapped_column(NullType, nullable=True)


class MemoryFtsContent(Base):
    """FTS5 shadow table created with ``memories_fts``."""

    __tablename__ = "memories_fts_content"

    id: Mapped[int | None] = mapped_column(Integer, primary_key=True, nullable=True)
    c0: Mapped[str | None] = mapped_column(NullType, nullable=True)
    c1: Mapped[str | None] = mapped_column(NullType, nullable=True)


class MemoryFtsData(Base):
    """FTS5 shadow table created with ``memories_fts``."""

    __tablename__ = "memories_fts_data"

    id: Mapped[int | None] = mapped_column(Integer, primary_key=True, nullable=True)
    block: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class MemoryFtsDocsize(Base):
    """FTS5 shadow table created with ``memories_fts``."""

    __tablename__ = "memories_fts_docsize"

    id: Mapped[int | None] = mapped_column(Integer, primary_key=True, nullable=True)
    sz: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class MemoryFtsIdx(Base):
    """FTS5 shadow table created with ``memories_fts``."""

    __tablename__ = "memories_fts_idx"
    __table_args__ = ({"sqlite_with_rowid": False},)

    segid: Mapped[str] = mapped_column(NullType, primary_key=True)
    term: Mapped[str] = mapped_column(NullType, primary_key=True)
    pgno: Mapped[str | None] = mapped_column(NullType, nullable=True)


class MessageFts(Base):
    """Search index for UI messages. Amended with the history wave."""

    __tablename__ = "messages_fts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    text: Mapped[str] = mapped_column(String, nullable=False)


class AgentLock(Base):
    """Advisory lock on a shared workspace path (D20)."""

    __tablename__ = "agent_locks"

    path: Mapped[str] = mapped_column(String, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
