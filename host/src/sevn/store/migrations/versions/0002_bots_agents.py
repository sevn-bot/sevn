"""Bots, agents, threads, turns, messages, jobs, and pending requests."""

from __future__ import annotations

from alembic import op
from sevn.store.models import Agent, Bot, Job, Message, PendingRequest, Thread, Turn
from sqlalchemy import Table
from sqlalchemy.orm import DeclarativeBase

revision = "0002_bots_agents"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_UP = (Bot, Agent, Thread, Turn, Message, Job, PendingRequest)
_DOWN = (PendingRequest, Job, Message, Turn, Thread, Agent, Bot)


def upgrade() -> None:
    for model in _UP:
        _apply(model, drop=False)


def downgrade() -> None:
    for model in _DOWN:
        _apply(model, drop=True)


def _apply(model: type[DeclarativeBase], *, drop: bool) -> None:
    table = model.__table__
    if not isinstance(table, Table):
        raise RuntimeError(f"{model.__name__} has no table")
    bind = op.get_bind()
    if drop:
        table.drop(bind)
    else:
        table.create(bind)
